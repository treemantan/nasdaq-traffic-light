from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_report.etf_monitor import DEFAULT_ETF_SPECS, _fetch_yahoo_history, _safe_float


UK_SYMBOL_OVERRIDES = {"IGTM": "IGTM.L", "ISF": "ISF.L"}


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

    positions = _reconstruct_positions(statements)
    if not positions:
        raise SystemExit("No open positions found in Revolut statement.")
    rows = _build_portfolio_rows(positions)
    output.write_text(_to_csv(rows), encoding="utf-8")

    print(f"Portfolio written to {output.resolve()}")
    print(f"Open positions: {len(rows)}")
    covered = [row["symbol"] for row in rows if row["monitor_status"] == "covered"]
    uncovered = [row["symbol"] for row in rows if row["monitor_status"] != "covered"]
    print("Covered ETF monitor symbols: " + (", ".join(covered) if covered else "none"))
    print("Outside ETF monitor pool: " + (", ".join(uncovered) if uncovered else "none"))
    return 0


def _reconstruct_positions(paths: list[Path]) -> dict[str, dict[str, float]]:
    positions: dict[str, dict[str, float]] = defaultdict(lambda: {"quantity": 0.0, "cost_gbp": 0.0})
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                ticker = str(row.get("Ticker") or "").strip().upper()
                transaction_type = str(row.get("Type") or "").strip().upper()
                quantity = _safe_float(row.get("Quantity"))
                if not ticker or quantity is None:
                    continue
                if transaction_type.startswith("BUY"):
                    price = _parse_money(row.get("Price per share"))
                    positions[ticker]["quantity"] += quantity
                    positions[ticker]["cost_gbp"] += quantity * (price or 0)
                elif transaction_type.startswith("SELL"):
                    current_quantity = positions[ticker]["quantity"]
                    average_cost = positions[ticker]["cost_gbp"] / current_quantity if current_quantity else 0
                    positions[ticker]["quantity"] -= quantity
                    positions[ticker]["cost_gbp"] -= average_cost * quantity
                elif transaction_type == "STOCK SPLIT":
                    positions[ticker]["quantity"] += quantity
    return {ticker: item for ticker, item in positions.items() if item["quantity"] > 1e-8}


def _build_portfolio_rows(positions: dict[str, dict[str, float]]) -> list[dict[str, str]]:
    monitor_symbols = {spec.symbol[:-2] if spec.symbol.endswith(".L") else spec.symbol: spec.symbol for spec in DEFAULT_ETF_SPECS}
    gbpusd = _latest_price("GBPUSD=X")[0]
    valued = []
    for ticker, position in positions.items():
        quantity = position["quantity"]
        monitor_symbol = monitor_symbols.get(ticker)
        yahoo_symbol = monitor_symbol or UK_SYMBOL_OVERRIDES.get(ticker) or ticker
        price, previous_price = _latest_price(yahoo_symbol)
        price_source = f"Yahoo:{yahoo_symbol}"
        if yahoo_symbol == ticker and gbpusd:
            price = price / gbpusd if price is not None else None
            previous_price = previous_price / gbpusd if previous_price is not None else None
            price_source += "；FX:GBPUSD=X"
        average_cost = position["cost_gbp"] / quantity if quantity else 0.0
        if price is None:
            price = average_cost or None
            price_source = "statement-average-cost fallback"
        market_value = quantity * price if price is not None else 0.0
        unrealized = market_value - position["cost_gbp"]
        unrealized_pct = unrealized / position["cost_gbp"] * 100 if position["cost_gbp"] else None
        day_change_pct = (price / previous_price - 1) * 100 if price is not None and previous_price not in (None, 0) else None
        valued.append(
            {
                "symbol": monitor_symbol or ticker,
                "quantity": quantity,
                "average_cost": average_cost,
                "current_price": price,
                "market_value": market_value,
                "unrealized_pnl": unrealized,
                "unrealized_pnl_pct": unrealized_pct,
                "day_change_pct": day_change_pct,
                "price_source": price_source,
                "monitor_status": "covered" if monitor_symbol else "outside-monitor-pool",
            }
        )
    total = sum(item["market_value"] for item in valued)
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
                "estimated_market_value_gbp": f"{item['market_value']:.2f}",
                "unrealized_pnl_gbp": _fmt_number(item["unrealized_pnl"]),
                "unrealized_pnl_pct": _fmt_number(item["unrealized_pnl_pct"]),
                "day_change_pct": _fmt_number(item["day_change_pct"]),
                "price_source": str(item["price_source"]),
                "monitor_status": str(item["monitor_status"]),
            }
        )
    return rows


def _latest_price(symbol: str) -> tuple[float | None, float | None]:
    try:
        history = _fetch_yahoo_history(symbol)
        if history:
            return history[-1][1], history[-2][1] if len(history) > 1 else None
    except Exception:
        pass
    return None, None


def _parse_money(raw: object) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    parts = text.replace(",", "").split()
    return _safe_float(parts[-1])


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
