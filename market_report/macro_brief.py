from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .anomaly_detection import AnomalyResult, detect_change_anomaly
from .liquidity_monitor import calculate_net_liquidity, format_net_liquidity
from .volatility_structure import assess_volatility_structure, format_volatility_structure

if TYPE_CHECKING:
    from .scoring import ScoredMetric, ScoredReport


@dataclass(frozen=True)
class MacroBriefSignal:
    label: str
    value: str
    interpretation: str


@dataclass(frozen=True)
class MacroDailyBrief:
    posture: str
    posture_note: str
    transition: str
    score_change: str
    signals: tuple[MacroBriefSignal, ...]
    exposure_change: str
    action_event: str
    actions: tuple[str, ...]
    verify: tuple[str, ...]
    invalidations: tuple[str, ...]
    anomaly_method: str
    liquidity_summary: str
    volatility_summary: str


_MOVE_SCALES = {
    "nasdaq": 1.0,
    "sp500": 0.8,
    "russell2000": 1.2,
    "vix": 10.0,
    "vvix": 8.0,
    "move": 6.0,
    "treasury_2y": 0.08,
    "treasury_10y": 0.08,
    "real_yield_10y": 0.06,
    "dxy": 0.4,
    "credit_spread_hy": 0.15,
    "oil": 2.0,
}


def build_macro_daily_brief(report: ScoredReport) -> MacroDailyBrief:
    posture, posture_note, actions = _risk_posture(report.overall_score)
    signals, anomaly_method = _largest_moves(report.metrics, report.metric_history)
    liquidity = calculate_net_liquidity(report.metrics, report.metric_history, report.report_date)
    volatility = assess_volatility_structure(report.metrics)
    verify = tuple((report.regime.unknowns + report.data_warnings)[:3])
    if not verify:
        verify = ("当前没有重要待核实项。",)
    return MacroDailyBrief(
        posture=posture,
        posture_note=posture_note,
        transition=report.regime_transition,
        score_change=_score_change(report),
        signals=tuple(signals[:3]),
        exposure_change=_rising_exposure(report),
        action_event=_action_event(report),
        actions=actions,
        verify=verify,
        invalidations=_invalidation_conditions(report),
        anomaly_method=anomaly_method,
        liquidity_summary=format_net_liquidity(liquidity),
        volatility_summary=format_volatility_structure(volatility),
    )


def _score_change(report: ScoredReport) -> str:
    delta = report.score_delta
    if delta is None or report.previous_score is None:
        return "风险分变化：暂无昨日基线。"
    direction = "恶化" if delta > 0 else "改善" if delta < 0 else "持平"
    magnitude = "明显" if abs(delta) >= 10 else "边际" if abs(delta) >= 5 else "轻微"
    if delta == 0:
        magnitude = ""
    return f"风险分 {report.previous_score}→{report.overall_score}（{delta:+d}，{magnitude}{direction}）。"


def _rising_exposure(report: ScoredReport) -> str:
    ledger = report.event_risk_ledger
    current = [entry for entry in (getattr(ledger, "entries", ()) or ()) if entry.portfolio_symbols]
    if not current:
        return "当前没有直接映射持仓的事件暴露。"
    previous = {
        str(item.get("label")): item
        for item in (report.previous_state.get("event_exposures", []) if report.previous_state else [])
        if isinstance(item, dict) and item.get("label")
    }
    changes = []
    for entry in current:
        old = previous.get(entry.label)
        old_score = old.get("risk_score") if old else None
        delta = entry.risk_score - old_score if isinstance(old_score, (int, float)) else None
        changes.append((delta if delta is not None else -999, entry))
    rising = [item for item in changes if item[0] > 0]
    if rising:
        delta, entry = max(rising, key=lambda item: (item[0], item[1].portfolio_weight_pct))
        symbols = "、".join(entry.portfolio_symbols)
        return f"{entry.label} 风险分较昨日 +{delta:.0f}，映射 {symbols}，约占组合 {entry.portfolio_weight_pct:.1f}%。"
    top = max(current, key=lambda item: (item.portfolio_weight_pct, item.risk_score))
    symbols = "、".join(top.portfolio_symbols)
    if not previous:
        return f"事件暴露今日建立基线：{top.label} 映射 {symbols}，约占组合 {top.portfolio_weight_pct:.1f}%。"
    return f"未发现事件暴露较昨日上升；当前最大映射为 {top.label}（{symbols}，{top.portfolio_weight_pct:.1f}%）。"


def _action_event(report: ScoredReport) -> str:
    ledger = report.event_risk_ledger
    mapped = [entry for entry in (getattr(ledger, "entries", ()) or ()) if entry.portfolio_symbols]
    if not mapped:
        return "今日没有需要升级为组合行动复核的直接事件。"
    entry = max(
        mapped,
        key=lambda item: (
            item.risk_score + min(item.portfolio_weight_pct, 30) + (10 if item.direction == "risk_up" else 0),
            item.evidence_count,
        ),
    )
    symbols = "、".join(entry.portfolio_symbols)
    if entry.risk_score < 60 and entry.direction != "risk_up":
        return f"最高优先事件仍为观察级：{entry.label}，映射 {symbols}。"
    return (
        f"今日优先复核：{entry.label}；映射 {symbols}（{entry.portfolio_weight_pct:.1f}%）；"
        f"价格验证：{entry.market_confirmation}。"
    )


