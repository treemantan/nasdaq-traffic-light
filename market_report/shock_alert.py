from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ShockTrigger:
    label: str
    value_text: str
    threshold_text: str
    severity: int
    note: str


@dataclass(frozen=True)
class MarketShockAssessment:
    triggered: bool
    level: str
    severity_score: int
    subject_suffix: str
    summary: str
    triggers: list[ShockTrigger]
    actions: list[str]


def assess_market_shock(payload: dict[str, Any]) -> MarketShockAssessment:
    nasdaq_pct = _change_pct(payload, "nasdaq")
    sp500_pct = _change_pct(payload, "sp500")
    russell_pct = _change_pct(payload, "russell2000")
    vix_pct = _change_pct(payload, "vix")
    vvix_pct = _change_pct(payload, "vvix")
    dxy_pct = _change_pct(payload, "dxy")
    ten_year = _value(payload, "treasury_10y")
    ten_year_change = _change(payload, "treasury_10y")

    triggers: list[ShockTrigger] = []
    _add_downside_trigger(
        triggers,
        "纳斯达克100",
        nasdaq_pct,
        warning=-2.5,
        critical=-4.0,
        warning_severity=25,
        critical_severity=35,
        note="高久期成长资产出现单日区间突破，新增仓位应等待波动率回落或价格重新确认。",
    )
    _add_downside_trigger(
        triggers,
        "标普500",
        sp500_pct,
        warning=-2.0,
        critical=-3.0,
        warning_severity=24,
        critical_severity=32,
        note="大盘层面进入明显risk-off，说明回撤不是单一主题内部波动。",
    )
    _add_downside_trigger(
        triggers,
        "罗素2000",
        russell_pct,
        warning=-3.0,
        critical=-4.0,
        warning_severity=14,
        critical_severity=20,
        note="小盘同步下跌意味着市场宽度转弱，风险预算可能正在收缩。",
    )
    _add_upside_trigger(
        triggers,
        "VIX",
        vix_pct,
        warning=15.0,
        critical=25.0,
        warning_severity=20,
        critical_severity=28,
        note="隐含波动率快速扩张，盘中卖压或对冲需求正在升温。",
    )
    _add_upside_trigger(
        triggers,
        "VVIX",
        vvix_pct,
        warning=10.0,
        critical=15.0,
        warning_severity=14,
        critical_severity=20,
        note="波动率二阶风险被重新定价，尾部保护需求抬升。",
    )

    if dxy_pct is not None and nasdaq_pct is not None and dxy_pct >= 0.4 and nasdaq_pct < 0:
        triggers.append(
            ShockTrigger(
                "美元与成长股压力共振",
                f"DXY {dxy_pct:+.2f}% / NDX {nasdaq_pct:+.2f}%",
                "DXY >= +0.40% 且 NDX < 0",
                10,
                "美元走强会收紧全球金融条件，对高估值成长资产形成额外约束。",
            )
        )

    if (
        ten_year is not None
        and ten_year_change is not None
        and nasdaq_pct is not None
        and ten_year >= 4.5
        and ten_year_change >= 0.03
        and nasdaq_pct < 0
    ):
        triggers.append(
            ShockTrigger(
                "长端利率与成长股压力共振",
                f"10Y {ten_year:.3f}% / {ten_year_change:+.3f}%",
                "10Y >= 4.50% 且日变动 >= +3bp",
                10,
                "长端收益率位于敏感区间并继续上行，高久期资产贴现率压力放大。",
            )
        )

    severity = min(100, sum(item.severity for item in triggers))
    hard_trigger = any(item.severity >= 20 for item in triggers)
    triggered = bool(triggers) and (hard_trigger or severity >= 30)
    level = "critical" if severity >= 60 else "high" if severity >= 35 else "watch"
    if not triggered:
        return MarketShockAssessment(
            False,
            "normal",
            severity,
            "No shock",
            "当前尚未触发紧急市场冲击条件。",
            triggers,
            [],
        )

    subject_bits = []
    if nasdaq_pct is not None:
        subject_bits.append(f"NDX {nasdaq_pct:+.2f}%")
    if vix_pct is not None:
        subject_bits.append(f"VIX {vix_pct:+.2f}%")
    subject_suffix = ", ".join(subject_bits) if subject_bits else f"severity {severity}"
    summary = (
        "权益指数单日下跌与波动率扩张同时出现，市场已不再是普通震荡环境。"
        "在冲击窗口内，新增仓位应从“寻找机会”切换为“先确认风险是否扩散”。"
    )
    actions = [
        "暂停追涨式新增仓位，等待指数跌幅、VIX/VVIX和美元/利率共振关系重新稳定。",
        "优先复核已有红色回撤或高beta持仓，区分基本面破坏、估值回撤和流动性冲击。",
        "若必须调仓，先降低节奏和单笔暴露，避免在波动率扩张初期一次性完成建仓。",
    ]
    return MarketShockAssessment(True, level, severity, subject_suffix, summary, triggers, actions)


