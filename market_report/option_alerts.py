from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import json
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class OptionRiskAlert:
    alert_id: str
    contract_key: str
    severity: str
    underlying: str
    symbol: str
    expiry: str
    right: str
    strike: float | None
    summary: str
    details: tuple[str, ...]
    source: str


_OCC_SYMBOL_RE = re.compile(r"^\s*([A-Z0-9.\-]+)\s*(\d{6})([CP])(\d{8})\s*$")


def build_option_risk_alerts(
    legs: Iterable[dict[str, Any]],
    previous_state: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    cooldown_hours: float = 24.0,
) -> tuple[tuple[OptionRiskAlert, ...], dict[str, Any]]:
    current_time = _aware_now(now)
    state = previous_state or {}
    previous_contracts = state.get("contracts") if isinstance(state.get("contracts"), dict) else {}
    sent_alerts = dict(state.get("sent_alerts") if isinstance(state.get("sent_alerts"), dict) else {})
    current_contracts: dict[str, dict[str, Any]] = {}
    alerts: list[OptionRiskAlert] = []

    for leg in legs:
        snapshot = _leg_snapshot(leg, current_time)
        if not snapshot:
            continue
        key = str(snapshot["key"])
        current_contracts[key] = snapshot
        previous = previous_contracts.get(key)
        if not isinstance(previous, dict):
            continue
        alert = _evaluate_snapshot_change(snapshot, previous)
        if alert is None:
            continue
        if _within_cooldown(sent_alerts.get(alert.alert_id), current_time, cooldown_hours):
            continue
        alerts.append(alert)
        sent_alerts[alert.alert_id] = current_time.isoformat()

    return (
        tuple(alerts),
        {
            "updated_at": current_time.isoformat(),
            "contracts": current_contracts,
            "sent_alerts": _prune_sent_alerts(sent_alerts, current_time),
        },
    )


def load_option_alert_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_option_alert_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _evaluate_snapshot_change(snapshot: dict[str, Any], previous: dict[str, Any]) -> OptionRiskAlert | None:
    triggers: list[tuple[str, str, str]] = []
    severity_rank = 0

    iv = _num(snapshot.get("iv"))
    prev_iv = _num(previous.get("iv"))
    if iv is not None and prev_iv is not None:
        iv_point_change = iv - prev_iv
        iv_pct_change = _pct_change(iv, prev_iv)
        abs_points = abs(iv_point_change)
        abs_pct = abs(iv_pct_change) if iv_pct_change is not None else 0.0
        if abs_points >= 0.10 or abs_pct >= 40.0:
            severity_rank = max(severity_rank, 2)
            triggers.append(("iv", "red", f"IV {prev_iv * 100:.1f}% → {iv * 100:.1f}%（{iv_point_change * 100:+.1f} vol pts）"))
        elif abs_points >= 0.05 or abs_pct >= 20.0:
            severity_rank = max(severity_rank, 1)
            triggers.append(("iv", "yellow", f"IV {prev_iv * 100:.1f}% → {iv * 100:.1f}%（{iv_point_change * 100:+.1f} vol pts）"))

    mark = _num(snapshot.get("mark"))
    prev_mark = _num(previous.get("mark"))
    if mark is not None and prev_mark is not None:
        mark_pct_change = _pct_change(mark, prev_mark)
        abs_pct = abs(mark_pct_change) if mark_pct_change is not None else 0.0
        if abs_pct >= 50.0:
            severity_rank = max(severity_rank, 2)
            triggers.append(("mark", "red", f"mark {prev_mark:.2f} → {mark:.2f}（{mark_pct_change:+.1f}%）"))
        elif abs_pct >= 25.0:
            severity_rank = max(severity_rank, 1)
            triggers.append(("mark", "yellow", f"mark {prev_mark:.2f} → {mark:.2f}（{mark_pct_change:+.1f}%）"))

    if not triggers:
        return None

    severity = "red" if severity_rank >= 2 else "yellow"
    trigger_types = {item[0] for item in triggers}
    primary_type = "iv" if "iv" in trigger_types else "mark"
    alert_id = f"{snapshot['key']}|{primary_type}-{severity}"
    label = "红色" if severity == "red" else "黄色"
    underlying = str(snapshot.get("underlying") or "")
    summary = f"{underlying} 期权{label}波动提醒：{'; '.join(item[2] for item in triggers)}"
    details = [
        f"合约：{_format_option_contract(snapshot)}",
        f"方向/数量：{_format_option_position(snapshot)}",
        f"当前MTM：{_fmt_signed_gbp(snapshot.get('market_value_gbp'))}",
        f"数据源：{snapshot.get('source') or 'statement/market-data cache'}",
    ]
    if underlying.upper() == "VIX":
        details.append("VIX 期权对波动率曲线和保护需求非常敏感；需结合VIX现货、期限结构和组合对冲目的复核。")
    return OptionRiskAlert(
        alert_id=alert_id,
        contract_key=str(snapshot["key"]),
        severity=severity,
        underlying=underlying,
        symbol=str(snapshot.get("symbol") or ""),
        expiry=str(snapshot.get("expiry") or ""),
        right=str(snapshot.get("right") or ""),
        strike=_num(snapshot.get("strike")),
        summary=summary,
        details=tuple(details),
        source=str(snapshot.get("source") or ""),
    )


