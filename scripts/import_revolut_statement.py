from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_report.technical_indicators import ema as shared_ema
from market_report.etf_monitor import (
    DEFAULT_ETF_SPECS,
    ETF_CACHE_PATH,
    _read_json,
    _daily_returns,
    _distance_to_sma,
    _fetch_yahoo_price_data,
    _normalize_currency,
    _rsi,
    _robust_trend_volatility,
    _safe_float,
    _sma,
)


UK_SYMBOL_OVERRIDES = {"IGTM": "IGTM.L", "ISF": "ISF.L", "ERNS": "ERNS.L"}
KNOWN_US_EQUITIES = {
    "AVGO",
    "GOOGL",
    "KO",
    "LITE",
    "META",
    "MSFT",
    "NFLX",
    "NVDA",
    "QBTS",
    "RKLB",
}
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
REVOLUT_TRANSACTION_ID_FIELDS = ("Date", "Ticker", "Type", "Quantity")
REVOLUT_STATEMENT_COLUMNS = set(REVOLUT_TRANSACTION_FIELDS)
PORTFOLIO_QUOTE_CACHE_PATH = Path("output") / "cache" / "portfolio_quote_cache.json"
PORTFOLIO_QUOTE_CACHE_MAX_AGE = timedelta(days=7)
_PORTFOLIO_QUOTE_CACHE: dict[str, dict[str, object]] | None = None
_PORTFOLIO_QUOTE_CACHE_DIRTY = False
_QUOTE_SOURCES: dict[str, str] = {}
_QUOTE_META: dict[str, dict[str, object]] = {}
CASH_LIKE_DISTRIBUTION_SYMBOLS = {"ERNS", "ERNS.L"}


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


def _reconstruct_positions(paths: list[Path]) -> dict[str, dict[str, object]]:
    positions: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "quantity": 0.0,
            "cost_gbp": 0.0,
            "realized_pnl_gbp": 0.0,
            "dividend_income_gbp": 0.0,
            "unmatched_sell_proceeds_gbp": 0.0,
            "unmatched_sells": [],
            "implied_trading_cost_gbp": 0.0,
            "transaction_costs": [],
            "lots": [],
            "closed_trades": [],
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
            positions[ticker]["dividend_income_gbp"] = float(positions[ticker]["dividend_income_gbp"]) + (
                _parse_money(row.get("Total Amount")) or 0
            )
            continue
        if quantity is None:
            continue
        trade_date = _parse_statement_date(row.get("Date"))
        if transaction_type.startswith("BUY"):
            price = _parse_money(row.get("Price per share"))
            gross_cost = quantity * (price or 0)
            cash_cost = _buy_cash_cost(row.get("Total Amount"), gross_cost)
            implied_cost = max(cash_cost - gross_cost, 0.0)
            _append_transaction_cost(
                positions[ticker],
                symbol=ticker,
                trade_date=trade_date,
                side="BUY",
                quantity=quantity,
                price_gbp=price,
                gross_value_gbp=gross_cost,
                cash_amount_gbp=cash_cost,
                implied_cost_gbp=implied_cost,
            )
            positions[ticker]["quantity"] = float(positions[ticker]["quantity"]) + quantity
            positions[ticker]["cost_gbp"] = float(positions[ticker]["cost_gbp"]) + cash_cost
            positions[ticker]["implied_trading_cost_gbp"] = (
                float(positions[ticker]["implied_trading_cost_gbp"]) + implied_cost
            )
            lots = positions[ticker]["lots"]
            assert isinstance(lots, list)
            lots.append(
                {
                    "quantity": quantity,
                    "cost_gbp": cash_cost,
                    "opened_at": trade_date.isoformat() if trade_date else "",
                }
            )
        elif transaction_type.startswith("SELL"):
            current_quantity = float(positions[ticker]["quantity"])
            price = _parse_money(row.get("Price per share"))
            gross_proceeds = quantity * (price or 0)
            net_proceeds = _sell_cash_proceeds(row.get("Total Amount"), gross_proceeds)
            implied_cost = max(gross_proceeds - net_proceeds, 0.0)
            _append_transaction_cost(
                positions[ticker],
                symbol=ticker,
                trade_date=trade_date,
                side="SELL",
                quantity=quantity,
                price_gbp=price,
                gross_value_gbp=gross_proceeds,
                cash_amount_gbp=net_proceeds,
                implied_cost_gbp=implied_cost,
            )
            matched_quantity = min(quantity, max(current_quantity, 0))
            unmatched_quantity = max(quantity - matched_quantity, 0)
            matched_ratio = matched_quantity / quantity if quantity else 0.0
            unmatched_ratio = unmatched_quantity / quantity if quantity else 0.0
            realized_pnl, consumed_cost, closed_trades = _consume_lots_fifo(
                ticker=ticker,
                lots=positions[ticker]["lots"],
                quantity=matched_quantity,
                gross_proceeds=gross_proceeds * matched_ratio,
                net_proceeds=net_proceeds * matched_ratio,
                implied_cost=implied_cost * matched_ratio,
                closed_at=trade_date,
            )
            positions[ticker]["realized_pnl_gbp"] = float(positions[ticker]["realized_pnl_gbp"]) + realized_pnl
            positions[ticker]["unmatched_sell_proceeds_gbp"] = (
                float(positions[ticker]["unmatched_sell_proceeds_gbp"]) + net_proceeds * unmatched_ratio
            )
            if unmatched_quantity > 1e-8:
                unmatched_sells = positions[ticker]["unmatched_sells"]
                assert isinstance(unmatched_sells, list)
                unmatched_sells.append(
                    {
                        "symbol": ticker,
                        "date": trade_date.isoformat() if trade_date else "",
                        "transaction_type": transaction_type,
                        "sell_quantity": quantity,
                        "matched_quantity": matched_quantity,
                        "unmatched_quantity": unmatched_quantity,
                        "price_gbp": price or 0.0,
                        "net_proceeds_gbp": net_proceeds * unmatched_ratio,
                        "reason": "missing_visible_cost_basis",
                        "broker": "Revolut",
                    }
                )
            positions[ticker]["implied_trading_cost_gbp"] = (
                float(positions[ticker]["implied_trading_cost_gbp"]) + implied_cost
            )
            positions[ticker]["quantity"] = current_quantity - matched_quantity
            positions[ticker]["cost_gbp"] = max(float(positions[ticker]["cost_gbp"]) - consumed_cost, 0.0)
            closed = positions[ticker]["closed_trades"]
            assert isinstance(closed, list)
            closed.extend(closed_trades)
        elif transaction_type == "STOCK SPLIT":
            positions[ticker]["quantity"] = float(positions[ticker]["quantity"]) + quantity
    return positions


