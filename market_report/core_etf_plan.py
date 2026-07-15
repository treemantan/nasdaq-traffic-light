from __future__ import annotations

from datetime import date
from typing import Any, Iterable


CORE_ETF_SYMBOLS = ("VUAG.L", "VWRL.L", "CNX1.L", "ISF.L")


def build_core_etf_plan(
    config: dict[str, Any],
    assets: Iterable[Any],
    positions: Iterable[Any],
    as_of: date,
) -> dict[str, Any] | None:
    if not bool(config.get("enabled")):
        return None

    allocations = [
        item
        for item in (config.get("allocations") or [])
        if isinstance(item, dict) and _canonical_symbol(item.get("symbol")) in CORE_ETF_SYMBOLS
    ]
    if not allocations:
        return {
            "enabled": True,
            "as_of": as_of.isoformat(),
            "summary": "核心ETF计划已启用，但尚未配置四只核心ETF的预算。",
            "decisions": [],
            "warnings": ["请通过私有配置或 CORE_ETF_PLAN_JSON 设置 allocations。"],
        }

    asset_map = {_canonical_symbol(item.symbol): item for item in assets}
    position_map = {_canonical_symbol(item.symbol): item for item in positions}
    start_date = _parse_date(config.get("start_date")) or as_of
    elapsed_days = max(0, (as_of - start_date).days)
    fallback_days = max(1, int(_number(config.get("fallback_days")) or 56))
    minimum_order = max(0, _number(config.get("minimum_order_gbp")) or 100)

    decisions = []
    warnings = []
    total_planned = 0.0
    total_due = 0.0
    for item in allocations:
        symbol = _canonical_symbol(item.get("symbol"))
        asset = asset_map.get(symbol)
        position = position_map.get(symbol)
        planned = max(0, _number(item.get("planned_addition_gbp")) or 0)
        target_weight = _normalized_weight(item.get("target_weight"))
        baseline_quantity = _number(item.get("baseline_quantity"))
        total_planned += planned

        if asset is None:
            decisions.append(
                _missing_decision(symbol, target_weight, planned, "ETF行情未进入本次监控结果。")
            )
            continue

        drawdown = _number(getattr(asset, "drawdown_1y_peak_pct", None))
        distance_sma200 = _number(getattr(asset, "distance_sma200", None))
        above_sma200 = distance_sma200 is not None and distance_sma200 >= 0
        stage, cumulative_ratio, trigger = _trigger_stage(
            drawdown,
            above_sma200,
            elapsed_days,
            fallback_days,
        )
        executed, execution_note = _estimated_executed_gbp(position, baseline_quantity)
        due = max(0, planned * cumulative_ratio - (executed or 0))

        asset_as_of = getattr(asset, "as_of", None)
        stale = asset_as_of is None or (as_of - asset_as_of).days > 3
        if stale:
            status = "数据待更新"
            suggested_order = 0.0
            action = "行情日期过旧，不据此下单。"
        elif not above_sma200:
            status = "等待趋势确认"
            suggested_order = 0.0
            action = "价格位于SMA200下方；保留预算，等待重新站回或人工复核基本面。"
        elif due < minimum_order:
            status = "本阶段已覆盖"
            suggested_order = 0.0
            action = "当前触发阶段没有新增额度；等待下一档回撤或时间条件。"
        else:
            status = "可下单"
            suggested_order = round(due, 2)
            action = f"本阶段新增下单上限约£{suggested_order:,.0f}，成交后等待statement更新。"
            total_due += suggested_order

        decisions.append(
            {
                "symbol": symbol,
                "target_weight_pct": target_weight * 100 if target_weight is not None else None,
                "planned_addition_gbp": round(planned, 2),
                "baseline_quantity": baseline_quantity,
                "current_quantity": _number(getattr(position, "quantity", None)) if position else None,
                "estimated_executed_gbp": round(executed, 2) if executed is not None else None,
                "execution_note": execution_note,
                "drawdown_1y_peak_pct": drawdown,
                "distance_sma200_pct": distance_sma200,
                "stage": stage,
                "trigger": trigger,
                "cumulative_budget_pct": cumulative_ratio * 100,
                "status": status,
                "suggested_order_gbp": suggested_order,
                "action": action,
                "market_as_of": asset_as_of.isoformat() if asset_as_of else "",
            }
        )
        if baseline_quantity is None:
            warnings.append(f"{symbol} 未配置baseline_quantity，报告无法自动扣除已执行订单。")

    return {
        "enabled": True,
        "as_of": as_of.isoformat(),
        "start_date": start_date.isoformat(),
        "elapsed_days": elapsed_days,
        "fallback_days": fallback_days,
        "total_planned_addition_gbp": round(total_planned, 2),
        "total_suggested_order_gbp": round(total_due, 2),
        "summary": (
            f"四只核心ETF计划预算£{total_planned:,.0f}；今日满足条件的新增下单上限合计约£{total_due:,.0f}。"
            "下单前仍需核对IBKR实时价与当日事件。"
        ),
        "decisions": decisions,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _trigger_stage(
    drawdown: float | None,
    above_sma200: bool,
    elapsed_days: int,
    fallback_days: int,
) -> tuple[str, float, str]:
    if drawdown is not None and drawdown <= -8:
        return "深度回撤档", 0.8, "距一年高点回撤达到8%或更多，累计释放80%预算。"
    if drawdown is not None and drawdown <= -3:
        return "普通回撤档", 0.5, "距一年高点回撤达到3%或更多，累计释放50%预算。"
    if elapsed_days >= fallback_days and above_sma200:
        return "时间兜底档", 1.0, f"计划已运行{elapsed_days}天且仍在SMA200上方，释放剩余预算。"
    return "首笔试仓档", 0.2, "尚未出现3%回撤，累计仅释放20%试仓预算。"


def _estimated_executed_gbp(position: Any | None, baseline_quantity: float | None) -> tuple[float | None, str]:
    if position is None:
        return None, "未匹配到当前持仓，无法估算已执行金额。"
    if baseline_quantity is None:
        return None, "未配置计划起点数量，当前建议未扣除历史执行。"
    current_quantity = _number(getattr(position, "quantity", None))
    current_price_gbp = _number(getattr(position, "current_price_gbp", None))
    if current_quantity is None or current_price_gbp is None:
        return None, "当前数量或GBP价格缺失，无法估算已执行金额。"
    added_quantity = max(0, current_quantity - baseline_quantity)
    return added_quantity * current_price_gbp, "按新增数量乘当前GBP价格估算，可能与实际成交成本略有差异。"


def _missing_decision(symbol: str, target_weight: float | None, planned: float, reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "target_weight_pct": target_weight * 100 if target_weight is not None else None,
        "planned_addition_gbp": round(planned, 2),
        "status": "数据待更新",
        "stage": "待确认",
        "trigger": reason,
        "suggested_order_gbp": 0.0,
        "action": reason,
    }


def _canonical_symbol(value: object) -> str:
    symbol = str(value or "").strip().upper()
    aliases = {"VUAG": "VUAG.L", "VWRL": "VWRL.L", "CNX1": "CNX1.L", "ISF": "ISF.L"}
    return aliases.get(symbol, symbol)


def _normalized_weight(value: object) -> float | None:
    weight = _number(value)
    if weight is None:
        return None
    return weight / 100 if weight > 1 else weight


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