def _invalidation_conditions(report: ScoredReport) -> tuple[str, ...]:
    ten_year = _metric_value(report, "treasury_10y")
    vix = _metric_value(report, "vix")
    vvix = _metric_value(report, "vvix")
    dxy = _metric_value(report, "dxy")
    conditions = []
    if ten_year is not None:
        conditions.append(f"10Y美债升至 {ten_year + 0.08:.2f}% 以上并维持，当前风险姿态失效。")
    if vix is not None and vvix is not None:
        conditions.append(
            f"VIX升至 {max(20.0, vix * 1.10):.1f} 且VVIX升至 {max(100.0, vvix * 1.08):.1f}，视为波动同步扩张。"
        )
    if dxy is not None:
        conditions.append(
            f"DXY升至 {dxy * 1.004:.2f} 且Nasdaq单日跌幅达到1%，在宽度指标上线前视为同步收紧代理。"
        )
    return tuple(conditions[:3])


def _metric_value(report: ScoredReport, key: str) -> float | None:
    scored = report.metrics.get(key)
    value = getattr(getattr(scored, "metric", None), "value", None)
    return float(value) if isinstance(value, (int, float)) else None


def _risk_posture(score: int) -> tuple[str, str, tuple[str, ...]]:
    if score >= 70:
        return (
            "Defensive / 防守",
            "宏观压力已形成广泛约束，风险预算应优先防守。",
            (
                "保护亏损预算，避免新增广泛高 Beta 暴露。",
                "优先复核对冲覆盖与组合中最弱的仓位。",
                "等待利率、美元或波动率至少一项转向后再增加风险。",
            ),
        )
    if score >= 55:
        return (
            "Cautious / 审慎",
            "风险信号偏高，但尚未进入全面防守状态。",
            (
                "新增仓位分批执行，避免一次性前置风险。",
                "优先选择相对强势且失效条件明确的标的。",
                "若波动率与实际利率同步加速，重新检查对冲。",
            ),
        )
    if score >= 40:
        return (
            "Neutral / 中性",
            "跨资产证据混合，当前重点是保留调整弹性。",
            (
                "维持核心仓位；市场宽度未确认前不追逐指数强势。",
                "只选择性利用回调，既定止损位保持不变。",
                "由下一步利率、美元或波动率变化决定是否扩大风险。",
            ),
        )
    return (
        "Constructive / 积极但有纪律",
        "宏观条件偏支持，但仍受事件与集中度风险约束。",
        (
            "在投资逻辑与趋势一致的方向逐步增加风险。",
            "不要因为宏观分数偏支持而放宽单股亏损上限。",
            "警惕实际利率、美元或波动率广度出现反转。",
        ),
    )


def _largest_moves(
    metrics: dict[str, ScoredMetric], history: list[dict]
) -> tuple[list[MacroBriefSignal], str]:
    ranked: list[tuple[float, MacroBriefSignal]] = []
    z_scored = 0
    for key, scale in _MOVE_SCALES.items():
        scored = metrics.get(key)
        if scored is None:
            continue
        metric = scored.metric
        if metric.status != "ok" or metric.value is None:
            continue
        move = metric.change if key in {"treasury_2y", "treasury_10y", "real_yield_10y", "credit_spread_hy"} else metric.change_pct
        if move is None:
            continue
        absolute_change = key in {"treasury_2y", "treasury_10y", "real_yield_10y", "credit_spread_hy"}
        anomaly = detect_change_anomaly(
            key, float(move), history, use_absolute_change=absolute_change
        )
        if anomaly.classification != "insufficient_history":
            z_scored += 1
        rank, annotation = _anomaly_rank_and_label(anomaly, abs(move) / scale)
        ranked.append(
            (
                rank,
                MacroBriefSignal(
                    label=metric.label,
                    value=(
                        f"Level {_format_level(float(metric.value), metric.unit, key)}"
                        f" | 日变 {_format_move(move, metric.unit, key)}"
                    ),
                    interpretation=f"{annotation}{scored.signal}",
                ),
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    method = (
        "滚动60日 Standard Z + Robust Z 双轨检测；双确认优先，单边异常标记待核实。"
        if z_scored
        else "历史样本不足20期，暂用固定冲击尺度启发式排序。"
    )
    return [item[1] for item in ranked], method


def _anomaly_rank_and_label(anomaly: AnomalyResult, fallback_rank: float) -> tuple[float, str]:
    if anomaly.classification == "insufficient_history":
        return fallback_rank, "[启发式] "
    z = anomaly.z_score or 0.0
    robust_z = anomaly.robust_z_score or 0.0
    severity = max(abs(z) / 2.0, abs(robust_z) / 2.5)
    values = f"Z {z:+.2f} / Robust Z {robust_z:+.2f}"
    if anomaly.classification == "confirmed":
        return 100.0 + severity, f"[确认异常；{values}] "
    if anomaly.classification == "robust_only":
        return 60.0 + severity, f"[Robust异常；{values}，待核实] "
    if anomaly.classification == "standard_only":
        return 50.0 + severity, f"[Standard异常；{values}，分布敏感] "
    return severity, f"[正常区间；{values}] "


def _format_move(value: float, unit: str, key: str) -> str:
    sign = "+" if value > 0 else ""
    if key in {"treasury_2y", "treasury_10y", "real_yield_10y", "credit_spread_hy"}:
        return f"{sign}{value * 100:.0f}bp"
    return f"{sign}{value:.2f}%"


def _format_level(value: float, unit: str, key: str) -> str:
    if key in {"treasury_2y", "treasury_10y", "real_yield_10y", "credit_spread_hy"}:
        return f"{value:.2f}%"
    if key in {"nasdaq", "sp500", "russell2000"}:
        return f"{value:,.2f}"
    if unit == "%":
        return f"{value:.2f}%"
    if unit:
        return f"{value:,.2f} {unit}"
    return f"{value:,.2f}"