def _buy_cash_cost(total_amount: object, gross_cost: float) -> float:
    cash_amount = _absolute_money(total_amount)
    if cash_amount is None:
        return gross_cost
    return cash_amount if cash_amount >= gross_cost - 0.01 else gross_cost


def _sell_cash_proceeds(total_amount: object, gross_proceeds: float) -> float:
    cash_amount = _absolute_money(total_amount)
    return gross_proceeds if cash_amount is None else cash_amount


def _append_transaction_cost(
    position: dict[str, object],
    *,
    symbol: str,
    trade_date: date | None,
    side: str,
    quantity: float,
    price_gbp: float | None,
    gross_value_gbp: float,
    cash_amount_gbp: float,
    implied_cost_gbp: float,
) -> None:
    events = position.setdefault("transaction_costs", [])
    if not isinstance(events, list):
        return
    cost_rate_pct = implied_cost_gbp / gross_value_gbp * 100 if gross_value_gbp > 0 else 0.0
    events.append(
        {
            "symbol": symbol,
            "date": trade_date.isoformat() if trade_date else "",
            "side": side,
            "quantity": round(quantity, 8),
            "price_gbp": round(price_gbp or 0.0, 4),
            "gross_value_gbp": round(gross_value_gbp, 4),
            "cash_amount_gbp": round(cash_amount_gbp, 4),
            "implied_trading_cost_gbp": round(implied_cost_gbp, 4),
            "cost_rate_pct": round(cost_rate_pct, 10),
        }
    )


def _absolute_money(raw: object) -> float | None:
    value = _parse_money(raw)
    return abs(value) if value is not None else None


