from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_report.etf_monitor import _safe_float
from market_report.time_utils import _timezone_for

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
    parser.add_argument(
        "--ibkr-diagnostics",
        default="",
        help="Optional diagnostics JSON produced by scripts/download_ibkr_flex.py.",
    )
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
    option_legs = _extract_ibkr_option_legs(ibkr_paths) if ibkr_paths else []
    if not positions:
        raise SystemExit("No open positions found in supported portfolio statements.")

    rows = _build_portfolio_rows(positions)
    if rows and option_legs:
        rows[0]["option_legs_json"] = json.dumps(option_legs, ensure_ascii=False, separators=(",", ":"))
    ibkr_health = _ibkr_data_health(
        ibkr_paths,
        Path(args.ibkr_diagnostics) if args.ibkr_diagnostics else None,
    )
    for row in rows:
        row.update(ibkr_health)
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
    fx_rates_to_base = _ibkr_fx_rates_to_base_by_date(rows)
    for row in rows:
        asset_category = str(row.get("AssetCategory") or "").strip().upper()
        if asset_category == "CASH":
            continue
        if asset_category == "OPT":
            continue
        symbol = str(row.get("Symbol") or row.get("UnderlyingSymbol") or "").strip().upper()
        if not symbol or symbol == "GBP":
            continue
        activity = str(row.get("Buy/Sell") or row.get("TransactionType") or row.get("ActivityCode") or "").upper()
        quantity = _ibkr_quantity(row)
        if quantity is None:
            continue
        if activity == "BUY":
            cost = _ibkr_cash_amount(row, buy=True, fx_rates_to_base=fx_rates_to_base)
            positions[symbol]["quantity"] += quantity
            positions[symbol]["cost_gbp"] += cost
        elif activity == "SELL":
            current_quantity = positions[symbol]["quantity"]
            average_cost = positions[symbol]["cost_gbp"] / current_quantity if current_quantity else 0.0
            matched_quantity = min(quantity, max(current_quantity, 0))
            proceeds = _ibkr_cash_amount(row, buy=False, fx_rates_to_base=fx_rates_to_base)
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


def _extract_ibkr_option_legs(paths: list[Path]) -> list[dict[str, Any]]:
    rows, _duplicate_count = _unique_ibkr_rows(paths)
    fx_rates_to_base = _ibkr_fx_rates_to_base_by_date(rows)
    legs: list[dict[str, Any]] = []
    for row in rows:
        asset_category = str(row.get("AssetCategory") or "").strip().upper()
        if asset_category != "OPT":
            continue
        quantity = _ibkr_quantity(row)
        if quantity is None or quantity <= 0:
            continue
        raw_symbol = str(row.get("Symbol") or "").strip().upper()
        underlying = _option_underlying(row, raw_symbol)
        right = _option_right(row, raw_symbol)
        expiry = _option_expiry(row, raw_symbol)
        strike = _option_strike(row, raw_symbol)
        multiplier = _safe_float(row.get("Multiplier") or row.get("multiplier")) or 100.0
        side = str(row.get("Buy/Sell") or "").strip().upper()
        signed_contracts = quantity if side == "BUY" else -quantity if side == "SELL" else quantity
        net_cash_native = _safe_float(row.get("NetCash") or row.get("NetCashWithBillable"))
        net_cash_gbp = (
            _ibkr_amount_in_base_currency(row, net_cash_native, fx_rates_to_base)
            if net_cash_native is not None
            else None
        )
        commission_native = _safe_float(row.get("Commission") or row.get("IBCommission") or row.get("TradeCommission"))
        commission_gbp = (
            _ibkr_amount_in_base_currency(row, commission_native, fx_rates_to_base)
            if commission_native is not None
            else None
        )
        net_cash_after_fee_native = (
            net_cash_native + commission_native
            if net_cash_native is not None and commission_native is not None
            else net_cash_native
        )
        net_cash_after_fee_gbp = (
            net_cash_gbp + commission_gbp
            if net_cash_gbp is not None and commission_gbp is not None
            else net_cash_gbp
        )
        trade_price = _safe_float(row.get("TradePrice") or row.get("Price"))
        legs.append(
            {
                "symbol": raw_symbol,
                "underlying": underlying,
                "expiry": expiry,
                "right": right,
                "strike": strike,
                "side": side,
                "contracts": quantity,
                "signed_contracts": signed_contracts,
                "multiplier": multiplier,
                "trade_price": trade_price,
                "currency": str(row.get("Currency") or "").strip().upper(),
                "net_cash_native": net_cash_native,
                "net_cash_gbp": net_cash_gbp,
                "commission_native": commission_native,
                "commission_gbp": commission_gbp,
                "net_cash_after_fee_native": net_cash_after_fee_native,
                "net_cash_after_fee_gbp": net_cash_after_fee_gbp,
                "trade_date": _format_ibkr_date(str(row.get("TradeDate") or row.get("Date/Time") or "")),
                "source": "IBKR statement",
            }
        )
    return sorted(
        legs,
        key=lambda item: (
            str(item.get("underlying") or ""),
            str(item.get("expiry") or ""),
            str(item.get("right") or ""),
            float(item.get("strike") or 0),
        ),
    )


