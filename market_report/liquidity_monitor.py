from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class NetLiquiditySnapshot:
    level_bn: float | None
    one_week_change_bn: float | None
    four_week_change_bn: float | None
    status: str


def calculate_net_liquidity(
    metrics: dict[str, Any], metric_history: list[dict[str, Any]], report_date: str
) -> NetLiquiditySnapshot:
    current = _composite_from_scored_metrics(metrics)
    if current is None:
        return NetLiquiditySnapshot(None, None, None, "missing_components")

    try:
        current_date = date.fromisoformat(report_date)
    except ValueError:
        return NetLiquiditySnapshot(current, None, None, "invalid_date")

    observations: list[tuple[date, float]] = []
    for row in metric_history:
        try:
            observation_date = date.fromisoformat(str(row.get("report_date")))
        except ValueError:
            continue
        composite = _composite_from_saved_metrics(row.get("metrics") or {})
        if composite is not None and observation_date < current_date:
            observations.append((observation_date, composite))
    observations.sort(key=lambda item: item[0])

    one_week_base = _latest_on_or_before(observations, current_date - timedelta(days=7))
    four_week_base = _latest_on_or_before(observations, current_date - timedelta(days=28))
    one_week = current - one_week_base if one_week_base is not None else None
    four_week = current - four_week_base if four_week_base is not None else None
    status = "ok" if one_week is not None and four_week is not None else "building_history"
    return NetLiquiditySnapshot(current, one_week, four_week, status)


def format_net_liquidity(snapshot: NetLiquiditySnapshot) -> str:
    if snapshot.level_bn is None:
        return "净流动性代理暂不可用：Fed资产、TGA或RRP存在缺失。"
    one_week = _format_change(snapshot.one_week_change_bn, "1周")
    four_week = _format_change(snapshot.four_week_change_bn, "4周")
    qualifier = "历史积累中；" if snapshot.status == "building_history" else ""
    return (
        f"净流动性代理 ${snapshot.level_bn / 1000:.2f}tn；{one_week}；{four_week}。"
        f"{qualifier}口径：Fed资产 - TGA - RRP。"
    )


def _composite_from_scored_metrics(metrics: dict[str, Any]) -> float | None:
    values = []
    for key in ("fed_balance_sheet", "tga", "rrp"):
        scored = metrics.get(key)
        metric = getattr(scored, "metric", None)
        value = getattr(metric, "value", None)
        if not isinstance(value, (int, float)):
            return None
        values.append(float(value))
    return values[0] - values[1] - values[2]


def _composite_from_saved_metrics(metrics: dict[str, Any]) -> float | None:
    values = []
    for key in ("fed_balance_sheet", "tga", "rrp"):
        value = (metrics.get(key) or {}).get("value")
        if not isinstance(value, (int, float)):
            return None
        values.append(float(value))
    return values[0] - values[1] - values[2]


def _latest_on_or_before(observations: list[tuple[date, float]], target: date) -> float | None:
    eligible = [value for observation_date, value in observations if observation_date <= target]
    return eligible[-1] if eligible else None


def _format_change(value: float | None, label: str) -> str:
    if value is None:
        return f"{label}变化待积累"
    direction = "注入" if value > 0 else "回笼" if value < 0 else "持平"
    return f"{label} {value:+,.0f}bn（{direction}）"