def _consume_lots_fifo(
    *,
    ticker: str,
    lots: object,
    quantity: float,
    gross_proceeds: float,
    net_proceeds: float,
    implied_cost: float,
    closed_at: date | None,
) -> tuple[float, float, list[dict[str, object]]]:
    if not isinstance(lots, list) or quantity <= 0:
        return 0.0, 0.0, []
    remaining = quantity
    realized_pnl = 0.0
    consumed_cost = 0.0
    closed_trades: list[dict[str, object]] = []
    while remaining > 1e-10 and lots:
        lot = lots[0]
        lot_quantity = float(lot.get("quantity") or 0)
        lot_cost = float(lot.get("cost_gbp") or 0)
        if lot_quantity <= 1e-10:
            lots.pop(0)
            continue
        matched = min(remaining, lot_quantity)
        lot_ratio = matched / lot_quantity
        sale_ratio = matched / quantity if quantity else 0.0
        cost_basis = lot_cost * lot_ratio
        allocated_gross = gross_proceeds * sale_ratio
        allocated_net = net_proceeds * sale_ratio
        allocated_implied_cost = implied_cost * sale_ratio
        pnl = allocated_net - cost_basis
        opened_at = _parse_statement_date(lot.get("opened_at"))
        holding_days = (
            max((closed_at - opened_at).days, 0)
            if opened_at is not None and closed_at is not None
            else None
        )
        closed_trades.append(
            {
                "symbol": ticker,
                "opened_at": opened_at.isoformat() if opened_at else "",
                "closed_at": closed_at.isoformat() if closed_at else "",
                "holding_days": holding_days,
                "quantity": round(matched, 8),
                "cost_basis_gbp": round(cost_basis, 4),
                "gross_proceeds_gbp": round(allocated_gross, 4),
                "net_proceeds_gbp": round(allocated_net, 4),
                "implied_trading_cost_gbp": round(allocated_implied_cost, 4),
                "realized_pnl_gbp": round(pnl, 4),
            }
        )
        realized_pnl += pnl
        consumed_cost += cost_basis
        remaining -= matched
        remaining_quantity = lot_quantity - matched
        remaining_cost = lot_cost - cost_basis
        if remaining_quantity <= 1e-10:
            lots.pop(0)
        else:
            lot["quantity"] = remaining_quantity
            lot["cost_gbp"] = remaining_cost
    return realized_pnl, consumed_cost, closed_trades


def _unique_transaction_rows(paths: list[Path]) -> tuple[list[dict[str, str]], int]:
    rows_by_identity: dict[tuple[str, ...], dict[str, str]] = {}
    duplicate_count = 0
    # Revolut can revise price or cash amount for an already exported trade.
    # Process older statements first so the newest export replaces that revision.
    ordered_paths = sorted(paths, key=lambda path: (path.stat().st_mtime, str(path)))
    for path in ordered_paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                identity = tuple(
                    _normalize_statement_cell(row.get(field))
                    for field in REVOLUT_TRANSACTION_ID_FIELDS
                )
                if not any(identity):
                    identity = tuple(
                        _normalize_statement_cell(row.get(field))
                        for field in REVOLUT_TRANSACTION_FIELDS
                    )
                if identity in rows_by_identity:
                    duplicate_count += 1
                rows_by_identity[identity] = row
    rows = sorted(rows_by_identity.values(), key=lambda row: _normalize_statement_cell(row.get("Date")))
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