def _option_underlying(row: dict[str, str], raw_symbol: str) -> str:
    underlying = str(row.get("UnderlyingSymbol") or "").strip().upper()
    if underlying:
        return underlying
    match = re.match(r"^([A-Z.\-]+)\s+\d{6}[CP]\d{8}$", raw_symbol)
    return match.group(1) if match else raw_symbol.split()[0] if raw_symbol else ""


def _option_right(row: dict[str, str], raw_symbol: str) -> str:
    value = str(row.get("PutCall") or row.get("Right") or row.get("putCall") or "").strip().upper()
    if value.startswith("P"):
        return "P"
    if value.startswith("C"):
        return "C"
    match = re.search(r"\d{6}([CP])\d{8}$", raw_symbol)
    return match.group(1) if match else ""


def _option_expiry(row: dict[str, str], raw_symbol: str) -> str:
    value = str(row.get("Expiry") or row.get("ExpiryDate") or row.get("Maturity") or "").strip()
    if value:
        return _format_ibkr_date(value)
    match = re.search(r"(\d{6})[CP]\d{8}$", raw_symbol)
    if not match:
        return ""
    compact = match.group(1)
    return _format_ibkr_date("20" + compact)


def _option_strike(row: dict[str, str], raw_symbol: str) -> float | None:
    value = _safe_float(row.get("Strike") or row.get("strike"))
    if value is not None:
        return value
    match = re.search(r"\d{6}[CP](\d{8})$", raw_symbol)
    if not match:
        return None
    return int(match.group(1)) / 1000.0


def _format_ibkr_date(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return value


def _unique_ibkr_rows(paths: list[Path]) -> tuple[list[dict[str, str]], int]:
    unique_rows: list[dict[str, str]] = []
    seen_identifiers: set[tuple[str, ...]] = set()
    duplicate_count = 0
    for path in paths:
        for row in _iter_ibkr_rows(path):
            if str(row.get("LevelOfDetail") or "").upper() != "EXECUTION":
                continue
            if not (row.get("Buy/Sell") or row.get("TransactionType")):
                continue
            identifiers = _ibkr_identity_keys(row)
            if any(identifier in seen_identifiers for identifier in identifiers):
                duplicate_count += 1
                seen_identifiers.update(identifiers)
                continue
            unique_rows.append(row)
            seen_identifiers.update(identifiers)
    return sorted(unique_rows, key=_ibkr_sort_key), duplicate_count


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
            yield _normalize_ibkr_csv_row(dict(zip(header, raw)))


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


def _normalize_ibkr_csv_row(row: dict[str, str]) -> dict[str, str]:
    normalized = {str(key): str(value) for key, value in row.items()}
    lower = {key.lower(): value for key, value in normalized.items()}

    def pick(*names: str) -> str:
        for name in names:
            value = lower.get(name.lower())
            if value not in (None, ""):
                return value
        return ""

    return {
        **normalized,
        "ClientAccountID": pick("ClientAccountID", "AccountID", "AccountId"),
        "LevelOfDetail": (pick("LevelOfDetail") or "EXECUTION").upper(),
        "AssetCategory": pick("AssetCategory", "AssetClass"),
        "Symbol": pick("Symbol", "UnderlyingSymbol"),
        "UnderlyingSymbol": pick("UnderlyingSymbol"),
        "TradeID": pick("TradeID", "TradeId"),
        "OrderID": pick("OrderID", "OrderId"),
        "ExecID": pick("IBExecID", "ExecID", "ExecutionID"),
        "TradeDate": pick("TradeDate", "Date/Time", "DateTime", "Date"),
        "Date/Time": pick("Date/Time", "DateTime", "TradeDate", "Date"),
        "Buy/Sell": pick("Buy/Sell", "BuySell", "Side"),
        "Quantity": pick("Quantity", "TradeQuantity"),
        "TradeQuantity": pick("TradeQuantity", "Quantity"),
        "Price": pick("Price", "TradePrice"),
        "TradePrice": pick("TradePrice", "Price"),
        "Amount": pick("TradeMoney", "Amount", "Proceeds"),
        "TradeMoney": pick("TradeMoney", "Amount"),
        "Proceeds": pick("Proceeds"),
        "NetCash": pick("NetCash", "NetCashWithBillable"),
        "Commission": pick("Commission", "IBCommission", "TradeCommission"),
        "IBCommission": pick("IBCommission", "Commission", "TradeCommission"),
        "Tax": pick("Tax", "Taxes"),
        "Currency": pick("Currency", "CommissionCurrency", "IBCommissionCurrency", "CurrencyPrimary"),
        "FxRateToBase": pick("FxRateToBase", "FXRateToBase"),
        "Multiplier": pick("Multiplier"),
        "PutCall": pick("PutCall", "Right"),
        "Strike": pick("Strike"),
        "Expiry": pick("Expiry", "ExpiryDate", "Maturity"),
    }


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
            "AssetCategory": pick("assetCategory"),
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
            "FxRateToBase": pick("fxRateToBase"),
        }
    return {
        **normalized,
        "ClientAccountID": pick("accountId", "acctId", "account"),
        "LevelOfDetail": (pick("levelOfDetail") or "DETAIL").upper(),
        "AssetCategory": pick("assetCategory"),
        "Symbol": pick("symbol", "underlyingSymbol"),
        "UnderlyingSymbol": pick("underlyingSymbol"),
        "Type": pick("type", "transactionType", "description"),
        "DividendType": pick("type", "transactionType", "description"),
        "TransactionID": pick("transactionID", "transactionId"),
        "ReportDate": pick("reportDate", "dateTime", "date"),
        "Date/Time": pick("dateTime", "reportDate", "date"),
        "Amount": pick("amount", "netCash"),
        "Currency": pick("currency", "currencyPrimary"),
        "FxRateToBase": pick("fxRateToBase"),
    }


