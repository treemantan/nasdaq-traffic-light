from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .news_monitor import NewsEvent, NewsMonitor


@dataclass(frozen=True)
class PolicyRiskEvidence:
    title: str
    source: str
    published_at: str
    url: str
    direction: str
    impact: str


@dataclass(frozen=True)
class PolicyRiskFactor:
    key: str
    label: str
    score: int
    direction: str
    confidence: str
    summary: str
    affected_assets: tuple[str, ...]
    affected_tickers: tuple[str, ...]
    event_count: int
    evidence: tuple[PolicyRiskEvidence, ...]


@dataclass(frozen=True)
class PolicyRiskMonitor:
    generated_at: str
    status: str
    overall_score: int
    label: str
    summary: str
    factors: tuple[PolicyRiskFactor, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FactorDefinition:
    key: str
    label: str
    keywords: tuple[str, ...]
    affected_assets: tuple[str, ...]
    mapped_tickers: tuple[str, ...]


FACTOR_DEFINITIONS = (
    _FactorDefinition(
        key="tariff_trade",
        label="关税与贸易政策",
        keywords=(
            "tariff",
            "trade",
            "export",
            "export control",
            "restriction",
            "exemption",
            "import",
            "customs",
            "sanction",
            "china",
            "supply chain",
            "retaliat",
        ),
        affected_assets=("Nasdaq 100", "Semiconductors", "USD", "China/Korea exposure"),
        mapped_tickers=("NVDA", "AVGO", "AMD", "MU", "TSM", "ASML", "QCOM"),
    ),
    _FactorDefinition(
        key="ai_semiconductor_policy",
        label="AI与半导体政策",
        keywords=(
            "artificial intelligence",
            " ai ",
            "semiconductor",
            "chip",
            "gpu",
            "data center",
            "datacenter",
            "nvidia",
            "memory",
            "hbm",
            "accelerator",
            "export control",
        ),
        affected_assets=("AI capex chain", "Semiconductors", "Nasdaq 100", "High-duration growth"),
        mapped_tickers=("NVDA", "AVGO", "AMD", "MU", "TSM", "ASML", "QCOM"),
    ),
    _FactorDefinition(
        key="geopolitical_war",
        label="地缘冲突与战争风险",
        keywords=(
            "war",
            "missile",
            "military",
            "russia",
            "ukraine",
            "iran",
            "israel",
            "middle east",
            "nato",
            "ceasefire",
            "defense",
            "defence",
        ),
        affected_assets=("Oil", "Defense", "Europe risk premium", "USD"),
        mapped_tickers=("DFNG.L", "DFND.L", "WDEF.L", "NATO.L"),
    ),
    _FactorDefinition(
        key="energy_oil",
        label="能源与油价风险",
        keywords=("oil", "energy", "gas", "opec", "drilling", "crude", "pipeline"),
        affected_assets=("Oil", "Inflation breakevens", "Airlines", "Consumer discretionary"),
        mapped_tickers=(),
    ),
    _FactorDefinition(
        key="rates_fiscal_regulation",
        label="财政、利率与监管压力",
        keywords=(
            "federal reserve",
            "fed",
            "treasury",
            "deficit",
            "debt",
            "fiscal",
            "tax",
            "regulation",
            "dollar",
            "interest rate",
        ),
        affected_assets=("10Y yield", "DXY", "Growth equities", "Gold"),
        mapped_tickers=("QQQ", "SPY", "TLT", "GLD"),
    ),
)

NEGATIVE_TERMS = (
    "tariff",
    "sanction",
    "restrict",
    "ban",
    "probe",
    "investigation",
    "threat",
    "uncertainty",
    "retaliat",
    "export control",
    "war",
    "missile",
    "attack",
)
POSITIVE_TERMS = (
    "deal",
    "agreement",
    "approve",
    "support",
    "subsid",
    "investment",
    "relief",
    "exempt",
    "cut tax",
    "ceasefire",
)


def build_policy_risk_monitor(news_monitor: NewsMonitor | None, now: datetime | None = None) -> PolicyRiskMonitor:
    generated_at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    if news_monitor is None:
        return PolicyRiskMonitor(
            generated_at=generated_at,
            status="no_data",
            overall_score=0,
            label="无可用新闻",
            summary="政策事件风险监控暂无新闻输入，主报告仍以市场价格和宏观数据为准。",
            factors=(),
            warnings=("新闻监控模块不可用，政策风险分暂不生成。",),
        )

    if not news_monitor.events:
        return PolicyRiskMonitor(
            generated_at=generated_at,
            status="no_data",
            overall_score=0,
            label="暂无可量化信号",
            summary="当前新闻流中暂无可量化的政策、关税、地缘或监管事件信号。",
            factors=(),
            warnings=tuple(news_monitor.warnings),
        )

    factors = tuple(
        factor
        for definition in FACTOR_DEFINITIONS
        for factor in (_score_factor(definition, news_monitor.events),)
        if factor is not None
    )
    if not factors:
        return PolicyRiskMonitor(
            generated_at=generated_at,
            status="no_data",
            overall_score=0,
            label="暂无可量化信号",
            summary="新闻流存在事件，但暂未匹配到政策、贸易、地缘、能源或利率监管风险因子。",
            factors=(),
            warnings=tuple(news_monitor.warnings),
        )

    factors = tuple(sorted(factors, key=lambda item: item.score, reverse=True))
    top_scores = [factor.score for factor in factors[:3]]
    overall = _clamp(round(max(top_scores) * 0.6 + (sum(top_scores) / len(top_scores)) * 0.4), 0, 100)
    if news_monitor.warnings and overall > 85:
        overall = 85
    top_labels = "、".join(factor.label for factor in factors[:3])
    label = _overall_label(overall)
    summary = (
        f"Policy risk monitor: 当前政策/地缘事件风险为{label}，主要来自{top_labels}。"
        "该层基于新闻标题、来源类型、主题和ticker映射进行规则化聚合，用于提高新闻板块的信息密度，不能替代人工阅读原文。"
    )
    return PolicyRiskMonitor(
        generated_at=generated_at,
        status="ok",
        overall_score=overall,
        label=label,
        summary=summary,
        factors=factors,
        warnings=tuple(news_monitor.warnings),
    )


def _score_factor(definition: _FactorDefinition, events: tuple[NewsEvent, ...]) -> PolicyRiskFactor | None:
    matched = [event for event in events if _matches_factor(definition, event)]
    if not matched:
        return None

    event_scores = []
    risk_up = 0
    risk_down = 0
    high_confidence = 0
    primary_sources = 0
    tickers: set[str] = set(definition.mapped_tickers)
    for event in matched:
        score = _event_score(event)
        event_scores.append(score)
        direction = _event_direction(event)
        if direction == "risk_up":
            risk_up += 1
        elif direction == "risk_down":
            risk_down += 1
        if _is_high_confidence(event):
            high_confidence += 1
        if _is_primary_source(event):
            primary_sources += 1
        tickers.update(ticker.upper() for ticker in event.tickers)

    if risk_up and risk_down:
        direction = "mixed"
    elif risk_up:
        direction = "risk_up"
    elif risk_down:
        direction = "risk_down"
    else:
        direction = "neutral"
    confidence = "high" if high_confidence and len(matched) >= 2 else "medium" if high_confidence or len(matched) >= 2 else "low"
    score = _factor_score(event_scores, matched, tickers, confidence, primary_sources)
    summary = _factor_summary(definition.label, score, direction, len(matched))
    evidence = tuple(_to_evidence(event) for event in matched[:4])
    return PolicyRiskFactor(
        key=definition.key,
        label=definition.label,
        score=score,
        direction=direction,
        confidence=confidence,
        summary=summary,
        affected_assets=definition.affected_assets,
        affected_tickers=tuple(sorted(tickers)),
        event_count=len(matched),
        evidence=evidence,
    )


def _matches_factor(definition: _FactorDefinition, event: NewsEvent) -> bool:
    haystack = " ".join(
        [
            event.title,
            event.original_title,
            " ".join(event.themes),
            " ".join(event.tickers),
            " ".join(event.entities),
        ]
    ).lower()
    return any(keyword in haystack for keyword in definition.keywords)


def _event_score(event: NewsEvent) -> int:
    impact = event.impact.lower()
    if "高" in event.impact or "high" in impact:
        base = 42
    elif "低" in event.impact or "low" in impact:
        base = 8
    else:
        base = 20
    if _event_direction(event) == "mixed":
        base = round(base * 0.8)
    if _is_high_confidence(event):
        base += 4
    if _is_primary_source(event):
        base += 4
    return base


def _factor_score(
    event_scores: list[int],
    matched: list[NewsEvent],
    tickers: set[str],
    confidence: str,
    primary_sources: int,
) -> int:
    ordered = sorted(event_scores, reverse=True)
    top_event = ordered[0]
    additional_events = min(round(sum(ordered[1:]) * 0.35), 26)
    evidence_breadth = min(len(matched), 6) * 3
    ticker_breadth = min(len(tickers), 8)
    raw_score = top_event + additional_events + evidence_breadth + ticker_breadth
    cap = {"low": 55, "medium": 78, "high": 88}.get(confidence, 78)
    if confidence == "high" and primary_sources >= 2 and len(matched) >= 3:
        cap = 94
    return _clamp(raw_score, 0, cap)


def _event_direction(event: NewsEvent) -> str:
    direction = event.direction.lower()
    text = f"{event.title} {event.original_title}".lower()
    negative_terms = sum(term in text for term in NEGATIVE_TERMS)
    positive_terms = sum(term in text for term in POSITIVE_TERMS)
    if "risk_up" in direction or "negative" in direction or "风险溢价上行" in event.direction or "偏紧缩" in event.direction:
        return "risk_up"
    if "risk_down" in direction or "positive" in direction or "缓和" in event.direction or "支持" in event.direction:
        return "risk_down"
    if negative_terms > positive_terms:
        return "risk_up"
    if positive_terms > negative_terms:
        return "risk_down"
    return "mixed" if negative_terms and positive_terms else "neutral"


def _is_high_confidence(event: NewsEvent) -> bool:
    confidence = event.confidence.lower()
    return "高" in event.confidence or "high" in confidence


def _is_primary_source(event: NewsEvent) -> bool:
    source_type = event.source_type.lower()
    return any(term in source_type for term in ("official", "primary")) or "原文" in event.source_type


def _to_evidence(event: NewsEvent) -> PolicyRiskEvidence:
    return PolicyRiskEvidence(
        title=event.title,
        source=event.source,
        published_at=event.published_at,
        url=event.url,
        direction=event.direction,
        impact=event.impact,
    )


def _factor_summary(label: str, score: int, direction: str, event_count: int) -> str:
    direction_text = {
        "risk_up": "风险溢价上行",
        "risk_down": "风险溢价缓和",
        "mixed": "信号分歧",
        "neutral": "方向待确认",
    }.get(direction, "方向待确认")
    return f"{label}因子分数{score}/100，方向为{direction_text}，匹配{event_count}条相关新闻。"


def _overall_label(score: int) -> str:
    if score >= 75:
        return "高"
    if score >= 60:
        return "中等偏高"
    if score >= 35:
        return "中性偏低"
    return "低"


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))