def _build_portfolio_rows(positions: dict[str, dict[str, object]]) -> list[dict[str, str]]:
    monitor_symbols = {spec.symbol[:-2] if spec.symbol.endswith(".L") else spec.symbol: spec.symbol for spec in DEFAULT_ETF_SPECS}
    fx_quotes = {
        "USD": _latest_quote("GBPUSD=X"),
        "EUR": _latest_quote("GBPEUR=X"),
    }
    fx_as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    valued = []
    for ticker, position in positions.items():
        quantity = float(position["quantity"])
        if quantity <= 1e-8:
            continue
        cost_gbp = float(position.get("cost_gbp") or 0.0)
        average_cost = cost_gbp / quantity if quantity else 0.0
        monitor_symbol = monitor_symbols.get(ticker) or UK_SYMBOL_OVERRIDES.get(ticker) or _resolve_lse_etf_symbol(ticker)
        yahoo_symbol = monitor_symbol or ticker
        price, previous_price, native_currency, history = _latest_quote(yahoo_symbol)
        price_gbp, fx_pair, fx_rate = _quote_in_gbp(price, native_currency, fx_quotes)
        if (
            monitor_symbol
            and monitor_symbol != ticker
            and not _price_matches_cost_basis(price_gbp, average_cost)
        ):
            raw_price, raw_previous, raw_currency, raw_history = _latest_quote(ticker)
            raw_price_gbp, raw_fx_pair, raw_fx_rate = _quote_in_gbp(
                raw_price, raw_currency, fx_quotes
            )
            if _price_matches_cost_basis(raw_price_gbp, average_cost):
                print(
                    f"Rejected ticker collision {monitor_symbol} for {ticker}; "
                    "the original ticker quote is consistent with statement cost.",
                    file=sys.stderr,
                )
                monitor_symbol = None
                yahoo_symbol = ticker
                price, previous_price, native_currency, history = (
                    raw_price,
                    raw_previous,
                    raw_currency,
                    raw_history,
                )
                price_gbp, fx_pair, fx_rate = raw_price_gbp, raw_fx_pair, raw_fx_rate
        price_source = _QUOTE_SOURCES.get(yahoo_symbol, f"Yahoo:{yahoo_symbol}")
        if fx_pair:
            price_source += f" | FX:{fx_pair}"
        if price_gbp is None:
            price_gbp = average_cost or None
            price_source = "statement-average-cost fallback"
        market_value_native = quantity * price if price is not None else None
        market_value = quantity * price_gbp if price_gbp is not None else 0.0
        unrealized = market_value - cost_gbp
        unrealized_pct = unrealized / cost_gbp * 100 if cost_gbp else None
        realized_pnl = float(position.get("realized_pnl_gbp") or 0.0)
        dividend_income = float(position.get("dividend_income_gbp") or 0.0)
        implied_trading_cost = float(position.get("implied_trading_cost_gbp") or 0.0)
        total_return = unrealized + realized_pnl + dividend_income
        day_change_pct = (price / previous_price - 1) * 100 if price is not None and previous_price not in (None, 0) else None
        peak_price, peak_date, drawdown_from_peak_pct = _year_peak_snapshot(history)
        technical = _portfolio_technical_snapshot(history)
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
        distribution_fields = _cash_like_distribution_fields(
            monitor_symbol or ticker,
            _QUOTE_META.get(yahoo_symbol) or {},
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
                "implied_trading_cost": implied_trading_cost,
                "total_return": total_return,
                "day_change_pct": day_change_pct,
                "year_peak_price_native": peak_price,
                "year_peak_date": peak_date.isoformat() if peak_date else "",
                "drawdown_from_year_peak_pct": drawdown_from_peak_pct,
                "peak_watch": peak_watch,
                "ema21_native": technical["ema21"],
                "distance_ema21_pct": technical["distance_ema21_pct"],
                "sma50_native": technical["sma50"],
                "distance_sma50_pct": technical["distance_sma50_pct"],
                "sma200_native": sma200,
                "distance_sma200_pct": distance_sma200_pct,
                "rsi14": technical["rsi14"],
                "momentum_1m_pct": technical["momentum_1m_pct"],
                "support_20d_native": technical["support_20d"],
                "support_60d_native": technical["support_60d"],
                "daily_volatility_pct": daily_volatility_pct,
                "pullback_sigma_1m": pullback_sigma_1m,
                "yellow_drawdown_threshold_pct": yellow_drawdown_threshold_pct,
                "red_drawdown_threshold_pct": red_drawdown_threshold_pct,
                "drawdown_regime": drawdown_regime,
                "distribution_ex_date": distribution_fields["distribution_ex_date"],
                "distribution_amount_native": distribution_fields["distribution_amount_native"],
                "distribution_cycle_note": distribution_fields["distribution_cycle_note"],
                "fx_pair": fx_pair,
                "fx_rate": fx_rate,
                "fx_as_of": fx_as_of,
                "price_source": price_source,
                "monitor_status": "covered" if monitor_symbol else "outside-monitor-pool",
            }
        )
    total = sum(item["market_value"] for item in valued)
    account_realized_pnl = sum(float(item.get("realized_pnl_gbp") or 0.0) for item in positions.values())
    account_dividend_income = sum(float(item.get("dividend_income_gbp") or 0.0) for item in positions.values())
    account_implied_trading_cost = sum(float(item.get("implied_trading_cost_gbp") or 0.0) for item in positions.values())
    unmatched_sell_proceeds = sum(float(item.get("unmatched_sell_proceeds_gbp") or 0.0) for item in positions.values())
    unmatched_sells = [
        event
        for position in positions.values()
        for event in (position.get("unmatched_sells") if isinstance(position.get("unmatched_sells"), list) else [])
    ]
    unmatched_sells = sorted(
        unmatched_sells,
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("symbol") or ""),
        ),
        reverse=True,
    )
    unmatched_sells_json = json.dumps(unmatched_sells, ensure_ascii=False, separators=(",", ":"))
    account_unrealized_pnl = sum(item["unrealized_pnl"] for item in valued)
    account_total_return = account_unrealized_pnl + account_realized_pnl + account_dividend_income
    closed_trades = [
        trade
        for position in positions.values()
        for trade in (position.get("closed_trades") if isinstance(position.get("closed_trades"), list) else [])
    ]
    closed_trades = sorted(
        closed_trades,
        key=lambda item: (
            str(item.get("closed_at") or ""),
            str(item.get("symbol") or ""),
        ),
        reverse=True,
    )
    closed_trades_json = json.dumps(closed_trades, ensure_ascii=False, separators=(",", ":"))
    transaction_costs = [
        event
        for position in positions.values()
        for event in (position.get("transaction_costs") if isinstance(position.get("transaction_costs"), list) else [])
    ]
    transaction_costs = sorted(
        transaction_costs,
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("symbol") or ""),
            str(item.get("side") or ""),
        ),
        reverse=True,
    )
    transaction_costs_json = json.dumps(transaction_costs, ensure_ascii=False, separators=(",", ":"))
    account_sell_cost_rate_pct = _weighted_sell_cost_rate(transaction_costs)
    rows = []
    for item in sorted(valued, key=lambda value: value["market_value"], reverse=True):
        weight = item["market_value"] / total * 100 if total else 0.0
        symbol_transaction_costs = [
            event
            for event in transaction_costs
            if _base_symbol(event.get("symbol")) == _base_symbol(item["symbol"])
        ]
        exit_cost_rate_pct = _weighted_sell_cost_rate(symbol_transaction_costs)
        if exit_cost_rate_pct is None:
            exit_cost_rate_pct = account_sell_cost_rate_pct or 0.0
        breakeven_price_gbp = _breakeven_price(
            cost_gbp=float(item["average_cost"]) * float(item["quantity"]),
            quantity=float(item["quantity"]),
            exit_cost_rate_pct=exit_cost_rate_pct,
        )
        breakeven_price_native = (
            breakeven_price_gbp * item["fx_rate"]
            if breakeven_price_gbp is not None and item["fx_rate"] not in (None, 0)
            else breakeven_price_gbp
        )
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
                "implied_trading_cost_gbp": _fmt_number(item["implied_trading_cost"]),
                "total_return_gbp": _fmt_number(item["total_return"]),
                "account_unrealized_pnl_gbp": _fmt_number(account_unrealized_pnl),
                "account_realized_pnl_gbp": _fmt_number(account_realized_pnl),
                "account_dividend_income_gbp": _fmt_number(account_dividend_income),
                "account_implied_trading_cost_gbp": _fmt_number(account_implied_trading_cost),
                "account_total_return_gbp": _fmt_number(account_total_return),
                "unmatched_sell_proceeds_gbp": _fmt_number(unmatched_sell_proceeds),
                "unmatched_sells_json": unmatched_sells_json,
                "closed_trades_json": closed_trades_json,
                "transaction_costs_json": transaction_costs_json,
                "estimated_exit_cost_rate_pct": _fmt_number(exit_cost_rate_pct),
                "breakeven_price_gbp": _fmt_number(breakeven_price_gbp),
                "breakeven_price_native": _fmt_number(breakeven_price_native),
                "day_change_pct": _fmt_number(item["day_change_pct"]),
                "year_peak_price_native": _fmt_number(item["year_peak_price_native"]),
                "year_peak_date": str(item["year_peak_date"]),
                "drawdown_from_year_peak_pct": _fmt_number(item["drawdown_from_year_peak_pct"]),
                "peak_watch": str(item["peak_watch"]),
                "ema21_native": _fmt_number(item["ema21_native"]),
                "distance_ema21_pct": _fmt_number(item["distance_ema21_pct"]),
                "sma50_native": _fmt_number(item["sma50_native"]),
                "distance_sma50_pct": _fmt_number(item["distance_sma50_pct"]),
                "sma200_native": _fmt_number(item["sma200_native"]),
                "distance_sma200_pct": _fmt_number(item["distance_sma200_pct"]),
                "rsi14": _fmt_number(item["rsi14"]),
                "momentum_1m_pct": _fmt_number(item["momentum_1m_pct"]),
                "support_20d_native": _fmt_number(item["support_20d_native"]),
                "support_60d_native": _fmt_number(item["support_60d_native"]),
                "daily_volatility_pct": _fmt_number(item["daily_volatility_pct"]),
                "pullback_sigma_1m": _fmt_number(item["pullback_sigma_1m"]),
                "yellow_drawdown_threshold_pct": _fmt_number(item["yellow_drawdown_threshold_pct"]),
                "red_drawdown_threshold_pct": _fmt_number(item["red_drawdown_threshold_pct"]),
                "drawdown_regime": str(item["drawdown_regime"]),
                "distribution_ex_date": str(item["distribution_ex_date"]),
                "distribution_amount_native": _fmt_number(item["distribution_amount_native"]),
                "distribution_cycle_note": str(item["distribution_cycle_note"]),
                "fx_pair": str(item["fx_pair"]),
                "fx_rate": _fmt_number(item["fx_rate"]),
                "fx_as_of": str(item["fx_as_of"]),
                "price_source": str(item["price_source"]),
                "monitor_status": str(item["monitor_status"]),
            }
        )
    _save_portfolio_quote_cache()
    return rows


