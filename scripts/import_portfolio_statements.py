from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import re
import sys
import urllib.parse
import urllib.request
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
    option_lifecycle = _extract_ibkr_option_lifecycle_events(ibkr_paths) if ibkr_paths else []
    if not positions:
        raise SystemExit("No open positions found in supported portfolio statements.")

    rows = _build_portfolio_rows(positions)
    if rows and option_legs:
        rows[0]["option_legs_json"] = json.dumps(option_legs, ensure_ascii=False, separators=(",", ":"))
        _apply_closed_option_realized_pnl(rows, _closed_option_realized_summary(option_legs))
    if rows:
        rows[0]["option_lifecycle_json"] = json.dumps(
            option_lifecycle,
            ensure_ascii=False,
            separators=(",", ":"),
        )
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
        if _ibkr_is_position_row(row):
            # OpenPosition rows are snapshots, not cash-flow executions. Counting
            # them here can double count holdings and dilute cost basis after a
            # partial sale. Option MTM still uses POSITION rows separately.
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
            positions[symbol]["lots"].append(
                {
                    "quantity": quantity,
                    "cost_gbp": cost,
                    "opened_at": _format_ibkr_date(str(row.get("TradeDate") or row.get("Date/Time") or "")),
                    "broker": "IBKR",
                }
            )
        elif activity == "SELL":
            current_quantity = positions[symbol]["quantity"]
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
            realized_pnl, consumed_cost, closed_trades = _consume_ibkr_lots_fifo(
                symbol=symbol,
                lots=positions[symbol].setdefault("lots", []),
                quantity=matched_quantity,
                net_proceeds_gbp=matched_proceeds,
                closed_at=_format_ibkr_date(str(row.get("TradeDate") or row.get("Date/Time") or "")),
            )
            positions[symbol]["realized_pnl_gbp"] += realized_pnl
            positions[symbol]["closed_trades"].extend(closed_trades)
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
            positions[symbol]["cost_gbp"] = max(positions[symbol]["cost_gbp"] - consumed_cost, 0.0)
    _add_ibkr_dividends(paths, positions)
    return dict(positions)


