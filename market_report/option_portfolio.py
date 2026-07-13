from __future__ import annotations

import json
from typing import Any, Iterable


def option_closeout_snapshot(positions: Iterable[object]) -> dict[str, Any]:
    legs = _option_legs(positions)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for leg in legs:
        key = (str(leg.get("underlying") or ""), str(leg.get("expiry") or ""))
        groups.setdefault(key, []).append(leg)
    return option_closeout_snapshot_from_groups(groups)


def option_closeout_snapshot_from_groups(
    groups: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    results = [_group_unrealized_result(group_legs) for group_legs in groups.values()]
    available = [(value, source) for value, source in results if value is not None]
    sources = {source for _value, source in available}
    signature = sorted(
        f"{underlying}|{expiry}|{_group_position_signature(group_legs)}"
        for (underlying, expiry), group_legs in groups.items()
    )
    return {
        "total_gbp": sum(value or 0.0 for value, _source in available) if available else None,
        "source": next(iter(sources)) if len(sources) == 1 else "混合" if sources else "缺失",
        "available_groups": len(available),
        "total_groups": len(results),
        "complete": bool(results) and len(available) == len(results),
        "position_signature": signature,
    }


def _option_legs(positions: Iterable[object]) -> list[dict[str, Any]]:
    for position in positions:
        raw_json = str(getattr(position, "option_legs_json", "") or "")
        if not raw_json:
            continue
        try:
            raw = json.loads(raw_json)
        except json.JSONDecodeError:
            return []
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    return []


def _group_unrealized_result(legs: list[dict[str, Any]]) -> tuple[float | None, str]:
    direct_values = [_num(leg.get("unrealized_pnl_gbp")) for leg in legs]
    if direct_values and all(value is not None for value in direct_values):
        return sum(value or 0.0 for value in direct_values), "IBKR"
    market_values = [_num(leg.get("market_value_gbp")) for leg in legs]
    present_market_values = [value for value in market_values if value is not None]
    if not present_market_values:
        return None, "缺失"
    net_cash = sum(_cash_after_fee_gbp(leg) for leg in legs)
    return net_cash + sum(present_market_values), "估算"


def _cash_after_fee_gbp(leg: dict[str, Any]) -> float:
    open_premium = _num(leg.get("open_net_premium_gbp"))
    if open_premium is not None:
        return open_premium
    value = _num(leg.get("net_cash_after_fee_gbp"))
    if value is not None:
        return value
    net_cash = _num(leg.get("net_cash_gbp"))
    commission = _num(leg.get("commission_gbp"))
    if net_cash is not None and commission is not None:
        return net_cash + commission
    return net_cash or 0.0


def _group_position_signature(legs: list[dict[str, Any]]) -> str:
    parts = []
    for leg in sorted(
        legs,
        key=lambda item: (
            str(item.get("right") or ""),
            _num(item.get("strike")) or 0.0,
        ),
    ):
        parts.append(
            f"{str(leg.get('right') or '').upper()}"
            f"{_num(leg.get('strike')) or 0:g}"
            f"@{_num(leg.get('signed_contracts')) or 0:g}"
        )
    return ",".join(parts)


def _num(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