def _xml_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _ibkr_fingerprint(row: dict[str, str]) -> tuple[str, ...]:
    identifiers = _ibkr_identity_keys(row)
    return identifiers[0]


def _ibkr_identity_keys(row: dict[str, str]) -> tuple[tuple[str, ...], ...]:
    account = str(row.get("ClientAccountID") or "").strip()
    identifiers: list[tuple[str, ...]] = []
    for kind, fields in (
        ("execution", ("ExecID", "IBExecID")),
        ("transaction", ("TransactionID",)),
        ("trade", ("TradeID",)),
    ):
        for field in fields:
            value = str(row.get(field) or "").strip()
            if value:
                identifier = (kind, account, value)
                if identifier not in identifiers:
                    identifiers.append(identifier)
    if identifiers:
        return tuple(identifiers)
    keys = ("Symbol", "TradeDate", "Date/Time", "Buy/Sell", "Quantity", "TradeQuantity", "Price", "TradePrice", "NetCash")
    return (("economic", account, *(str(row.get(key) or "").strip() for key in keys)),)


def _ibkr_sort_key(row: dict[str, str]) -> str:
    return str(row.get("TradeDate") or row.get("ReportDate") or row.get("Date/Time") or "")


def _ibkr_quantity(row: dict[str, str]) -> float | None:
    quantity = _safe_float(row.get("Quantity")) or _safe_float(row.get("TradeQuantity"))
    return abs(quantity) if quantity is not None else None


def _ibkr_cash_amount(
    row: dict[str, str],
    *,
    buy: bool,
    fx_rates_to_base: dict[tuple[str, str], float] | None = None,
) -> float:
    net_cash = _safe_float(row.get("NetCash") or row.get("NetCashWithBillable"))
    if net_cash is not None:
        return abs(_ibkr_amount_in_base_currency(row, net_cash, fx_rates_to_base))
    gross = _safe_float(row.get("Amount") or row.get("TradeMoney") or row.get("TradeGross") or row.get("Proceeds")) or 0.0
    commission = abs(_safe_float(row.get("Commission") or row.get("IBCommission") or row.get("TradeCommission")) or 0.0)
    tax = abs(_safe_float(row.get("Tax") or row.get("Taxes") or row.get("TradeTax")) or 0.0)
    gross_base = abs(_ibkr_amount_in_base_currency(row, gross, fx_rates_to_base))
    commission_base = abs(_ibkr_amount_in_base_currency(row, commission, fx_rates_to_base))
    tax_base = abs(_ibkr_amount_in_base_currency(row, tax, fx_rates_to_base))
    return gross_base + commission_base + tax_base if buy else max(gross_base - commission_base - tax_base, 0.0)


