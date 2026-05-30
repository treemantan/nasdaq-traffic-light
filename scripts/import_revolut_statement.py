from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_report.etf_monitor import DEFAULT_ETF_SPECS, _fetch_yahoo_history, _safe_float


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a Revolut trading statement CSV into portfolio.csv.")
    parser.add_argument("statement", help="Path to Revolut trading-account-statement CSV.")
    parser.add_argument("--output", default="portfolio.csv", help="Output portfolio CSV path.")
    args = parser.parse_args()

    statement = Path(args.statement)
    output = Path(args.output)
    if not statement.exists():
        raise SystemExit(f"Statement file not found: {statement}")

    positions, last_trade_prices = _reconstruct_positions(statement)
    if not positions:
        raise SystemExit("No open positions found in Revolut statement.")
    rows = _build_portfolio_rows(positions, last_trade_prices)
    output.write_text(_to_csv(rows), encoding="utf-8")

    print(f"Portfolio written to {output.resolve()}")
    print(f"Open positions: {len(rows)}")
    covered = [row["symbol"] for row in rows if row["monitor_status"] == "covered"]
    uncovered = [row["symbol"] for row in rows if row["monitor_status"] != "covered"]
    print("Covered ETF monitor symbols: " + (", ".join(covered) if covered else "none"))
    print("Outside ETF monitor pool: " + (", ".join(uncovered) if uncovered else "none"))
    return 0


def _reconstruct_positions(path: Path) -> tuple[dict[str, float], dict[str, float]]:
    quantities: dict[str, float] = defaultdict(float)
    last_trade_prices: dict[str, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = str(row.get("Ticker") or "").strip().upper()
            transaction_type = str(row.get("Type") or "").strip().upper()
            quantity = _safe_float(row.get("Quantity"))
            if not ticker or quantity is None:
                continue
            if transaction_type.startswith("BUY"):
                quantities[ticker] += quantity
            elif transaction_type.startswith("SELL"):
                quantities[ticker] -= quantity
            elif transaction_type == "STOCK SPLIT":
                quantities[ticker] += quantity
            price = _parse_money(row.get("Price per share"))
            if price is not None and transaction_type.startswith(("BUY", "SELL")):
                last_trade_prices[ticker] = price
    return ({ticker: quantity for ticker, quantity in quantities.items() if quantity > 1e-8}, last_trade_prices)


def _build_portfolio_rows(positions: dict[str, float], last_trade_prices: dict[str, float]) -> list[dict[str, str]]:
    monitor_symbols = {spec.symbol[:-2] if spec.symbol.endswith(".L") else spec.symbol: spec.symbol for spec in DEFAULT_ETF_SPECS}
    valued = []
    for ticker, quantity in positions.items():
        monitor_symbol = monitor_symbols.get(ticker)
        yahoo_symbol = monitor_symbol or ticker
        price, price_source = _current_or_fallback_price(yahoo_symbol, last_trade_prices.get(ticker), monitor_symbol is not None)
        market_value = quantity * price if price is not None else 0.0
        valued.append(
            {
                "symbol": monitor_symbol or ticker,
                "quantity": quantity,
                "market_value": market_value,
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
                "estimated_market_value_gbp": f"{item['market_value']:.2f}",
                "price_source": str(item["price_source"]),
                "monitor_status": str(item["monitor_status"]),
            }
        )
    return rows


def _current_or_fallback_price(symbol: str, fallback: float | None, use_yahoo: bool) -> tuple[float | None, str]:
    if use_yahoo:
        try:
            history = _fetch_yahoo_history(symbol)
            if history:
                return history[-1][1], f"Yahoo:{symbol}"
        except Exception:
            pass
    return fallback, "latest-statement-trade-price" if fallback is not None else "unavailable"


def _parse_money(raw: object) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    parts = text.replace(",", "").split()
    return _safe_float(parts[-1])


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