def _quote_in_gbp(
    price: float | None,
    native_currency: str,
    fx_quotes: dict[str, tuple[float | None, float | None, str, list[tuple[date, float]]]],
) -> tuple[float | None, str, float | None]:
    fx_pair = ""
    fx_rate = 1.0 if native_currency == "GBP" else None
    if native_currency in fx_quotes:
        fx_pair = f"GBP/{native_currency}"
        fx_rate = fx_quotes[native_currency][0]
    price_gbp = price / fx_rate if price is not None and fx_rate not in (None, 0) else None
    return price_gbp, fx_pair, fx_rate


def _cash_like_distribution_fields(
    symbol: str,
    meta: dict[str, object],
) -> dict[str, object]:
    if symbol.upper() not in CASH_LIKE_DISTRIBUTION_SYMBOLS:
        return {
            "distribution_ex_date": "",
            "distribution_amount_native": None,
            "distribution_cycle_note": "",
        }
    event = _latest_distribution_event(meta)
    if event:
        ex_date, amount = event
        amount_text = f"{amount:.4f}" if amount is not None else "待确认"
        note = (
            f"现金/超短债分派周期：Yahoo记录最近除息日 {ex_date}，每份分派约 {amount_text}；"
            "净值回落应与分派现金合并观察，不按权益式趋势破坏处理。"
            "Revolut到账日取决于发行商payment date和券商入账节奏。"
        )
        return {
            "distribution_ex_date": ex_date,
            "distribution_amount_native": amount,
            "distribution_cycle_note": note,
        }
    return {
        "distribution_ex_date": "",
        "distribution_amount_native": None,
        "distribution_cycle_note": (
            "现金/超短债分派周期：未从Yahoo确认最新除息日；若发行商近期除息，"
            "约一个季度收益幅度的价格回落应按净值除息处理，到账日以Revolut入账为准。"
        ),
    }