def _ibkr_amount_in_base_currency(
    row: dict[str, str],
    amount: float,
    fx_rates_to_base: dict[tuple[str, str], float] | None = None,
) -> float:
    currency = str(row.get("Currency") or row.get("CurrencyPrimary") or "").strip().upper()
    date_key = str(row.get("TradeDate") or row.get("Date/Time") or row.get("ReportDate") or "")[:8]
    actual_fx_rate = (fx_rates_to_base or {}).get((date_key, currency))
    if actual_fx_rate is not None and actual_fx_rate > 0:
        return amount * actual_fx_rate
    fx_rate = _safe_float(row.get("FxRateToBase") or row.get("FXRateToBase") or row.get("fxRateToBase"))
    if fx_rate is None or fx_rate <= 0:
        return amount
    return amount * fx_rate


def _ibkr_fx_rates_to_base_by_date(rows: list[dict[str, str]]) -> dict[tuple[str, str], float]:
    totals: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"base": 0.0, "foreign": 0.0})
    for row in rows:
        if str(row.get("AssetCategory") or "").strip().upper() != "CASH":
            continue
        symbol = str(row.get("Symbol") or "").strip().upper()
        if symbol != "GBP.USD":
            continue
        currency = str(row.get("Currency") or "").strip().upper()
        date_key = str(row.get("TradeDate") or row.get("Date/Time") or "")[:8]
        if not currency or not date_key:
            continue
        base_amount = abs(_safe_float(row.get("Quantity")) or 0.0)
        foreign_amount = abs(
            _safe_float(row.get("Proceeds"))
            or _safe_float(row.get("TradeMoney"))
            or _safe_float(row.get("Amount"))
            or 0.0
        )
        if base_amount <= 0 or foreign_amount <= 0:
            continue
        totals[(date_key, currency)]["base"] += base_amount
        totals[(date_key, currency)]["foreign"] += foreign_amount
    return {
        key: value["base"] / value["foreign"]
        for key, value in totals.items()
        if value["base"] > 0 and value["foreign"] > 0
    }


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
            amount = _ibkr_amount_in_base_currency(row, amount)
            positions[symbol]["dividend_income_gbp"] += amount


def _ibkr_data_health(paths: list[Path], diagnostics_path: Path | None) -> dict[str, str]:
    diagnostics = _load_ibkr_diagnostics(diagnostics_path)
    if not paths and not diagnostics:
        return _blank_ibkr_health()
    candidates: dict[str, list[Path]] = {"activity": [], "trade": []}
    for path in paths:
        role = _ibkr_statement_role(path)
        if role:
            candidates[role].append(path)

    selected = {
        role: _latest_ibkr_source(role_paths)
        for role, role_paths in candidates.items()
        if role_paths
    }
    activity = selected.get("activity")
    trade = selected.get("trade")
    activity_source = _ibkr_source_label(activity)
    trade_source = _ibkr_source_label(trade)
    activity_as_of = _ibkr_observation_date(activity) if activity else ""
    trade_as_of = _ibkr_observation_date(trade) if trade else ""
    activity_updated = _ibkr_file_updated_at(activity) if activity else ""
    trade_updated = _ibkr_file_updated_at(trade) if trade else ""
    failed_labels = {
        str(event.get("label") or "")
        for event in diagnostics.get("events", [])
        if event.get("event") == "query_final_failure"
    }

    if not activity and not trade:
        status = "missing"
        warning = (
            "IBKR 数据暂不可用；本次报告未获得 Activity 或 Trade Confirmation。"
            "当前组合可能遗漏近期交易、现金流或持仓变化，请手动更新 OneDrive statement。"
        )
    elif not activity or not trade:
        status = "partial"
        missing = "Activity" if not activity else "Trade Confirmation"
        available = _ibkr_source_summary(
            "Trade Confirmation" if trade else "Activity",
            trade if trade else activity,
        )
        warning = (
            f"IBKR 数据覆盖不完整：{missing} 暂不可用；{available}。"
            "当前组合可能遗漏近期交易、历史成本或现金流，请手动更新对应 statement。"
        )
    elif activity_source == "IBKR Flex live" and trade_source == "IBKR Flex live" and not failed_labels:
        status = "live"
        warning = ""
    elif "OneDrive manual" in {activity_source, trade_source}:
        status = "manual-fallback"
        warning = (
            "IBKR 自动下载未完整成功，当前使用 OneDrive 手动 statement 兜底；"
            f"{_ibkr_source_summary('Activity', activity)}；"
            f"{_ibkr_source_summary('Trade Confirmation', trade)}。"
            "如期间发生新交易，请手动更新文件，避免整体持仓判断遗漏。"
        )
    else:
        status = "partial"
        warning = (
            "IBKR Flex 本次存在部分失败；"
            f"{_ibkr_source_summary('Activity', activity)}；"
            f"{_ibkr_source_summary('Trade Confirmation', trade)}。"
            "请结合截止日期判断组合信息是否完整。"
        )

    return {
        "ibkr_data_status": status,
        "ibkr_activity_source": activity_source,
        "ibkr_activity_as_of": activity_as_of,
        "ibkr_activity_file_updated": activity_updated,
        "ibkr_trade_source": trade_source,
        "ibkr_trade_as_of": trade_as_of,
        "ibkr_trade_file_updated": trade_updated,
        "ibkr_data_warning": warning,
    }


