from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from typing import Iterable, Mapping, Sequence

from .news_monitor import NewsMonitor
from .policy_risk_monitor import PolicyRiskFactor, PolicyRiskMonitor


@dataclass(frozen=True)
class EventRiskLedgerEntry:
    event_id: str
    label: str
    direction: str
    confidence: str
    risk_score: int
    affected_assets: tuple[str, ...]
    affected_tickers: tuple[str, ...]
    portfolio_symbols: tuple[str, ...]
    portfolio_weight_pct: float
    evidence_count: int
    latest_published_at: str
    market_confirmation: str
    validation_note: str
    synthesis: str
    source_urls: tuple[str, ...] = ()
    lifecycle: str = "待跟踪"


@dataclass(frozen=True)
class EventRiskLedger:
    generated_at: str
    status: str
    summary: str
    entries: tuple[EventRiskLedgerEntry, ...]
    warnings: tuple[str, ...] = ()


def build_event_risk_ledger(
    policy_risk_monitor: PolicyRiskMonitor | None,
    news_monitor: NewsMonitor | None,
    portfolio_positions: Sequence[object] | None = None,
    metrics: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> EventRiskLedger:
    generated_at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    warnings = tuple(getattr(news_monitor, "warnings", ()) or ())
    if policy_risk_monitor is None or not policy_risk_monitor.factors:
        return EventRiskLedger(
            generated_at=generated_at,
            status="no_data",
            summary="事件风险追踪暂未形成：当前没有足够的政策、地缘或主题事件簇。",
            entries=(),
            warnings=warnings,
        )

    portfolio_index = _portfolio_index(portfolio_positions or ())
    entries = tuple(
        sorted(
            (
                _entry_from_factor(factor, portfolio_index, metrics)
                for factor in policy_risk_monitor.factors
            ),
            key=lambda item: (item.portfolio_weight_pct, item.risk_score),
            reverse=True,
        )
    )
    mapped = [entry for entry in entries if entry.portfolio_symbols]
    mapped_weight = _unique_mapped_weight(policy_risk_monitor.factors, portfolio_index)
    summary = _summary(entries, mapped, entries[0] if entries else None, mapped_weight)
    return EventRiskLedger(
        generated_at=generated_at,
        status="ok",
        summary=summary,
        entries=entries,
        warnings=warnings + tuple(policy_risk_monitor.warnings or ()),
    )


def _entry_from_factor(
    factor: PolicyRiskFactor,
    portfolio_index: dict[str, tuple[str, float]],
    metrics: Mapping[str, object] | None,
) -> EventRiskLedgerEntry:
    matched_symbols: dict[str, float] = {}
    for ticker in factor.affected_tickers:
        normalized = _normalize_symbol(ticker)
        if normalized in portfolio_index:
            symbol, weight = portfolio_index[normalized]
            matched_symbols[symbol] = max(matched_symbols.get(symbol, 0.0), weight)

    portfolio_weight = round(sum(matched_symbols.values()), 2)
    evidence = tuple(factor.evidence or ())
    latest = max((item.published_at for item in evidence), default="")
    source_urls = tuple(dict.fromkeys(item.url for item in evidence if item.url))
    synthesis = _synthesis(factor, tuple(matched_symbols), portfolio_weight)
    market_confirmation, validation_note = _market_validation(factor, metrics)
    return EventRiskLedgerEntry(
        event_id=_event_id(factor),
        label=factor.label,
        direction=factor.direction,
        confidence=factor.confidence,
        risk_score=factor.score,
        affected_assets=tuple(factor.affected_assets),
        affected_tickers=tuple(factor.affected_tickers),
        portfolio_symbols=tuple(matched_symbols),
        portfolio_weight_pct=portfolio_weight,
        evidence_count=factor.event_count,
        latest_published_at=latest,
        market_confirmation=market_confirmation,
        validation_note=validation_note,
        synthesis=synthesis,
        source_urls=source_urls,
        lifecycle=_lifecycle(factor.event_count),
    )


def _market_validation(
    factor: PolicyRiskFactor,
    metrics: Mapping[str, object] | None,
) -> tuple[str, str]:
    if not metrics:
        return (
            "待价格验证",
            "当前仅完成事件归档与组合暴露映射；尚未接入当日跨资产价格行为验证。",
        )
    if factor.direction == "mixed":
        return (
            "事件方向混合",
            "该事件簇本身同时包含风险上行与缓和信号，暂不强行给出单一价格验证结论。",
        )

    support: list[str] = []
    conflict: list[str] = []

    def add_pct(name: str, key: str, risk_up_support: float, risk_up_conflict: float) -> None:
        value = _change_pct(metrics, key)
        if value is None:
            return
        if factor.direction == "risk_down":
            if value <= risk_up_conflict:
                support.append(_fmt_pct_signal(name, value))
            elif value >= risk_up_support:
                conflict.append(_fmt_pct_signal(name, value))
        else:
            if value >= risk_up_support:
                support.append(_fmt_pct_signal(name, value))
            elif value <= risk_up_conflict:
                conflict.append(_fmt_pct_signal(name, value))

    def add_inverse_pct(name: str, key: str, risk_up_support: float, risk_up_conflict: float) -> None:
        value = _change_pct(metrics, key)
        if value is None:
            return
        if factor.direction == "risk_down":
            if value >= risk_up_conflict:
                support.append(_fmt_pct_signal(name, value))
            elif value <= risk_up_support:
                conflict.append(_fmt_pct_signal(name, value))
        else:
            if value <= risk_up_support:
                support.append(_fmt_pct_signal(name, value))
            elif value >= risk_up_conflict:
                conflict.append(_fmt_pct_signal(name, value))

    def add_yield(name: str, key: str, risk_up_support: float, risk_up_conflict: float) -> None:
        value = _change(metrics, key)
        if value is None:
            return
        if factor.direction == "risk_down":
            if value <= risk_up_conflict:
                support.append(_fmt_bp_signal(name, value))
            elif value >= risk_up_support:
                conflict.append(_fmt_bp_signal(name, value))
        else:
            if value >= risk_up_support:
                support.append(_fmt_bp_signal(name, value))
            elif value <= risk_up_conflict:
                conflict.append(_fmt_bp_signal(name, value))

    relevant = _relevant_validation_keys(factor)
    if "equities" in relevant:
        add_inverse_pct("纳指100", "nasdaq", -0.5, 0.5)
        add_inverse_pct("标普500", "sp500", -0.4, 0.4)
    if "dxy" in relevant:
        add_pct("DXY", "dxy", 0.2, -0.2)
    if "rates" in relevant:
        add_yield("10Y美债", "treasury_10y", 0.03, -0.03)
    if "oil" in relevant:
        add_pct("WTI原油", "oil", 1.0, -1.0)
    if "gold" in relevant:
        add_pct("黄金", "gold", 0.4, -0.4)
    if "vol" in relevant:
        add_pct("VIX", "vix", 3.0, -3.0)
        add_pct("MOVE", "move", 3.0, -3.0)
    if "credit" in relevant:
        add_pct("高收益利差", "credit_spread_hy", 1.0, -1.0)

    if not support and not conflict:
        return (
            "缺少价格验证",
            "相关价格指标暂不可用或波动幅度未达到验证阈值；该事件仍需结合后续价格行为复核。",
        )

    label = _validation_label(len(support), len(conflict))
    note_parts: list[str] = []
    if support:
        note_parts.append("支持信号：" + "、".join(support[:4]))
    if conflict:
        note_parts.append("相反信号：" + "、".join(conflict[:4]))
    note_parts.append("该层只验证价格行为是否与事件方向同向，不构成因果确认。")
    return label, "；".join(note_parts)


def _relevant_validation_keys(factor: PolicyRiskFactor) -> set[str]:
    base = {"vol"}
    if factor.key in {"tariff_trade", "ai_semiconductor_policy"}:
        return base | {"equities", "dxy", "rates"}
    if factor.key == "geopolitical_war":
        return base | {"oil", "gold", "dxy"}
    if factor.key == "energy_oil":
        return base | {"oil", "rates", "gold"}
    if factor.key == "rates_fiscal_regulation":
        return base | {"equities", "dxy", "rates", "gold", "credit"}
    return base | {"equities", "dxy", "rates"}


def _validation_label(support_count: int, conflict_count: int) -> str:
    if support_count >= 2 and conflict_count <= 1:
        return "价格行为初步确认"
    if support_count >= 1 and conflict_count == 0:
        return "价格行为部分确认"
    if conflict_count >= 2 and support_count == 0:
        return "价格行为暂未确认"
    if support_count and conflict_count:
        return "价格信号分歧"
    return "缺少价格验证"


def _metric(metrics: Mapping[str, object], key: str) -> object | None:
    value = metrics.get(key)
    if isinstance(value, Mapping):
        return value
    return value


def _change_pct(metrics: Mapping[str, object], key: str) -> float | None:
    return _field_number(_metric(metrics, key), "change_pct")


def _change(metrics: Mapping[str, object], key: str) -> float | None:
    return _field_number(_metric(metrics, key), "change")


def _field_number(metric: object | None, field: str) -> float | None:
    if metric is None:
        return None
    value = metric.get(field) if isinstance(metric, Mapping) else getattr(metric, field, None)
    return _safe_float(value)


def _fmt_pct_signal(name: str, value: float) -> str:
    return f"{name}{value:+.2f}%"


def _fmt_bp_signal(name: str, value: float) -> str:
    return f"{name}{value * 100:+.0f}bp"


def _portfolio_index(positions: Iterable[object]) -> dict[str, tuple[str, float]]:
    total_value = sum(
        value
        for position in positions
        for value in (_safe_float(getattr(position, "market_value_gbp", None)),)
        if value is not None and value > 0
    )
    index: dict[str, tuple[str, float]] = {}
    for position in positions:
        raw_symbol = str(getattr(position, "symbol", "") or "").strip()
        if not raw_symbol:
            continue
        weight = _safe_float(getattr(position, "weight_pct", None))
        if weight is None:
            value = _safe_float(getattr(position, "market_value_gbp", None))
            weight = (value / total_value * 100) if value is not None and total_value > 0 else 0.0
        index[_normalize_symbol(raw_symbol)] = (raw_symbol.upper(), round(weight, 2))
    return index


def _normalize_symbol(symbol: str) -> str:
    text = symbol.upper().strip()
    if not text:
        return ""
    if text.startswith("^"):
        text = text[1:]
    return text.split(".")[0]


def _event_id(factor: PolicyRiskFactor) -> str:
    seed = "|".join(
        (
            factor.key,
            factor.direction,
            str(factor.score),
            "|".join(item.title for item in factor.evidence[:3]),
        )
    )
    return sha1(seed.encode("utf-8")).hexdigest()[:12]


def _lifecycle(evidence_count: int) -> str:
    if evidence_count >= 2:
        return "延续事件"
    if evidence_count == 1:
        return "新事件"
    return "待跟踪"


def _summary(
    entries: tuple[EventRiskLedgerEntry, ...],
    mapped: list[EventRiskLedgerEntry],
    top: EventRiskLedgerEntry | None,
    mapped_weight: float,
) -> str:
    if not entries:
        return "事件风险追踪暂未形成。"
    if mapped:
        top_label = top.label if top else mapped[0].label
        return (
            f"事件风险追踪识别{len(entries)}个事件簇，其中{len(mapped)}个直接映射到当前持仓，"
            f"映射权重约{mapped_weight:.1f}%。当前最需要人工复核的是“{top_label}”。"
        )
    return (
        f"事件风险追踪识别{len(entries)}个事件簇，但暂未直接映射到当前持仓；"
        "仍需观察其是否通过利率、美元、能源或指数风险偏好间接传导。"
    )


def _unique_mapped_weight(
    factors: tuple[PolicyRiskFactor, ...],
    portfolio_index: dict[str, tuple[str, float]],
) -> float:
    symbol_weights: dict[str, float] = {}
    for factor in factors:
        for ticker in factor.affected_tickers:
            normalized = _normalize_symbol(ticker)
            if normalized in portfolio_index:
                symbol, weight = portfolio_index[normalized]
                symbol_weights[symbol] = max(symbol_weights.get(symbol, 0.0), weight)
    return round(sum(symbol_weights.values()), 2)


def _synthesis(factor: PolicyRiskFactor, symbols: tuple[str, ...], weight: float) -> str:
    direction = {
        "risk_up": "风险上行",
        "risk_down": "风险缓和",
        "mixed": "信号分歧",
    }.get(factor.direction, factor.direction)
    if symbols:
        names = "、".join(symbols[:8])
        return (
            f"{factor.label}当前为{direction}，与组合持仓{names}存在直接或主题映射，"
            f"相关权重约{weight:.1f}%。该结论应结合原文、价格确认和仓位集中度复核。"
        )
    assets = "、".join(factor.affected_assets[:4]) if factor.affected_assets else "相关资产"
    return (
        f"{factor.label}当前为{direction}，主要影响{assets}。当前未直接映射到持仓，"
        "但可能通过宏观叙事和风险偏好间接影响组合。"
    )


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None
