from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_report.etf_monitor import (
    DEFAULT_ETF_SPECS,
    ETF_CACHE_PATH,
    _daily_returns,
    _distance_to_sma,
    _fetch_yahoo_price_data,
    _normalize_currency,
    _robust_trend_volatility,
    _safe_float,
    _sma,
)


UK_SYMBOL_OVERRIDES = {"IGTM": "IGTM.L", "ISF": "ISF.L", "ERNS": "ERNS.L"}
REVOLUT_TRANSACTION_FIELDS = (
    "Date",
    "Ticker",
    "Type",
    "Quantity",
    "Price per share",
    "Total Amount",
    "Currency",
    "FX Rate",
)
REVOLUT_STATEMENT_COLUMNS = set(REVOLUT_TRANSACTION_FIELDS)
PORTFOLIO_QUOTE_CACHE_PATH = Path("output") / "cache" / "portfolio_quote_cache.json"
PORTFOLIO_QUOTE_CACHE_MAX_AGE = timedelta(days=7)
_PORTFOLIO_QUOTE_CACHE: dict[str, dict[str, object]] | None = None
_PORTFOLIO_QUOTE_CACHE_DIRTY = False
_QUOTE_SOURCES: dict[str, str] = {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a Revolut trading statement CSV into portfolio.csv.")
    parser.add_argument("statement", nargs="+", help="One or more Revolut trading-account-statement CSV paths.")
    parser.add_argument("--output", default="portfolio.csv", help="Output portfolio CSV path.")
    args = parser.parse_args()

    statements = [Path(value) for value in args.statement]
    output = Path(args.output)
    missing = [statement for statement in statements if not statement.exists()]
    if missing:
        raise SystemExit("Statement file not found: " + ", ".join(str(path) for path in missing))

    statements = [statement for statement in statements if _is_revolut_statement(statement)]
    if not statements:
        raise SystemExit("No valid Revolut trading statement CSV found after checking file headers.")
    positions = _reconstruct_positions(statements)
    if not positions:
        raise SystemExit("No open positions found in Revolut statement.")
    rows = _build_portfolio_rows(positions)
    try:
        output.write_text(_to_csv(rows), encoding="utf-8")
    except PermissionError as exc:
        raise SystemExit(
            f"Cannot update {output}: the file is locked. Close portfolio.csv in Excel or another editor, then run again."
        ) from exc

    print(f"Portfolio written to {output.resolve()}")
    print(f"Open positions: {len(rows)}")
    covered = [row["symbol"] for row in rows if row["monitor_status"] == "covered"]
    uncovered = [row["symbol"] for row in rows if row["monitor_status"] != "covered"]
    print("Covered ETF monitor symbols: " + (", ".join(covered) if covered else "none"))
    print("Outside ETF monitor pool: " + (", ".join(uncovered) if uncovered else "none"))
    return 0


def _reconstruct_positions(paths: list[Path]) -> dict[str, dict[str, float]]:
    positions: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "quantity": 0.0,
            "cost_gbp": 0.0,
            "realized_pnl_gbp": 0.0,
            "dividend_income_gbp": 0.0,
            "unmatched_sell_proceeds_gbp": 0.0,
        }
    )
    rows, duplicate_count = _unique_transaction_rows(paths)
    if duplicate_count:
        print(f"Removed {duplicate_count} duplicate transaction row(s) across overlapping statements.")
    for row in rows:
        ticker = str(row.get("Ticker") or "").strip().upper()
        transaction_type = str(row.get("Type") or "").strip().upper()
        quantity = _safe_float(row.get("Quantity"))
        if not ticker:
            continue
        if transaction_type == "DIVIDEND":
            positions[ticker]["dividend_income_gbp"] += _parse_money(row.get("Total Amount")) or 0
            continue
        if quantity is None:
            continue
        if transaction_type.startswith("BUY"):
            price = _parse_money(row.get("Price per share"))
            positions[ticker]["quantity"] += quantity
            positions[ticker]["cost_gbp"] += quantity * (price or 0)
        elif transaction_type.startswith("SELL"):
            current_quantity = positions[ticker]["quantity"]
            average_cost = positions[ticker]["cost_gbp"] / current_quantity if current_quantity else 0
            price = _parse_money(row.get("Price per share"))
            proceeds = _parse_money(row.get("Total Amount"))
            matched_quantity = min(quantity, max(current_quantity, 0))
            matched_proceeds = matched_quantity * (price or 0)
            unmatched_quantity = max(quantity - matched_quantity, 0)
            positions[ticker]["realized_pnl_gbp"] += matched_proceeds - average_cost * matched_quantity
            positions[ticker]["unmatched_sell_proceeds_gbp"] += (
                unmatched_quantity * (price or 0) if price is not None else (proceeds or 0)
            )
            positions[ticker]["quantity"] -= matched_quantity
            positions[ticker]["cost_gbp"] -= average_cost * matched_quantity
        elif transaction_type == "STOCK SPLIT":
            positions[ticker]["quantity"] += quantity
    return positions