def _blank_ibkr_health() -> dict[str, str]:
    return {
        "ibkr_data_status": "",
        "ibkr_activity_source": "",
        "ibkr_activity_as_of": "",
        "ibkr_activity_file_updated": "",
        "ibkr_trade_source": "",
        "ibkr_trade_as_of": "",
        "ibkr_trade_file_updated": "",
        "ibkr_data_warning": "",
    }


def _load_ibkr_diagnostics(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _ibkr_statement_role(path: Path) -> str:
    name = re.sub(r"(?:\s+\d+|\s*\(\d+\)|-\d+)$", "", path.stem.lower())
    compact = re.sub(r"[\s_-]+", "", name)
    if any(token in compact for token in ("tradeconfirm", "custtrade", "todaytrade")):
        return "trade"
    if any(token in compact for token in ("activity", "pasttrade", "customisedtransac", "customizedtransac")):
        return "activity"
    if path.suffix.lower() == ".xml":
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            return ""
        tags = {_xml_tag(element) for element in root.iter()}
        if "TradeConfirms" in tags or "TradeConfirm" in tags:
            return "trade"
        if "FlexStatement" in tags or "OpenPositions" in tags:
            return "activity"
    return ""


def _latest_ibkr_source(paths: list[Path]) -> Path:
    return max(
        paths,
        key=lambda path: (
            _ibkr_observation_date(path),
            path.stat().st_mtime if path.exists() else 0,
        ),
    )


def _ibkr_source_label(path: Path | None) -> str:
    if path is None:
        return ""
    return "IBKR Flex live" if path.name.lower().startswith("ibkr-") else "OneDrive manual"


def _ibkr_observation_date(path: Path | None) -> str:
    if path is None:
        return ""
    candidates: list[str] = []
    try:
        for row in _iter_ibkr_rows(path):
            for key in ("TradeDate", "ReportDate", "Date/Time", "Date"):
                parsed = _normalize_ibkr_date(row.get(key))
                if parsed:
                    candidates.append(parsed)
        if path.suffix.lower() == ".xml":
            root = ET.parse(path).getroot()
            for element in root.iter():
                for key in ("toDate", "reportDate", "tradeDate", "dateTime", "date"):
                    parsed = _normalize_ibkr_date(element.attrib.get(key))
                    if parsed:
                        candidates.append(parsed)
    except (OSError, UnicodeDecodeError, csv.Error, ET.ParseError, RuntimeError):
        pass
    return max(candidates) if candidates else ""


def _normalize_ibkr_date(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", raw)
    if not match:
        return ""
    try:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        ).date().isoformat()
    except ValueError:
        return ""


def _ibkr_file_updated_at(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    utc_updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    updated = utc_updated.astimezone(_timezone_for(utc_updated, "Europe/London"))
    return updated.strftime("%Y-%m-%d %H:%M UK")


def _ibkr_source_summary(label: str, path: Path | None) -> str:
    if path is None:
        return f"{label} 缺失"
    source = _ibkr_source_label(path)
    as_of = _ibkr_observation_date(path) or "未知"
    updated = _ibkr_file_updated_at(path)
    updated_text = f"，文件更新 {updated}" if updated else ""
    return f"{label} 来源 {source}，最近有效记录 {as_of}{updated_text}"


if __name__ == "__main__":
    raise SystemExit(main())