def should_send_shock_alert(
    assessment: MarketShockAssessment,
    state: dict[str, Any],
    report_date: str,
    *,
    escalation_step: int = 15,
) -> bool:
    if not assessment.triggered:
        return False
    record = (state.get("dates") or {}).get(report_date)
    if not isinstance(record, dict):
        return True
    previous = _safe_int(record.get("max_severity"))
    return assessment.severity_score >= previous + escalation_step


def update_shock_state(
    state: dict[str, Any],
    report_date: str,
    assessment: MarketShockAssessment,
    *,
    sent_at: datetime | None = None,
) -> dict[str, Any]:
    dates = dict(state.get("dates") or {})
    existing = dates.get(report_date) if isinstance(dates.get(report_date), dict) else {}
    max_severity = max(_safe_int(existing.get("max_severity")), assessment.severity_score)
    sends = _safe_int(existing.get("send_count")) + 1
    sent_at = sent_at or datetime.now(timezone.utc)
    dates[report_date] = {
        "max_severity": max_severity,
        "last_level": assessment.level,
        "last_subject_suffix": assessment.subject_suffix,
        "last_sent_at": sent_at.isoformat(),
        "send_count": sends,
    }
    return {"dates": dates}


def metric_line(payload: dict[str, Any], key: str) -> str:
    metric = _metric(payload, key)
    value = metric.get("value")
    pct = _change_pct(payload, key)
    label = metric.get("label") or key
    if isinstance(value, (int, float)) and pct is not None:
        return f"{label}: {_fmt_number(value)} / {pct:+.2f}%"
    if pct is not None:
        return f"{label}: {pct:+.2f}%"
    return f"{label}: N/A"


def _add_downside_trigger(
    triggers: list[ShockTrigger],
    label: str,
    pct: float | None,
    *,
    warning: float,
    critical: float,
    warning_severity: int,
    critical_severity: int,
    note: str,
) -> None:
    if pct is None:
        return
    if pct <= critical:
        triggers.append(ShockTrigger(label, f"{pct:+.2f}%", f"<= {critical:.1f}%", critical_severity, note))
    elif pct <= warning:
        triggers.append(ShockTrigger(label, f"{pct:+.2f}%", f"<= {warning:.1f}%", warning_severity, note))


def _add_upside_trigger(
    triggers: list[ShockTrigger],
    label: str,
    pct: float | None,
    *,
    warning: float,
    critical: float,
    warning_severity: int,
    critical_severity: int,
    note: str,
) -> None:
    if pct is None:
        return
    if pct >= critical:
        triggers.append(ShockTrigger(label, f"{pct:+.2f}%", f">= +{critical:.1f}%", critical_severity, note))
    elif pct >= warning:
        triggers.append(ShockTrigger(label, f"{pct:+.2f}%", f">= +{warning:.1f}%", warning_severity, note))


def _metric(payload: dict[str, Any], key: str) -> dict[str, Any]:
    scored = (payload.get("metrics") or {}).get(key) or {}
    metric = scored.get("metric") or {}
    return metric if isinstance(metric, dict) else {}


def _value(payload: dict[str, Any], key: str) -> float | None:
    value = _metric(payload, key).get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _previous_value(payload: dict[str, Any], key: str) -> float | None:
    value = _metric(payload, key).get("previous_value")
    return float(value) if isinstance(value, (int, float)) else None


def _change(payload: dict[str, Any], key: str) -> float | None:
    metric = _metric(payload, key)
    raw = metric.get("change")
    if isinstance(raw, (int, float)):
        return float(raw)
    value = _value(payload, key)
    previous = _previous_value(payload, key)
    if value is None or previous is None:
        return None
    return value - previous


def _change_pct(payload: dict[str, Any], key: str) -> float | None:
    metric = _metric(payload, key)
    raw = metric.get("change_pct")
    if isinstance(raw, (int, float)):
        return float(raw)
    value = _value(payload, key)
    previous = _previous_value(payload, key)
    if value is None or previous in (None, 0):
        return None
    return (value / previous - 1) * 100


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fmt_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.4f}".rstrip("0").rstrip(".")