def _latest_distribution_event(meta: dict[str, object]) -> tuple[str, float | None] | None:
    raw_events = meta.get("_dividend_events")
    if not isinstance(raw_events, list):
        return None
    parsed: list[tuple[date, str, float | None]] = []
    today = date.today()
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        ex_date_raw = str(item.get("ex_date") or "")
        try:
            ex_day = date.fromisoformat(ex_date_raw)
        except ValueError:
            continue
        if ex_day > today:
            continue
        parsed.append((ex_day, ex_date_raw, _safe_float(item.get("amount"))))
    if not parsed:
        return None
    _, ex_date, amount = max(parsed, key=lambda item: item[0])
    return ex_date, amount


def _price_matches_cost_basis(price_gbp: float | None, average_cost_gbp: float) -> bool:
    if price_gbp is None or average_cost_gbp <= 0:
        return False
    return 0.25 <= price_gbp / average_cost_gbp <= 4.0


def _base_symbol(symbol: object) -> str:
    normalized = str(symbol or "").strip().upper()
    return normalized[:-2] if normalized.endswith(".L") else normalized


def _weighted_sell_cost_rate(events: list[dict[str, object]]) -> float | None:
    sell_events = [
        event
        for event in events
        if str(event.get("side") or "").upper() == "SELL" and _safe_float(event.get("gross_value_gbp"))
    ]
    gross_total = sum(_safe_float(event.get("gross_value_gbp")) or 0.0 for event in sell_events)
    if gross_total <= 0:
        return None
    cost_total = sum(_safe_float(event.get("implied_trading_cost_gbp")) or 0.0 for event in sell_events)
    return cost_total / gross_total * 100


