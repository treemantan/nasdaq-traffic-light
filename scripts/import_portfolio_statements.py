from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_report.etf_monitor import _safe_float

_REVOLUT_SCRIPT = Path(__file__).resolve().parent / "import_revolut_statement.py"
_REVOLUT_SPEC = importlib.util.spec_from_file_location("import_revolut_statement", _REVOLUT_SCRIPT)
assert _REVOLUT_SPEC and _REVOLUT_SPEC.loader
_REVOLUT = importlib.util.module_from_spec(_REVOLUT_SPEC)
_REVOLUT_SPEC.loader.exec_module(_REVOLUT)

_build_portfolio_rows = _REVOLUT._build_portfolio_rows
_is_revolut_statement = _REVOLUT._is_revolut_statement
_parse_money = _REVOLUT._parse_money
_reconstruct_positions = _REVOLUT._reconstruct_positions
_to_csv = _REVOLUT._to_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert broker statement CSV/XML files into portfolio.csv.")
    parser.add_argument("statement", nargs="+", help="One or more Revolut CSV or IBKR CSV/XML statement paths.")
    parser.add_argument("--output", default="portfolio.csv", help="Output portfolio CSV path.")
    args = parser.parse_args()

    paths = [Path(value) for value in args.statement]
    missing = [path for path in paths if not path.exists()]
    if missing:
        raise SystemExit("Statement file not found: " + ", ".join(str(path) for path in missing))

    revolut_paths: list[Path] = []
    ibkr_paths: list[Path] = []
    for path in paths:
        if _is_ibkr_statement(path):
            ibkr_paths.append(path)
        elif _is_revolut_statement(path):
            revolut_paths.append(path)
    if not revolut_paths and not ibkr_paths:
        raise SystemExit("No supported portfolio statement CSV found after checking file headers.")

    positions = _merge_positions(
        _reconstruct_positions(revolut_paths) if revolut_paths else {},
        _reconstruct_ibkr_positions(ibkr_paths) if ibkr_paths else {},
    )
    if not positions:
        raise SystemExit("No open positions found in supported portfolio statements.")

    rows = _build_portfolio_rows(positions)
    output = Path(args.output)
    try:
        output.write_text(_to_csv(rows), encoding="utf-8")
    except PermissionError as exc:
        raise SystemExit(
            f"Cannot update {output}: the file is locked. Close portfolio.csv in Excel or another editor, then run again."
        ) from exc

    print(f"Portfolio written to {output.resolve()}")
    print(f"Open positions: {len(rows)}")
    if revolut_paths:
        print(f"Revolut statement files: {len(revolut_paths)}")
    if ibkr_paths:
        print(f"IBKR statement files: {len(ibkr_paths)}")
    covered = [row["symbol"] for row in rows if row["monitor_status"] == "covered"]
    uncovered = [row["symbol"] for row in rows if row["monitor_status"] != "covered"]
    print("Covered ETF monitor symbols: " + (", ".join(covered) if covered else "none"))
    print("Outside ETF monitor pool: " + (", ".join(uncovered) if uncovered else "none"))
    return 0