def _unique_transaction_rows(paths: list[Path]) -> tuple[list[dict[str, str]], int]:
    rows_by_fingerprint: dict[tuple[str, ...], dict[str, str]] = {}
    duplicate_count = 0
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                fingerprint = tuple(_normalize_statement_cell(row.get(field)) for field in REVOLUT_TRANSACTION_FIELDS)
                if fingerprint in rows_by_fingerprint:
                    duplicate_count += 1
                    continue
                rows_by_fingerprint[fingerprint] = row
    rows = sorted(rows_by_fingerprint.values(), key=lambda row: _normalize_statement_cell(row.get("Date")))
    return rows, duplicate_count


def _normalize_statement_cell(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _is_revolut_statement(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            headers = set(next(csv.reader(handle), []))
    except (OSError, UnicodeDecodeError, csv.Error):
        return False
    valid = REVOLUT_STATEMENT_COLUMNS.issubset(headers)
    if not valid:
        print(f"Skipping non-Revolut CSV: {path}", file=sys.stderr)
    return valid


def _build_portfolio_rows(positions: dict[str, dict[str, float]]) -> list[dict[str, str]]:
    monitor_symbols = {spec.symbol[:-2] if spec.symbol.endswith(".L") else spec.symbol: spec.symbol for spec in DEFAULT_ETF_SPECS}
    fx_quotes = {
        "USD": _latest_quote("GBPUSD=X"),
        "EUR": _latest_quote("GBPEUR=X"),
    }
    fx_as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    valued = []
    for ticker, position in positions.items():
        quantity = position["quantity"]
        if quantity <= 1e-8:
            continue
        monitor_symbol = monitor_symbols.get(ticker) or UK_SYMBOL_OVERRIDES.get(ticker) or _resolve_lse_etf_symbol(ticker)
        yahoo_symbol = monitor_symbol or ticker
        price, previous_price, native_currency, history = _latest_quote(yahoo_symbol)
        price_source = _QUOTE_SOURCES.get(yahoo_symbol, f"Yahoo:{yahoo_symbol}")
        fx_pair = ""
        fx_rate = 1.0 if native_currency == "GBP" else None
        if native_currency in fx_quotes:
            fx_pair = f"GBP/{native_currency}"
            fx_rate = fx_quotes[native_currency][0]
        price_gbp = price / fx_rate if price is not None and fx_rate not in (None, 0) else None
        if fx_pair:
            price_source += f" | FX:{fx_pair}"
        average_cost = position["cost_gbp"] / quantity if quantity else 0.0
        if price_gbp is None:
            price_gbp = average_cost or None
            price_source = "statement-average-cost fallback"
        market_value_native = quantity * price if price is not None else None
        market_value = quantity * price_gbp if price_gbp is not None else 0.0
        unrealized = market_value - position["cost_gbp"]
        unrealized_pct = unrealized / position["cost_gbp"] * 100 if position["cost_gbp"] else None
        realized_pnl = position.get("realized_pnl_gbp", 0.0)
        dividend_income = position.get("dividend_income_gbp", 0.0)
        total_return = unrealized + realized_pnl + dividend_income
        day_change_pct = (price / previous_price - 1) * 100 if price is not None and previous_price not in (None, 0) else None
        peak_price, peak_date, drawdown_from_peak_pct = _year_peak_snapshot(history)
        (
            sma200,
            distance_sma200_pct,
            daily_volatility_pct,
            pullback_sigma_1m,
            yellow_drawdown_threshold_pct,
            red_drawdown_threshold_pct,
            drawdown_regime,
        ) = (
            _portfolio_drawdown_snapshot(history, drawdown_from_peak_pct)
        )
        peak_watch = _peak_watch_label(
            drawdown_from_peak_pct,
            yellow_drawdown_threshold_pct,
            red_drawdown_threshold_pct,
        )
        valued.append(
            {
                "symbol": monitor_symbol or ticker,
                "quantity": quantity,
                "average_cost": average_cost,
                "current_price": price_gbp,
                "native_currency": native_currency,
                "current_price_native": price,
                "market_value_native": market_value_native,
                "market_value": market_value,
                "unrealized_pnl": unrealized,
                "unrealized_pnl_pct": unrealized_pct,
                "realized_pnl": realized_pnl,
                "dividend_income": dividend_income,
                "total_return": total_return,
                "day_change_pct": day_change_pct,
                "year_peak_price_native": peak_price,
                "year_peak_date": peak_date.isoformat() if peak_date else "",
                "drawdown_from_year_peak_pct": drawdown_from_peak_pct,
                "peak_watch": peak_watch,
                "sma200_native": sma200,
                "distance_sma200_pct": distance_sma200_pct,
                "daily_volatility_pct": daily_volatility_pct,
                "pullback_sigma_1m": pullback_sigma_1m,
                "yellow_drawdown_threshold_pct": yellow_drawdown_threshold_pct,
                "red_drawdown_threshold_pct": red_drawdown_threshold_pct,
                "drawdown_regime": drawdown_regime,
                "fx_pair": fx_pair,
                "fx_rate": fx_rate,
                "fx_as_of": fx_as_of,
                "price_source": price_source,
                "monitor_status": "covered" if monitor_symbol else "outside-monitor-pool",
            }
        )
    total = sum(item["market_value"] for item in valued)
    account_realized_pnl = sum(item.get("realized_pnl_gbp", 0.0) for item in positions.values())
    account_dividend_income = sum(item.get("dividend_income_gbp", 0.0) for item in positions.values())
    unmatched_sell_proceeds = sum(item.get("unmatched_sell_proceeds_gbp", 0.0) for item in positions.values())
    account_unrealized_pnl = sum(item["unrealized_pnl"] for item in valued)
    account_total_return = account_unrealized_pnl + account_realized_pnl + account_dividend_income
    rows = []
    for item in sorted(valued, key=lambda value: value["market_value"], reverse=True):
        weight = item["market_value"] / total * 100 if total else 0.0
        rows.append(
            {
                "symbol": str(item["symbol"]),
                "weight_pct": f"{weight:.4f}",
                "quantity": f"{item['quantity']:.8f}".rstrip("0").rstrip("."),
                "average_cost_gbp": _fmt_number(item["average_cost"]),
                "current_price_gbp": _fmt_number(item["current_price"]),
                "native_currency": str(item["native_currency"] or ""),
                "current_price_native": _fmt_number(item["current_price_native"]),
                "market_value_native": _fmt_number(item["market_value_native"]),
                "estimated_market_value_gbp": f"{item['market_value']:.2f}",
                "unrealized_pnl_gbp": _fmt_number(item["unrealized_pnl"]),
                "unrealized_pnl_pct": _fmt_number(item["unrealized_pnl_pct"]),
                "realized_pnl_gbp": _fmt_number(item["realized_pnl"]),
                "dividend_income_gbp": _fmt_number(item["dividend_income"]),
                "total_return_gbp": _fmt_number(item["total_return"]),
                "account_unrealized_pnl_gbp": _fmt_number(account_unrealized_pnl),
                "account_realized_pnl_gbp": _fmt_number(account_realized_pnl),
                "account_dividend_income_gbp": _fmt_number(account_dividend_income),
                "account_total_return_gbp": _fmt_number(account_total_return),
                "unmatched_sell_proceeds_gbp": _fmt_number(unmatched_sell_proceeds),
                "day_change_pct": _fmt_number(item["day_change_pct"]),
                "year_peak_price_native": _fmt_number(item["year_peak_price_native"]),
                "year_peak_date": str(item["year_peak_date"]),
                "drawdown_from_year_peak_pct": _fmt_number(item["drawdown_from_year_peak_pct"]),
                "peak_watch": str(item["peak_watch"]),
                "sma200_native": _fmt_number(item["sma200_native"]),
                "distance_sma200_pct": _fmt_number(item["distance_sma200_pct"]),
                "daily_volatility_pct": _fmt_number(item["daily_volatility_pct"]),
                "pullback_sigma_1m": _fmt_number(item["pullback_sigma_1m"]),
                "yellow_drawdown_threshold_pct": _fmt_number(item["yellow_drawdown_threshold_pct"]),
                "red_drawdown_threshold_pct": _fmt_number(item["red_drawdown_threshold_pct"]),
                "drawdown_regime": str(item["drawdown_regime"]),
                "fx_pair": str(item["fx_pair"]),
                "fx_rate": _fmt_number(item["fx_rate"]),
                "fx_as_of": str(item["fx_as_of"]),
                "price_source": str(item["price_source"]),
                "monitor_status": str(item["monitor_status"]),
            }
        )
    _save_portfolio_quote_cache()
    return rows


def _latest_quote(symbol: str) -> tuple[float | None, float | None, str, list[tuple[date, float]]]:
    try:
        # Portfolio imports are batch jobs. Use a short live probe here; the shared
        # Yahoo reader already checks both query endpoints before cache fallback.
        price_data = _fetch_yahoo_price_data(symbol, timeout=5, attempts=1)
        history = price_data.history
        if history:
            currency = _normalize_currency(price_data.meta.get("currency")) or ""
            previous = history[-2][1] if len(history) > 1 else None
            _store_portfolio_quote_cache(symbol, history[-1][1], previous, currency, history)
            _QUOTE_SOURCES[symbol] = f"Yahoo:{symbol}"
            return history[-1][1], previous, currency, history
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    cached = _portfolio_quote_from_cache(symbol)
    if cached is not None:
        _QUOTE_SOURCES[symbol] = f"Yahoo cache:{symbol}"
        return cached
    etf_cached = _etf_monitor_quote_from_cache(symbol)
    if etf_cached is not None:
        _QUOTE_SOURCES[symbol] = f"ETF monitor cache:{symbol}"
        return etf_cached
    if "error" in locals():
        print(f"Quote unavailable for {symbol}; using statement cost fallback. Last error: {error}", file=sys.stderr)
    return None, None, "", []


def _resolve_lse_etf_symbol(ticker: str) -> str | None:
    if "." in ticker:
        return ticker if ticker.endswith(".L") else None
    candidate = f"{ticker}.L"
    try:
        data = _fetch_yahoo_price_data(candidate, timeout=5, attempts=1)
    except Exception:
        return None
    meta = data.meta or {}
    exchange = str(meta.get("exchangeName") or "")
    instrument = str(meta.get("instrumentType") or "")
    long_name = str(meta.get("longName") or meta.get("shortName") or "")
    if exchange == "LSE" and instrument in {"ETF", "ETC"}:
        _QUOTE_SOURCES[candidate] = f"Yahoo:{candidate}"
        return candidate
    if exchange == "LSE" and any(token in long_name.lower() for token in ("ucits etf", "physical gold")):
        _QUOTE_SOURCES[candidate] = f"Yahoo:{candidate}"
        return candidate
    return None


def _load_portfolio_quote_cache() -> dict[str, dict[str, object]]:
    global _PORTFOLIO_QUOTE_CACHE
    if _PORTFOLIO_QUOTE_CACHE is not None:
        return _PORTFOLIO_QUOTE_CACHE
    try:
        payload = json.loads(PORTFOLIO_QUOTE_CACHE_PATH.read_text(encoding="utf-8"))
        _PORTFOLIO_QUOTE_CACHE = dict(payload.get("quotes") or {})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _PORTFOLIO_QUOTE_CACHE = {}
    return _PORTFOLIO_QUOTE_CACHE


def _store_portfolio_quote_cache(
    symbol: str,
    value: float,
    previous_value: float | None,
    currency: str,
    history: list[tuple[date, float]],
) -> None:
    global _PORTFOLIO_QUOTE_CACHE_DIRTY
    cache = _load_portfolio_quote_cache()
    cache[symbol] = {
        "value": value,
        "previous_value": previous_value,
        "currency": currency,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "history": [[day.isoformat(), price] for day, price in history[-1500:]],
    }
    _PORTFOLIO_QUOTE_CACHE_DIRTY = True


def _save_portfolio_quote_cache() -> None:
    global _PORTFOLIO_QUOTE_CACHE_DIRTY
    if not _PORTFOLIO_QUOTE_CACHE_DIRTY:
        return
    PORTFOLIO_QUOTE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"quotes": _load_portfolio_quote_cache()}
    PORTFOLIO_QUOTE_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _PORTFOLIO_QUOTE_CACHE_DIRTY = False


def _portfolio_quote_from_cache(
    symbol: str,
) -> tuple[float | None, float | None, str, list[tuple[date, float]]] | None:
    entry = _load_portfolio_quote_cache().get(symbol)
    if not entry or not _is_fresh_cache_entry(entry):
        return None
    history = _parse_cached_history(entry.get("history"))
    value = _safe_float(entry.get("value"))
    if value is None:
        return None
    return value, _safe_float(entry.get("previous_value")), str(entry.get("currency") or ""), history


def _etf_monitor_quote_from_cache(
    symbol: str,
) -> tuple[float | None, float | None, str, list[tuple[date, float]]] | None:
    try:
        payload = json.loads(ETF_CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    for entry in (payload.get("assets") or {}).values():
        if str(entry.get("symbol") or "").upper() != symbol.upper() or not _is_fresh_cache_entry(entry):
            continue
        value = _safe_float(entry.get("value"))
        if value is None:
            return None
        return value, _safe_float(entry.get("previous_value")), str(entry.get("currency") or ""), []
    return None


def _is_fresh_cache_entry(entry: dict[str, object]) -> bool:
    try:
        fetched_at = datetime.fromisoformat(str(entry.get("fetched_at") or ""))
    except ValueError:
        return False
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched_at <= PORTFOLIO_QUOTE_CACHE_MAX_AGE


def _parse_cached_history(raw: object) -> list[tuple[date, float]]:
    history = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, list) or len(item) != 2:
            continue
        value = _safe_float(item[1])
        if value is None:
            continue
        try:
            history.append((date.fromisoformat(str(item[0])), value))
        except ValueError:
            continue
    return history


def _year_peak_snapshot(history: list[tuple[date, float]]) -> tuple[float | None, date | None, float | None]:
    if not history:
        return None, None, None
    latest_date, latest_price = history[-1]
    year_start = date(latest_date.year, 1, 1)
    current_year = [(day, price) for day, price in history if day >= year_start]
    if not current_year:
        return None, None, None
    peak_date, peak_price = max(current_year, key=lambda item: item[1])
    drawdown = (latest_price / peak_price - 1) * 100 if peak_price else None
    return peak_price, peak_date, drawdown


def _peak_watch_label(drawdown_pct: float | None, yellow_threshold: float = 5, red_threshold: float = 10) -> str:
    if drawdown_pct is None:
        return "数据不足"
    if drawdown_pct <= -red_threshold:
        return f"红色观察：较年内高点回撤超过自适应阈值{red_threshold:.1f}%，需复核趋势、估值与仓位风险"
    if drawdown_pct <= -yellow_threshold:
        return f"黄色观察：较年内高点回撤超过自适应阈值{yellow_threshold:.1f}%，需观察回撤性质与支撑位"
    return f"常态：距年内高点回撤仍在自适应阈值{yellow_threshold:.1f}%以内"


def _parse_money(raw: object) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    parts = text.replace(",", "").split()
    return _safe_float(parts[-1])


def _portfolio_drawdown_snapshot(
    history: list[tuple[date, float]], drawdown_pct: float | None
) -> tuple[float | None, float | None, float | None, float | None, float, float, str]:
    values = [price for _, price in history]
    latest_price = values[-1] if values else None
    sma200 = _sma(values, 200)
    distance_sma200_pct = _distance_to_sma(latest_price, sma200)
    daily_volatility_pct = _robust_trend_volatility(_daily_returns(values))
    pullback_sigma_1m = (
        abs(drawdown_pct) / (daily_volatility_pct * math.sqrt(21))
        if drawdown_pct is not None and daily_volatility_pct not in (None, 0)
        else None
    )
    yellow_threshold, red_threshold = _adaptive_drawdown_thresholds(daily_volatility_pct)
    return (
        sma200,
        distance_sma200_pct,
        daily_volatility_pct,
        pullback_sigma_1m,
        yellow_threshold,
        red_threshold,
        _drawdown_regime_label(
            drawdown_pct,
            distance_sma200_pct,
            pullback_sigma_1m,
            yellow_threshold,
            red_threshold,
        ),
    )


def _adaptive_drawdown_thresholds(daily_volatility_pct: float | None) -> tuple[float, float]:
    monthly_volatility = daily_volatility_pct * math.sqrt(21) if daily_volatility_pct is not None else 0
    return max(5.0, monthly_volatility), max(10.0, monthly_volatility * 2)


def _drawdown_regime_label(
    drawdown_pct: float | None,
    distance_sma200_pct: float | None,
    pullback_sigma_1m: float | None,
    yellow_threshold: float = 5,
    red_threshold: float = 10,
) -> str:
    if drawdown_pct is None:
        return "数据不足：暂无法判断回撤性质"
    if drawdown_pct > -yellow_threshold and (distance_sma200_pct is None or distance_sma200_pct > -3):
        return f"常态波动：距年内高点回撤仍在自适应阈值{yellow_threshold:.1f}%以内"
    if distance_sma200_pct is not None and distance_sma200_pct >= 0 and (
        pullback_sigma_1m is None or pullback_sigma_1m < 2
    ):
        return "正常回调观察：仍位于SMA200上方，回撤尚未显著偏离近期波动区间"
    if (distance_sma200_pct is not None and distance_sma200_pct <= -3) or (
        drawdown_pct <= -red_threshold and pullback_sigma_1m is not None and pullback_sigma_1m >= 2
    ):
        return "趋势破坏风险：回撤较深且中期趋势或波动结构已转弱"
    return "需要复核：回撤超过常态区间，需结合SMA200、波动率与基本面事件判断"


def _fmt_number(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def _to_csv(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    from io import StringIO

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