def _breakeven_price(*, cost_gbp: float, quantity: float, exit_cost_rate_pct: float | None) -> float | None:
    if quantity <= 0:
        return None
    exit_rate = max((exit_cost_rate_pct or 0.0) / 100, 0.0)
    if exit_rate >= 0.95:
        return None
    return cost_gbp / quantity / (1 - exit_rate)


def _latest_quote(symbol: str) -> tuple[float | None, float | None, str, list[tuple[date, float]]]:
    try:
        # Portfolio imports are batch jobs. Use a short live probe here; the shared
        # Yahoo reader already checks both query endpoints before cache fallback.
        price_data = _fetch_yahoo_price_data(symbol, timeout=5, attempts=1)
        history = price_data.history
        if history:
            try:
                quote = _fetch_yahoo_quote_snapshot(symbol, timeout=5, attempts=1)
            except Exception:
                quote = {}
            raw_currency = quote.get("currency") or price_data.meta.get("currency")
            currency = _normalize_currency(raw_currency) or ""
            scale = 0.01 if raw_currency == "GBp" else 1.0
            latest_price = _safe_float(quote.get("regularMarketPrice"))
            previous = _safe_float(quote.get("regularMarketPreviousClose"))
            if latest_price is not None:
                latest_price *= scale
                previous = previous * scale if previous is not None else None
                quote_day = _portfolio_quote_day(quote) or history[-1][0]
                if history[-1][0] == quote_day:
                    history = history[:-1] + [(quote_day, latest_price)]
                elif history[-1][0] < quote_day:
                    history = history + [(quote_day, latest_price)]
            else:
                latest_price = history[-1][1]
                previous = history[-2][1] if len(history) > 1 else None
            _store_portfolio_quote_cache(symbol, latest_price, previous, currency, history)
            _QUOTE_META[symbol] = dict(price_data.meta or {})
            source_kind = (
                "Yahoo quote"
                if latest_price is not None and quote
                else ("Yahoo quote" if price_data.meta.get("_price_source") == "regularMarketPrice" else "Yahoo")
            )
            _QUOTE_SOURCES[symbol] = f"{source_kind}:{symbol}"
            return latest_price, previous, currency, history
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


def _fetch_yahoo_quote_snapshot(symbol: str, timeout: int = 5, attempts: int = 1) -> dict[str, object]:
    encoded = urllib.parse.quote(symbol, safe="")
    urls = [
        f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={encoded}",
        f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={encoded}",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            payload = _read_json(url, timeout=timeout, attempts=attempts)
            results = payload.get("quoteResponse", {}).get("result") or []
            if results:
                return dict(results[0])
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
    return {}


def _portfolio_quote_day(quote: dict[str, object]) -> date | None:
    timestamp = _safe_float(quote.get("regularMarketTime") or quote.get("postMarketTime"))
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).date()


def _resolve_lse_etf_symbol(ticker: str) -> str | None:
    if "." in ticker:
        return ticker if ticker.endswith(".L") else None
    if ticker.upper() in KNOWN_US_EQUITIES:
        return None
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


def _parse_statement_date(raw: object) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


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


def _portfolio_technical_snapshot(history: list[tuple[date, float]]) -> dict[str, float | None]:
    values = [price for _, price in history]
    latest = values[-1] if values else None
    ema21 = _ema(values, 21)
    sma50 = _sma(values, 50)
    return {
        "ema21": ema21,
        "distance_ema21_pct": _distance_to_sma(latest, ema21),
        "sma50": sma50,
        "distance_sma50_pct": _distance_to_sma(latest, sma50),
        "rsi14": _rsi(values, 14),
        "momentum_1m_pct": _momentum(values, 21),
        "support_20d": min(values[-20:]) if values else None,
        "support_60d": min(values[-60:]) if values else None,
    }


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


def _ema(values: list[float], window: int) -> float | None:
    return shared_ema(values, window)


def _momentum(values: list[float], days: int) -> float | None:
    if len(values) <= days or values[-days - 1] == 0:
        return None
    return (values[-1] / values[-days - 1] - 1) * 100


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