def _merge_positions(*groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = defaultdict(_empty_position)
    for group in groups:
        for symbol, position in group.items():
            target = merged[symbol]
            for key, value in position.items():
                if isinstance(value, list):
                    target.setdefault(key, [])
                    target[key].extend(value)
                elif isinstance(value, (int, float)):
                    target[key] = float(target.get(key) or 0.0) + value
                elif key not in target:
                    target[key] = value
    return dict(merged)


def _empty_position() -> dict[str, Any]:
    return {
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


def _is_ibkr_statement(path: Path) -> bool:
    if path.suffix.lower() == ".xml":
        return _is_ibkr_flex_xml(path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle):
                fields = set(row)
                if {"ClientAccountID", "LevelOfDetail", "Symbol"}.issubset(fields) and (
                    {"Buy/Sell", "Quantity"}.issubset(fields) or {"TradeQuantity", "TradePrice"}.issubset(fields)
                ):
                    return True
    except (OSError, UnicodeDecodeError, csv.Error):
        return False
    return False


def _is_ibkr_flex_xml(path: Path) -> bool:
    try:
        root = ET.parse(path).getroot()
        tag = _xml_tag(root)
        return tag in {"FlexQueryResponse", "FlexStatement"}
    except (OSError, UnicodeDecodeError, ET.ParseError):
        return False


def _reconstruct_ibkr_positions(paths: list[Path]) -> dict[str, dict[str, Any]]:
    positions: dict[str, dict[str, Any]] = defaultdict(_empty_position)
    rows, duplicate_count = _unique_ibkr_rows(paths)
    if duplicate_count:
        print(f"Removed {duplicate_count} duplicate IBKR execution row(s).")
    for row in rows:
        symbol = str(row.get("Symbol") or row.get("UnderlyingSymbol") or "").strip().upper()
        if not symbol or symbol == "GBP":
            continue
        activity = str(row.get("Buy/Sell") or row.get("TransactionType") or row.get("ActivityCode") or "").upper()
        quantity = _ibkr_quantity(row)
        if quantity is None:
            continue
        if activity == "BUY":
            cost = _ibkr_cash_amount(row, buy=True)
            positions[symbol]["quantity"] += quantity
            positions[symbol]["cost_gbp"] += cost
        elif activity == "SELL":
            current_quantity = positions[symbol]["quantity"]
            average_cost = positions[symbol]["cost_gbp"] / current_quantity if current_quantity else 0.0
            matched_quantity = min(quantity, max(current_quantity, 0))
            proceeds = _ibkr_cash_amount(row, buy=False)
            matched_proceeds = proceeds * (matched_quantity / quantity) if quantity else 0.0
            unmatched_quantity = max(quantity - matched_quantity, 0.0)
            currency = str(
                row.get("Currency")
                or row.get("CommissionCurrency")
                or row.get("IBCommissionCurrency")
                or row.get("CurrencyPrimary")
                or ""
            ).strip().upper()
            positions[symbol]["realized_pnl_gbp"] += matched_proceeds - average_cost * matched_quantity
            unmatched_proceeds = proceeds * (unmatched_quantity / quantity) if quantity else 0.0
            if currency in {"", "GBP"}:
                positions[symbol]["unmatched_sell_proceeds_gbp"] += unmatched_proceeds
            if unmatched_quantity > 1e-8:
                positions[symbol]["unmatched_sells"].append(
                    {
                        "symbol": symbol,
                        "date": str(row.get("TradeDate") or row.get("Date/Time") or ""),
                        "transaction_type": str(row.get("TransactionType") or "SELL"),
                        "sell_quantity": quantity,
                        "matched_quantity": matched_quantity,
                        "unmatched_quantity": unmatched_quantity,
                        "price_native": _safe_float(row.get("Price") or row.get("TradePrice")) or 0.0,
                        "net_proceeds_native": unmatched_proceeds,
                        "currency": currency,
                        "net_proceeds_gbp": unmatched_proceeds if currency in {"", "GBP"} else None,
                        "reason": "missing_visible_cost_basis",
                        "broker": "IBKR",
                        "account_id": str(row.get("ClientAccountID") or ""),
                    }
                )
            positions[symbol]["quantity"] -= matched_quantity
            positions[symbol]["cost_gbp"] -= average_cost * matched_quantity
    _add_ibkr_dividends(paths, positions)
    return dict(positions)


def _unique_ibkr_rows(paths: list[Path]) -> tuple[list[dict[str, str]], int]:
    rows_by_fingerprint: dict[tuple[str, ...], dict[str, str]] = {}
    duplicate_count = 0
    for path in paths:
        for row in _iter_ibkr_rows(path):
            if str(row.get("LevelOfDetail") or "").upper() != "EXECUTION":
                continue
            if not (row.get("Buy/Sell") or row.get("TransactionType")):
                continue
            fingerprint = _ibkr_fingerprint(row)
            if fingerprint in rows_by_fingerprint:
                duplicate_count += 1
                continue
            rows_by_fingerprint[fingerprint] = row
    return sorted(rows_by_fingerprint.values(), key=_ibkr_sort_key), duplicate_count


def _iter_ibkr_rows(path: Path):
    if path.suffix.lower() == ".xml":
        yield from _iter_ibkr_xml_rows(path)
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header: list[str] | None = None
        for raw in csv.reader(handle):
            if not raw:
                continue
            if "ClientAccountID" in raw and "LevelOfDetail" in raw:
                header = raw
                continue
            if header is None or len(raw) != len(header):
                continue
            yield dict(zip(header, raw))


def _iter_ibkr_xml_rows(path: Path):
    try:
        context = ET.iterparse(path, events=("end",))
        for _event, element in context:
            tag = _xml_tag(element)
            if tag in {"Trade", "TradeConfirm"}:
                yield _normalize_ibkr_xml_row(element.attrib, row_kind="TRADE")
                element.clear()
            elif tag == "CashTransaction":
                yield _normalize_ibkr_xml_row(element.attrib, row_kind="CASH")
                element.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"Invalid IBKR Flex XML file {path}: {exc}") from exc


def _normalize_ibkr_xml_row(attrs: dict[str, str], *, row_kind: str) -> dict[str, str]:
    normalized = {key: str(value) for key, value in attrs.items()}
    lower = {key.lower(): value for key, value in normalized.items()}

    def pick(*names: str) -> str:
        for name in names:
            value = lower.get(name.lower())
            if value not in (None, ""):
                return value
        return ""

    if row_kind == "TRADE":
        level = pick("levelOfDetail") or "EXECUTION"
        return {
            **normalized,
            "ClientAccountID": pick("accountId", "acctId", "account"),
            "LevelOfDetail": level.upper(),
            "Symbol": pick("symbol", "underlyingSymbol"),
            "UnderlyingSymbol": pick("underlyingSymbol"),
            "TradeID": pick("tradeID", "tradeId"),
            "OrderID": pick("orderID", "orderId"),
            "ExecID": pick("ibExecID", "execID", "executionID"),
            "TradeDate": pick("tradeDate", "dateTime", "date"),
            "Date/Time": pick("dateTime", "tradeDate", "date"),
            "Buy/Sell": pick("buySell", "side"),
            "Quantity": pick("quantity", "tradeQuantity"),
            "TradeQuantity": pick("tradeQuantity", "quantity"),
            "Price": pick("price", "tradePrice"),
            "TradePrice": pick("tradePrice", "price"),
            "Amount": pick("tradeMoney", "amount", "proceeds"),
            "TradeMoney": pick("tradeMoney", "amount"),
            "Proceeds": pick("proceeds"),
            "NetCash": pick("netCash", "netCashWithBillable"),
            "Commission": pick("commission", "ibCommission"),
            "IBCommission": pick("ibCommission", "commission"),
            "Tax": pick("tax", "taxes"),
            "Currency": pick("currency", "currencyPrimary"),
        }
    return {
        **normalized,
        "ClientAccountID": pick("accountId", "acctId", "account"),
        "LevelOfDetail": (pick("levelOfDetail") or "DETAIL").upper(),
        "Symbol": pick("symbol", "underlyingSymbol"),
        "UnderlyingSymbol": pick("underlyingSymbol"),
        "Type": pick("type", "transactionType", "description"),
        "DividendType": pick("type", "transactionType", "description"),
        "TransactionID": pick("transactionID", "transactionId"),
        "ReportDate": pick("reportDate", "dateTime", "date"),
        "Date/Time": pick("dateTime", "reportDate", "date"),
        "Amount": pick("amount", "netCash"),
        "Currency": pick("currency", "currencyPrimary"),
    }


def _xml_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _ibkr_fingerprint(row: dict[str, str]) -> tuple[str, ...]:
    ids = (
        row.get("ExecID"),
        row.get("IBExecID"),
        row.get("TransactionID"),
        row.get("TradeID"),
        row.get("OrderID"),
        row.get("IBOrderID"),
    )
    stable = tuple(str(value or "").strip() for value in ids if str(value or "").strip())
    if stable:
        return stable
    keys = ("Symbol", "TradeDate", "Date/Time", "Buy/Sell", "Quantity", "TradeQuantity", "Price", "TradePrice", "NetCash")
    return tuple(str(row.get(key) or "").strip() for key in keys)


def _ibkr_sort_key(row: dict[str, str]) -> str:
    return str(row.get("TradeDate") or row.get("ReportDate") or row.get("Date/Time") or "")


def _ibkr_quantity(row: dict[str, str]) -> float | None:
    quantity = _safe_float(row.get("Quantity")) or _safe_float(row.get("TradeQuantity"))
    return abs(quantity) if quantity is not None else None


def _ibkr_cash_amount(row: dict[str, str], *, buy: bool) -> float:
    net_cash = _safe_float(row.get("NetCash") or row.get("NetCashWithBillable"))
    if net_cash is not None:
        return abs(net_cash)
    gross = _safe_float(row.get("Amount") or row.get("TradeMoney") or row.get("TradeGross") or row.get("Proceeds")) or 0.0
    commission = abs(_safe_float(row.get("Commission") or row.get("IBCommission") or row.get("TradeCommission")) or 0.0)
    tax = abs(_safe_float(row.get("Tax") or row.get("Taxes") or row.get("TradeTax")) or 0.0)
    return abs(gross) + commission + tax if buy else max(abs(gross) - commission - tax, 0.0)


def _add_ibkr_dividends(paths: list[Path], positions: dict[str, dict[str, Any]]) -> None:
    seen: set[tuple[str, ...]] = set()
    for path in paths:
        for row in _iter_ibkr_rows(path):
            row_type = str(row.get("Type") or row.get("DividendType") or "").upper()
            if str(row.get("LevelOfDetail") or "").upper() != "DETAIL" or "DIVIDEND" not in row_type:
                continue
            symbol = str(row.get("Symbol") or row.get("UnderlyingSymbol") or "").strip().upper()
            if not symbol:
                continue
            fingerprint = (
                symbol,
                str(row.get("TransactionID") or ""),
                str(row.get("Date/Time") or row.get("ReportDate") or ""),
                str(row.get("Amount") or ""),
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            amount = _parse_money(row.get("Amount")) or _safe_float(row.get("Amount")) or 0.0
            positions[symbol]["dividend_income_gbp"] += amount


if __name__ == "__main__":
    raise SystemExit(main())