def _consume_ibkr_lots_fifo(
    *,
    symbol: str,
    lots: object,
    quantity: float,
    net_proceeds_gbp: float,
    closed_at: str,
) -> tuple[float, float, list[dict[str, Any]]]:
    if not isinstance(lots, list) or quantity <= 0:
        return 0.0, 0.0, []
    remaining = quantity
    realized_pnl = 0.0
    consumed_cost = 0.0
    closed_trades: list[dict[str, Any]] = []
    while remaining > 1e-10 and lots:
        lot = lots[0]
        lot_quantity = float(lot.get("quantity") or 0.0)
        lot_cost = float(lot.get("cost_gbp") or 0.0)
        if lot_quantity <= 1e-10:
            lots.pop(0)
            continue
        matched = min(remaining, lot_quantity)
        lot_ratio = matched / lot_quantity
        sale_ratio = matched / quantity if quantity else 0.0
        cost_basis = lot_cost * lot_ratio
        allocated_net = net_proceeds_gbp * sale_ratio
        pnl = allocated_net - cost_basis
        opened_at = str(lot.get("opened_at") or "")
        holding_days = _holding_days(opened_at, closed_at)
        closed_trades.append(
            {
                "symbol": symbol,
                "opened_at": opened_at,
                "closed_at": closed_at,
                "holding_days": holding_days,
                "quantity": round(matched, 8),
                "cost_basis_gbp": round(cost_basis, 4),
                "gross_proceeds_gbp": round(allocated_net, 4),
                "net_proceeds_gbp": round(allocated_net, 4),
                "implied_trading_cost_gbp": 0.0,
                "realized_pnl_gbp": round(pnl, 4),
                "broker": "IBKR",
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


def _holding_days(opened_at: str, closed_at: str) -> int | None:
    try:
        opened = datetime.fromisoformat(opened_at).date()
        closed = datetime.fromisoformat(closed_at).date()
    except ValueError:
        return None
    return max((closed - opened).days, 0)


def _extract_ibkr_option_legs(paths: list[Path]) -> list[dict[str, Any]]:
    rows, _duplicate_count = _unique_ibkr_rows(paths)
    fx_rates_to_base = _ibkr_fx_rates_to_base_by_date(rows)
    legs: list[dict[str, Any]] = []
    mtm_by_contract: dict[tuple[str, str, str, float | None], dict[str, Any]] = {}
    for row in rows:
        asset_category = str(row.get("AssetCategory") or "").strip().upper()
        if asset_category != "OPT":
            continue
        raw_symbol = str(row.get("Symbol") or "").strip().upper()
        underlying = _option_underlying(row, raw_symbol)
        right = _option_right(row, raw_symbol)
        expiry = _option_expiry(row, raw_symbol)
        strike = _option_strike(row, raw_symbol)
        multiplier = _safe_float(row.get("Multiplier") or row.get("multiplier")) or 100.0
        key = _option_contract_key(underlying, expiry, right, strike)
        if _ibkr_is_position_row(row):
            signed_position = _safe_float(row.get("Position") or row.get("Quantity") or row.get("TradeQuantity"))
            mtm = _ibkr_option_mtm(row, signed_position, multiplier, fx_rates_to_base)
            mtm_by_contract[key] = {
                **mtm,
                "symbol": raw_symbol,
                "underlying": underlying,
                "expiry": expiry,
                "right": right,
                "strike": strike,
                "side": "POSITION",
                "contracts": abs(signed_position) if signed_position is not None else None,
                "signed_contracts": signed_position,
                "multiplier": multiplier,
                "currency": str(row.get("Currency") or "").strip().upper(),
                "trade_date": _format_ibkr_date(str(row.get("ReportDate") or row.get("Date/Time") or "")),
                "source": "IBKR open position",
                "fx_rate_to_base": _safe_float(row.get("FxRateToBase")),
            }
            continue
        quantity = _ibkr_quantity(row)
        if quantity is None or quantity <= 0:
            continue
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
        leg = {
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
                "fx_rate_to_base": _safe_float(row.get("FxRateToBase")),
            }
        leg.update(mtm_by_contract.get(key, {}))
        legs.append(leg)
    for leg in legs:
        key = _option_contract_key(
            str(leg.get("underlying") or ""),
            str(leg.get("expiry") or ""),
            str(leg.get("right") or ""),
            _safe_float(leg.get("strike")),
        )
        leg.update(mtm_by_contract.get(key, {}))
    seen_contracts = {
        _option_contract_key(
            str(leg.get("underlying") or ""),
            str(leg.get("expiry") or ""),
            str(leg.get("right") or ""),
            _safe_float(leg.get("strike")),
        )
        for leg in legs
    }
    for key, mtm_leg in mtm_by_contract.items():
        if key not in seen_contracts:
            legs.append(mtm_leg)
    _enrich_option_legs_with_yahoo_fallback(legs, fx_rates_to_base)
    return sorted(
        legs,
        key=lambda item: (
            str(item.get("underlying") or ""),
            str(item.get("expiry") or ""),
            str(item.get("right") or ""),
            float(item.get("strike") or 0),
        ),
    )


def _closed_option_realized_summary(option_legs: list[dict[str, Any]]) -> dict[str, Any]:
    by_contract: dict[tuple[str, str, str, float | None], list[dict[str, Any]]] = defaultdict(list)
    for leg in option_legs:
        key = _option_contract_key(
            str(leg.get("underlying") or ""),
            str(leg.get("expiry") or ""),
            str(leg.get("right") or ""),
            _safe_float(leg.get("strike")),
        )
        if not key[0] or not key[1] or not key[2]:
            continue
        by_contract[key].append(leg)

    closed_options: list[dict[str, Any]] = []
    realized_total_gbp = 0.0
    for (underlying, expiry, right, strike), legs in by_contract.items():
        trade_legs = [
            leg
            for leg in legs
            if str(leg.get("side") or "").upper() in {"BUY", "SELL"}
            and _safe_float(leg.get("net_cash_after_fee_gbp")) is not None
        ]
        if not trade_legs:
            continue
        open_positions = [
            leg
            for leg in legs
            if str(leg.get("side") or "").upper() == "POSITION"
            or str(leg.get("source") or "").lower().startswith("ibkr open position")
        ]
        if any(abs(_safe_float(leg.get("signed_contracts")) or 0.0) > 1e-6 for leg in open_positions):
            continue
        net_contracts = sum(_safe_float(leg.get("signed_contracts")) or 0.0 for leg in trade_legs)
        if abs(net_contracts) > 1e-6:
            continue
        realized_gbp = sum(_safe_float(leg.get("net_cash_after_fee_gbp")) or 0.0 for leg in trade_legs)
        realized_native = sum(_safe_float(leg.get("net_cash_after_fee_native")) or 0.0 for leg in trade_legs)
        realized_total_gbp += realized_gbp
        closed_options.append(
            {
                "underlying": underlying,
                "expiry": expiry,
                "right": right,
                "strike": strike,
                "legs": len(trade_legs),
                "opened_at": min(str(leg.get("trade_date") or "") for leg in trade_legs),
                "closed_at": max(str(leg.get("trade_date") or "") for leg in trade_legs),
                "realized_pnl_gbp": realized_gbp,
                "realized_pnl_native": realized_native,
                "currency": str(trade_legs[0].get("currency") or ""),
            }
        )
    return {
        "realized_pnl_gbp": realized_total_gbp,
        "closed_options": sorted(
            closed_options,
            key=lambda item: (str(item.get("closed_at") or ""), str(item.get("underlying") or "")),
            reverse=True,
        ),
    }


def _apply_closed_option_realized_pnl(rows: list[dict[str, str]], summary: dict[str, Any]) -> None:
    realized_gbp = _safe_float(summary.get("realized_pnl_gbp")) or 0.0
    closed_options = summary.get("closed_options")
    if not rows or abs(realized_gbp) < 1e-9 or not isinstance(closed_options, list):
        return
    for row in rows:
        account_realized = _safe_float(row.get("account_realized_pnl_gbp")) or 0.0
        account_total = _safe_float(row.get("account_total_return_gbp")) or 0.0
        row["account_realized_pnl_gbp"] = _fmt_import_number(account_realized + realized_gbp)
        row["account_total_return_gbp"] = _fmt_import_number(account_total + realized_gbp)
    rows[0]["closed_option_realized_pnl_gbp"] = _fmt_import_number(realized_gbp)
    rows[0]["closed_option_trades_json"] = json.dumps(closed_options, ensure_ascii=False, separators=(",", ":"))


def _fmt_import_number(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def _extract_ibkr_option_lifecycle_events(paths: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for path in paths:
        for row in _iter_ibkr_rows(path):
            if not _is_option_lifecycle_row(row):
                continue
            raw_symbol = str(row.get("Symbol") or row.get("UnderlyingSymbol") or "").strip().upper()
            underlying = _option_underlying(row, raw_symbol) or str(row.get("UnderlyingSymbol") or "").strip().upper()
            event = {
                "event_type": _option_lifecycle_type(row),
                "symbol": raw_symbol,
                "underlying": underlying,
                "expiry": _option_expiry(row, raw_symbol),
                "right": _option_right(row, raw_symbol),
                "strike": _option_strike(row, raw_symbol),
                "quantity": _safe_float(row.get("Quantity") or row.get("TradeQuantity") or row.get("Position")),
                "amount_gbp": _ibkr_amount_in_base_currency(row, _safe_float(row.get("Amount")) or 0.0)
                if row.get("Amount")
                else None,
                "currency": str(row.get("Currency") or "").strip().upper(),
                "date": _format_ibkr_date(str(row.get("TradeDate") or row.get("ReportDate") or row.get("Date/Time") or "")),
                "source_file": path.name,
                "status": "captured_not_booked",
            }
            fingerprint = tuple(str(event.get(key) or "") for key in ("event_type", "symbol", "date", "quantity", "amount_gbp"))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            events.append(event)
    return sorted(
        events,
        key=lambda item: (str(item.get("date") or ""), str(item.get("underlying") or ""), str(item.get("event_type") or "")),
        reverse=True,
    )


def _is_option_lifecycle_row(row: dict[str, str]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in (
            "LevelOfDetail",
            "Type",
            "DividendType",
            "Code",
            "Description",
            "TransactionType",
            "ActivityType",
            "AssetCategory",
            "Symbol",
        )
    ).upper()
    if not any(token in text for token in ("EXERCI", "ASSIGN", "EXPIR", "LAPSE")):
        return False
    asset_category = str(row.get("AssetCategory") or "").strip().upper()
    symbol = str(row.get("Symbol") or "").strip().upper()
    return asset_category in {"", "OPT"} or bool(re.search(r"\d{6}[CP]\d{8}$", symbol))


def _option_lifecycle_type(row: dict[str, str]) -> str:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("Type", "Description", "TransactionType", "ActivityType", "LevelOfDetail", "Code")
    ).upper()
    if "ASSIGN" in text:
        return "assignment"
    if "EXERCI" in text:
        return "exercise"
    if "EXPIR" in text or "LAPSE" in text:
        return "expiration"
    return "option_lifecycle"


def _ibkr_is_position_row(row: dict[str, str]) -> bool:
    return str(row.get("LevelOfDetail") or "").strip().upper() == "POSITION"


def _option_contract_key(
    underlying: str,
    expiry: str,
    right: str,
    strike: float | None,
) -> tuple[str, str, str, float | None]:
    return (underlying.strip().upper(), expiry, right.strip().upper(), strike)


def _ibkr_option_mtm(
    row: dict[str, str],
    signed_contracts: float | None,
    multiplier: float,
    fx_rates_to_base: dict[tuple[str, str], float] | None = None,
) -> dict[str, float | None]:
    mark_price = _safe_float(row.get("MarkPrice") or row.get("ClosePrice") or row.get("MarketPrice") or row.get("LastPrice"))
    direct_market_value = _safe_float(row.get("MarketValue") or row.get("PositionValue"))
    if direct_market_value is not None:
        market_value_native = direct_market_value
    elif mark_price is not None and signed_contracts is not None:
        market_value_native = signed_contracts * multiplier * mark_price
    else:
        market_value_native = None
    market_value_gbp = (
        _ibkr_amount_in_base_currency(row, market_value_native, fx_rates_to_base)
        if market_value_native is not None
        else None
    )
    return {
        "mark_price": mark_price,
        "market_value_native": market_value_native,
        "market_value_gbp": market_value_gbp,
    }


_YAHOO_OPTION_CACHE: dict[tuple[str, str], dict[str, Any] | None] = {}


def _enrich_option_legs_with_yahoo_fallback(
    legs: list[dict[str, Any]],
    fx_rates_to_base: dict[tuple[str, str], float] | None = None,
) -> None:
    for leg in legs:
        if _safe_float(leg.get("mark_price")) is not None and _safe_float(leg.get("market_value_native")) is not None:
            continue
        quote = _yahoo_option_quote_for_leg(leg)
        if not quote:
            continue
        mark = _option_quote_mark(quote)
        signed_contracts = _safe_float(leg.get("signed_contracts"))
        multiplier = _safe_float(leg.get("multiplier")) or 100.0
        if _safe_float(leg.get("mark_price")) is None and mark is not None:
            leg["mark_price"] = mark
        if _safe_float(leg.get("market_value_native")) is None and mark is not None and signed_contracts is not None:
            leg["market_value_native"] = signed_contracts * multiplier * mark
        if _safe_float(leg.get("market_value_gbp")) is None and _safe_float(leg.get("market_value_native")) is not None:
            fx_rate = _option_leg_fx_rate_to_base(leg, fx_rates_to_base)
            if fx_rate is not None:
                leg["market_value_gbp"] = (_safe_float(leg.get("market_value_native")) or 0.0) * fx_rate
        _enrich_option_leg_greeks(leg, quote)
        source = str(leg.get("source") or "IBKR statement")
        if "Yahoo option chain" not in source:
            leg["source"] = f"{source} + Yahoo option chain"
        leg["market_data_source"] = "Yahoo delayed option chain"
        leg["market_data_time"] = _format_yahoo_timestamp(quote.get("lastTradeDate"))


def _yahoo_option_quote_for_leg(leg: dict[str, Any]) -> dict[str, Any] | None:
    underlying = str(leg.get("underlying") or "").strip().upper()
    expiry = str(leg.get("expiry") or "").strip()
    right = str(leg.get("right") or "").strip().upper()
    strike = _safe_float(leg.get("strike"))
    if not underlying or not expiry or right not in {"C", "P"} or strike is None:
        return None
    for yahoo_symbol in _yahoo_underlying_candidates(underlying):
        payload = _fetch_yahoo_option_chain(yahoo_symbol, expiry)
        quote = _match_yahoo_option_quote(payload, leg, right, strike)
        if quote:
            return quote
    return None


def _yahoo_underlying_candidates(underlying: str) -> list[str]:
    candidates = [underlying]
    if underlying == "VIX":
        candidates.insert(0, "^VIX")
    if "." in underlying:
        candidates.append(underlying.replace(".", "-"))
    seen: set[str] = set()
    return [item for item in candidates if item and not (item in seen or seen.add(item))]


def _fetch_yahoo_option_chain(yahoo_symbol: str, expiry: str) -> dict[str, Any] | None:
    key = (yahoo_symbol, expiry)
    if key in _YAHOO_OPTION_CACHE:
        return _YAHOO_OPTION_CACHE[key]
    try:
        expiry_ts = int(datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        _YAHOO_OPTION_CACHE[key] = None
        return None
    encoded_symbol = urllib.parse.quote(yahoo_symbol, safe="")
    url = f"https://query2.finance.yahoo.com/v7/finance/options/{encoded_symbol}?date={expiry_ts}"
    try:
        payload = _read_yahoo_option_json(url)
    except Exception:
        payload = None
    _YAHOO_OPTION_CACHE[key] = payload
    return payload


def _read_yahoo_option_json(url: str) -> dict[str, Any] | None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Macro Regime Radar option fallback",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=6) as response:
        return json.loads(response.read().decode("utf-8"))


def _match_yahoo_option_quote(
    payload: dict[str, Any] | None,
    leg: dict[str, Any],
    right: str,
    strike: float,
) -> dict[str, Any] | None:
    if not payload:
        return None
    result = (((payload.get("optionChain") or {}).get("result") or []) or [None])[0]
    if not isinstance(result, dict):
        return None
    options = (result.get("options") or []) or []
    if not options or not isinstance(options[0], dict):
        return None
    candidates = options[0].get("calls" if right == "C" else "puts") or []
    normalized_symbol = _normalize_option_contract_symbol(str(leg.get("symbol") or ""))
    best: dict[str, Any] | None = None
    for quote in candidates:
        if not isinstance(quote, dict):
            continue
        contract_symbol = _normalize_option_contract_symbol(str(quote.get("contractSymbol") or ""))
        quote_strike = _safe_float(quote.get("strike"))
        if normalized_symbol and contract_symbol and normalized_symbol == contract_symbol:
            best = quote
            break
        if quote_strike is not None and abs(quote_strike - strike) < 0.001:
            best = quote
    if best and isinstance(result.get("quote"), dict):
        best = {**best, "_underlying_price": _safe_float(result["quote"].get("regularMarketPrice"))}
    return best


def _normalize_option_contract_symbol(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _option_quote_mark(quote: dict[str, Any]) -> float | None:
    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2
    return _safe_float(quote.get("lastPrice") or quote.get("regularMarketPrice"))


def _option_leg_fx_rate_to_base(
    leg: dict[str, Any],
    fx_rates_to_base: dict[tuple[str, str], float] | None = None,
) -> float | None:
    direct = _safe_float(leg.get("fx_rate_to_base"))
    if direct is not None and direct > 0:
        return direct
    native_cash = _safe_float(leg.get("net_cash_after_fee_native") or leg.get("net_cash_native"))
    gbp_cash = _safe_float(leg.get("net_cash_after_fee_gbp") or leg.get("net_cash_gbp"))
    if native_cash not in (None, 0) and gbp_cash is not None:
        return abs(gbp_cash / native_cash)
    currency = str(leg.get("currency") or "").strip().upper()
    trade_date = str(leg.get("trade_date") or "").strip()
    if fx_rates_to_base and currency and trade_date:
        return fx_rates_to_base.get((currency, trade_date)) or fx_rates_to_base.get((currency, ""))
    if currency in {"", "GBP"}:
        return 1.0
    return None


def _enrich_option_leg_greeks(leg: dict[str, Any], quote: dict[str, Any]) -> None:
    iv = _safe_float(quote.get("impliedVolatility"))
    underlying_price = _safe_float(quote.get("_underlying_price"))
    strike = _safe_float(leg.get("strike"))
    expiry = str(leg.get("expiry") or "")
    right = str(leg.get("right") or "").upper()
    signed_contracts = _safe_float(leg.get("signed_contracts")) or 0.0
    multiplier = _safe_float(leg.get("multiplier")) or 100.0
    if iv is not None:
        leg["implied_volatility"] = iv
    if iv is None or iv <= 0 or underlying_price is None or strike is None or strike <= 0 or right not in {"C", "P"}:
        return
    try:
        expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    except ValueError:
        return
    days = max((expiry_date - datetime.now(timezone.utc).date()).days, 1)
    t = days / 365.0
    risk_free = 0.045
    sqrt_t = math.sqrt(t)
    d1 = (math.log(underlying_price / strike) + (risk_free + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    nd1 = _normal_cdf(d1)
    nd2 = _normal_cdf(d2)
    pdf_d1 = _normal_pdf(d1)
    unit_delta = nd1 if right == "C" else nd1 - 1
    unit_gamma = pdf_d1 / (underlying_price * iv * sqrt_t)
    call_theta = (
        -(underlying_price * pdf_d1 * iv) / (2 * sqrt_t)
        - risk_free * strike * math.exp(-risk_free * t) * nd2
    ) / 365.0
    put_theta = (
        -(underlying_price * pdf_d1 * iv) / (2 * sqrt_t)
        + risk_free * strike * math.exp(-risk_free * t) * _normal_cdf(-d2)
    ) / 365.0
    unit_theta = call_theta if right == "C" else put_theta
    unit_vega = underlying_price * pdf_d1 * sqrt_t / 100.0
    leg["underlying_price"] = underlying_price
    leg["unit_delta"] = unit_delta
    leg["position_delta"] = unit_delta * signed_contracts * multiplier
    leg["unit_gamma"] = unit_gamma
    leg["position_gamma"] = unit_gamma * signed_contracts * multiplier
    leg["unit_theta"] = unit_theta
    leg["position_theta"] = unit_theta * signed_contracts * multiplier
    leg["unit_vega"] = unit_vega
    leg["position_vega"] = unit_vega * signed_contracts * multiplier


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _format_yahoo_timestamp(value: object) -> str:
    timestamp = _safe_float(value)
    if timestamp is None:
        return ""
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


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
            level = str(row.get("LevelOfDetail") or "").upper()
            if level not in {"EXECUTION", "POSITION"}:
                continue
            if level == "EXECUTION" and not (row.get("Buy/Sell") or row.get("TransactionType")):
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
            compact_header = {_compact_ibkr_field_name(value) for value in raw}
            if "levelofdetail" in compact_header and (
                "assetcategory" in compact_header
                or "assetclass" in compact_header
                or "symbol" in compact_header
            ):
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
            elif tag == "OpenPosition":
                yield _normalize_ibkr_xml_row(element.attrib, row_kind="POSITION")
                element.clear()
            elif _is_ibkr_option_lifecycle_tag(tag):
                yield _normalize_ibkr_xml_row(element.attrib, row_kind="OPTION_LIFECYCLE")
                element.clear()
            elif tag == "CashTransaction":
                yield _normalize_ibkr_xml_row(element.attrib, row_kind="CASH")
                element.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"Invalid IBKR Flex XML file {path}: {exc}") from exc


def _normalize_ibkr_csv_row(row: dict[str, str]) -> dict[str, str]:
    normalized = {str(key): str(value) for key, value in row.items()}
    lower = {key.lower(): value for key, value in normalized.items()}
    compact = {_compact_ibkr_field_name(key): value for key, value in normalized.items()}

    def pick(*names: str) -> str:
        for name in names:
            value = lower.get(name.lower())
            if value in (None, ""):
                value = compact.get(_compact_ibkr_field_name(name))
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
        "Type": pick("Type", "TransactionType", "Description"),
        "Description": pick("Description", "TransactionType", "Type"),
        "TransactionType": pick("TransactionType", "Type", "Description"),
        "ActivityType": pick("ActivityType"),
        "Code": pick("Code"),
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
        "Cost": pick("Cost", "CostBasis", "CostBasisMoney"),
        "Commission": pick("Commission", "IBCommission", "TradeCommission"),
        "IBCommission": pick("IBCommission", "Commission", "TradeCommission"),
        "Tax": pick("Tax", "Taxes"),
        "Currency": pick("Currency", "CurrencyPrimary", "TradeCurrency", "CommissionCurrency", "IBCommissionCurrency"),
        "FxRateToBase": pick("FxRateToBase", "FXRateToBase"),
        "Multiplier": pick("Multiplier"),
        "PutCall": pick("PutCall", "Right"),
        "Strike": pick("Strike"),
        "Expiry": pick("Expiry", "ExpiryDate", "Maturity"),
        "MarkPrice": pick("MarkPrice", "Mark", "MarketPrice", "ClosePrice", "LastPrice"),
        "ClosePrice": pick("ClosePrice", "LastPrice"),
        "MarketValue": pick("MarketValue", "PositionValue", "Value"),
        "Position": pick("Position", "Quantity"),
    }


def _normalize_ibkr_xml_row(attrs: dict[str, str], *, row_kind: str) -> dict[str, str]:
    normalized = {key: str(value) for key, value in attrs.items()}
    lower = {key.lower(): value for key, value in normalized.items()}
    compact = {_compact_ibkr_field_name(key): value for key, value in normalized.items()}

    def pick(*names: str) -> str:
        for name in names:
            value = lower.get(name.lower())
            if value in (None, ""):
                value = compact.get(_compact_ibkr_field_name(name))
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
            "Cost": pick("cost", "costBasis", "costBasisMoney"),
            "Commission": pick("commission", "ibCommission"),
            "IBCommission": pick("ibCommission", "commission"),
            "Tax": pick("tax", "taxes"),
            "Currency": pick("currency", "currencyPrimary"),
            "FxRateToBase": pick("fxRateToBase"),
        }
    if row_kind == "POSITION":
        return {
            **normalized,
            "ClientAccountID": pick("accountId", "acctId", "account"),
            "LevelOfDetail": "POSITION",
            "AssetCategory": pick("assetCategory"),
            "Symbol": pick("symbol", "underlyingSymbol"),
            "UnderlyingSymbol": pick("underlyingSymbol"),
            "ReportDate": pick("reportDate", "dateTime", "date"),
            "Date/Time": pick("dateTime", "reportDate", "date"),
            "Quantity": pick("position", "quantity"),
            "TradeQuantity": pick("position", "quantity"),
            "Currency": pick("currency", "currencyPrimary"),
            "FxRateToBase": pick("fxRateToBase"),
            "Multiplier": pick("multiplier"),
            "PutCall": pick("putCall", "right"),
            "Strike": pick("strike"),
            "Expiry": pick("expiry", "expiryDate", "maturity"),
            "MarkPrice": pick("markPrice", "mark", "marketPrice", "closePrice", "lastPrice"),
            "ClosePrice": pick("closePrice", "lastPrice"),
            "MarketValue": pick("marketValue", "positionValue", "value"),
            "Position": pick("position", "quantity"),
        }
    if row_kind == "OPTION_LIFECYCLE":
        return {
            **normalized,
            "ClientAccountID": pick("accountId", "acctId", "account"),
            "LevelOfDetail": (pick("levelOfDetail") or "OPTION_LIFECYCLE").upper(),
            "AssetCategory": pick("assetCategory") or "OPT",
            "Symbol": pick("symbol", "underlyingSymbol"),
            "UnderlyingSymbol": pick("underlyingSymbol"),
            "Type": pick("type", "transactionType", "description") or row_kind,
            "Description": pick("description", "transactionType", "type"),
            "TransactionType": pick("transactionType", "type", "description"),
            "ActivityType": pick("activityType"),
            "Code": pick("code"),
            "TransactionID": pick("transactionID", "transactionId"),
            "ReportDate": pick("reportDate", "dateTime", "date"),
            "TradeDate": pick("tradeDate", "dateTime", "date"),
            "Date/Time": pick("dateTime", "tradeDate", "reportDate", "date"),
            "Quantity": pick("quantity", "tradeQuantity", "position"),
            "TradeQuantity": pick("tradeQuantity", "quantity", "position"),
            "Amount": pick("amount", "netCash", "proceeds"),
            "Currency": pick("currency", "currencyPrimary"),
            "FxRateToBase": pick("fxRateToBase"),
            "Multiplier": pick("multiplier"),
            "PutCall": pick("putCall", "right"),
            "Strike": pick("strike"),
            "Expiry": pick("expiry", "expiryDate", "maturity"),
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
        "Description": pick("description", "transactionType", "type"),
        "TransactionType": pick("transactionType", "type", "description"),
        "ActivityType": pick("activityType"),
        "Code": pick("code"),
        "TransactionID": pick("transactionID", "transactionId"),
        "ReportDate": pick("reportDate", "dateTime", "date"),
        "Date/Time": pick("dateTime", "reportDate", "date"),
        "Amount": pick("amount", "netCash"),
        "Currency": pick("currency", "currencyPrimary"),
        "FxRateToBase": pick("fxRateToBase"),
    }


def _xml_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _is_ibkr_option_lifecycle_tag(tag: str) -> bool:
    compact = _compact_ibkr_field_name(tag)
    return "option" in compact and any(
        token in compact
        for token in ("exercise", "assignment", "expiration", "expire", "expiry")
    )


def _compact_ibkr_field_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


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
    if buy:
        cost_basis = _safe_float(row.get("Cost") or row.get("CostBasis") or row.get("CostBasisMoney"))
        if cost_basis is not None:
            return abs(_ibkr_amount_in_base_currency(row, cost_basis, fx_rates_to_base))
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
    if currency in {"", "GBP"}:
        return amount
    date_key = str(row.get("TradeDate") or row.get("Date/Time") or row.get("ReportDate") or "")[:8]
    actual_fx_rate = (fx_rates_to_base or {}).get((date_key, currency))
    if actual_fx_rate is not None and actual_fx_rate > 0:
        return amount * actual_fx_rate
    fallback_fx_rate = (fx_rates_to_base or {}).get(("", currency))
    if fallback_fx_rate is not None and fallback_fx_rate > 0:
        return amount * fallback_fx_rate
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
    rates = {
        key: value["base"] / value["foreign"]
        for key, value in totals.items()
        if value["base"] > 0 and value["foreign"] > 0
    }
    by_currency: dict[str, dict[str, float]] = defaultdict(lambda: {"base": 0.0, "foreign": 0.0})
    for (_date_key, currency), value in totals.items():
        by_currency[currency]["base"] += value["base"]
        by_currency[currency]["foreign"] += value["foreign"]
    for currency, value in by_currency.items():
        if value["base"] > 0 and value["foreign"] > 0:
            rates[("", currency)] = value["base"] / value["foreign"]
    return rates


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