def _leg_snapshot(leg: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    mark = _num(leg.get("mark_price"))
    iv = _num(leg.get("implied_volatility"))
    market_value_gbp = _num(leg.get("market_value_gbp"))
    if mark is None and iv is None and market_value_gbp is None:
        return None
    key = _contract_key(leg)
    if not key:
        return None
    return {
        "key": key,
        "symbol": str(leg.get("symbol") or ""),
        "underlying": str(leg.get("underlying") or ""),
        "expiry": str(leg.get("expiry") or ""),
        "right": str(leg.get("right") or "").upper(),
        "strike": _num(leg.get("strike")),
        "side": str(leg.get("side") or ""),
        "signed_contracts": _num(leg.get("signed_contracts")),
        "mark": mark,
        "iv": iv,
        "market_value_gbp": market_value_gbp,
        "source": str(leg.get("market_data_source") or leg.get("source") or ""),
        "observed_at": now.isoformat(),
    }


def _contract_key(leg: dict[str, Any]) -> str:
    underlying = str(leg.get("underlying") or "").strip().upper()
    expiry = str(leg.get("expiry") or "").strip()
    right = str(leg.get("right") or "").strip().upper()
    strike = _fmt_strike(_num(leg.get("strike")))
    if underlying and expiry and right and strike:
        return f"{underlying}|{expiry}|{right}|{strike}"
    symbol = str(leg.get("symbol") or "").strip().upper()
    return symbol


def _format_option_contract(snapshot: dict[str, Any]) -> str:
    raw_symbol = str(snapshot.get("symbol") or "").strip()
    underlying = str(snapshot.get("underlying") or "").strip().upper()
    expiry = str(snapshot.get("expiry") or "").strip()
    right = str(snapshot.get("right") or "").strip().upper()
    strike = _num(snapshot.get("strike"))

    parsed = _parse_occ_symbol(raw_symbol)
    if parsed is not None:
        parsed_underlying, parsed_expiry, parsed_right, parsed_strike = parsed
        underlying = underlying or parsed_underlying
        expiry = expiry or parsed_expiry
        right = right or parsed_right
        strike = strike if strike is not None else parsed_strike

    strike_text = _fmt_strike(strike)
    right_label = _format_right(right)
    if underlying and expiry and right_label and strike_text:
        readable = f"{underlying} {expiry} {strike_text} {right_label}"
    else:
        readable = raw_symbol or str(snapshot.get("key") or "N/A")

    if raw_symbol and raw_symbol.upper() != readable.upper():
        return f"{readable}（原始代码：{raw_symbol}）"
    return readable


def _format_option_position(snapshot: dict[str, Any]) -> str:
    contracts = _num(snapshot.get("signed_contracts"))
    side = str(snapshot.get("side") or "").strip().upper()
    if contracts is not None and abs(contracts) > 1e-12:
        direction = "short" if contracts < 0 else "long"
        return f"{direction} {abs(contracts):g} 张"
    if side:
        return side
    return "N/A"


def _parse_occ_symbol(symbol: str) -> tuple[str, str, str, float] | None:
    match = _OCC_SYMBOL_RE.match(symbol.upper())
    if not match:
        return None
    underlying, date_part, right, strike_part = match.groups()
    expiry = f"20{date_part[:2]}-{date_part[2:4]}-{date_part[4:6]}"
    strike = int(strike_part) / 1000.0
    return underlying, expiry, right, strike


def _format_right(right: str) -> str:
    normalized = right.strip().upper()
    if normalized == "P":
        return "Put"
    if normalized == "C":
        return "Call"
    return normalized


def _within_cooldown(sent_at: object, now: datetime, cooldown_hours: float) -> bool:
    if not sent_at:
        return False
    try:
        value = datetime.fromisoformat(str(sent_at))
    except ValueError:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=now.tzinfo)
    return now - value.astimezone(now.tzinfo) < timedelta(hours=cooldown_hours)


def _prune_sent_alerts(sent_alerts: dict[str, str], now: datetime) -> dict[str, str]:
    cutoff = now - timedelta(days=30)
    pruned: dict[str, str] = {}
    for key, value in sent_alerts.items():
        try:
            sent_at = datetime.fromisoformat(str(value))
        except ValueError:
            continue
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=now.tzinfo)
        if sent_at.astimezone(now.tzinfo) >= cutoff:
            pruned[key] = str(value)
    return pruned


def _num(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _pct_change(current: float, previous: float) -> float | None:
    if abs(previous) < 1e-12:
        return None
    return (current - previous) / abs(previous) * 100.0


def _fmt_strike(value: object) -> str:
    number = _num(value)
    if number is None:
        return ""
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _fmt_signed_gbp(value: object) -> str:
    number = _num(value)
    if number is None:
        return "N/A"
    sign = "+" if number >= 0 else "-"
    return f"{sign}£{abs(number):,.2f}"


def _aware_now(now: datetime | None) -> datetime:
    value = now or datetime.now().astimezone()
    if value.tzinfo is None:
        return value.astimezone()
    return value
