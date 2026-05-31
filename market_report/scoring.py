from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .data_sources import MarketMetric, MarketSnapshot
from .etf_monitor import ETFMonitor
from .news_monitor import NewsMonitor
from .time_utils import format_timestamp, timezone_label


@dataclass(frozen=True)
class ScoredMetric:
    metric: MarketMetric
    score: int
    signal: str
    note: str


@dataclass(frozen=True)
class RegimeAssessment:
    name: str
    label: str
    liquidity_regime: str
    yield_driver: str
    confidence: str
    confidence_score: int
    consistency: str
    summary: str
    knowns: list[str]
    unknowns: list[str]


@dataclass(frozen=True)
class IronCondorAssessment:
    score: int
    label: str
    color: str
    summary: str
    positives: list[str]
    warnings: list[str]
    blockers: list[str]


@dataclass(frozen=True)
class ScoredReport:
    report_date: str
    fetched_at: str
    fetched_timezone: str
    overall_score: int
    light_label: str
    light_color: str
    headline: str
    metrics: dict[str, ScoredMetric]
    weights: dict[str, float]
    summary: str
    risks: list[str]
    action: str
    regime: RegimeAssessment
    iron_condor: IronCondorAssessment
    etf_monitor: ETFMonitor | None
    data_warnings: list[str]
    data_quality: str
    data_health: dict[str, int]
    news_monitor: NewsMonitor | None = None
    previous_regime: str | None = None
    regime_transition: str = "暂无可比历史叙事。"


def score_snapshot(
    snapshot: MarketSnapshot,
    weights: dict[str, float] | None = None,
    previous_regime: str | None = None,
    report_timezone: str = "America/New_York",
    etf_monitor: ETFMonitor | None = None,
    news_monitor: NewsMonitor | None = None,
) -> ScoredReport:
    scored_metrics = {key: _score_metric(key, metric, snapshot.metrics) for key, metric in snapshot.metrics.items()}
    adaptive_weights = _adaptive_weights(snapshot.metrics)
    overall = _nonlinear_score(scored_metrics, adaptive_weights, snapshot.metrics)
    light_label, light_color, headline = _light(overall)
    health = _data_health(snapshot.metrics)
    regime = _infer_regime(snapshot.metrics, health)
    iron_condor = _iron_condor_filter(snapshot.metrics)
    data_warnings = list(snapshot.warnings)
    data_quality = _data_quality(health)
    transition = _regime_transition(previous_regime, regime.name)

    return ScoredReport(
        report_date=snapshot.as_of.isoformat(),
        fetched_at=_format_timestamp(snapshot.fetched_at, report_timezone),
        fetched_timezone=_timezone_label(report_timezone),
        overall_score=overall,
        light_label=light_label,
        light_color=light_color,
        headline=headline,
        metrics=scored_metrics,
        weights=adaptive_weights,
        summary=_build_summary(snapshot.metrics, regime, health),
        risks=_build_risks(snapshot.metrics, regime, health),
        action=_build_action(overall, regime, health),
        regime=regime,
        iron_condor=iron_condor,
        etf_monitor=etf_monitor,
        news_monitor=news_monitor,
        data_warnings=data_warnings,
        data_quality=data_quality,
        data_health=health,
        previous_regime=previous_regime,
        regime_transition=transition,
    )


def _format_timestamp(timestamp: datetime, timezone_name: str) -> str:
    return format_timestamp(timestamp, timezone_name)


def _timezone_label(timezone_name: str) -> str:
    return timezone_label(timezone_name)


def _score_metric(key: str, metric: MarketMetric, metrics: dict[str, MarketMetric]) -> ScoredMetric:
    if metric.value is None or metric.status != "ok":
        return ScoredMetric(metric, 62 if metric.importance == "core" else 50, "数据待核验", "该指标暂不进入核心定价判断，报告已在数据健康度中披露。")
    if metric.freshness == "cache":
        cache_note = "该指标使用本地缓存，方向判断可参考，但不应视为实时市场信号。"
        return ScoredMetric(metric, 55, "缓存数据", cache_note)
    if key in {"nasdaq", "sp500", "russell2000"}:
        return _score_equity(metric, metrics)
    if key in {"vix", "vvix"}:
        return _score_vol(metric)
    if key == "cnn_fear_greed":
        return _score_cnn_fear_greed(metric)
    if key == "naaim_exposure":
        return _score_naaim_exposure(metric)
    if key in {"treasury_2y", "treasury_10y", "real_yield_10y"}:
        return _score_yield(metric)
    if key == "curve_2s10s":
        return _score_curve(metric)
    if key in {"dxy", "gbpusd", "usdjpy"}:
        return _score_fx(metric)
    if key in {"gold", "oil"}:
        return _score_commodity(metric, metrics)
    if key in {"move", "credit_spread_hy"}:
        return _score_stress(metric)
    if key in {"fed_balance_sheet", "rrp", "tga", "bank_reserves"}:
        return _score_liquidity_metric(metric)
    return ScoredMetric(metric, 50, "观察", "该指标作为辅助交叉验证信号。")


def _score_equity(metric: MarketMetric, metrics: dict[str, MarketMetric]) -> ScoredMetric:
    pct = metric.change_pct or 0
    ten_year = _value(metrics, "treasury_10y")
    dxy_pct = _change_pct(metrics, "dxy")
    pressure = 0
    if ten_year is not None and ten_year >= 4.5:
        pressure += 12
    if dxy_pct is not None and dxy_pct > 0.35:
        pressure += 8
    score = 55 - pct * 14 + pressure
    if pct < -1 and pressure > 0:
        return ScoredMetric(metric, _clamp(score), "高久期资产承压", "权益回撤与美元或长端利率上行相互印证，风险偏好出现降温迹象。")
    if pct > 1 and pressure > 0:
        return ScoredMetric(metric, _clamp(score), "流动性韧性", "权益上涨但利率或美元仍偏强，当前更接近流动性或主题交易驱动。")
    if pct > 0.5:
        return ScoredMetric(metric, _clamp(score), "风险偏好修复", "权益端延续修复，但仍需观察利率与美元是否配合。")
    return ScoredMetric(metric, _clamp(score), "区间震荡", "权益端方向性有限，宏观约束尚未形成单边叙事。")


def _score_vol(metric: MarketMetric) -> ScoredMetric:
    value = metric.value or 0
    pct = metric.change_pct or 0
    if metric.key == "vvix":
        score = _clamp(_logistic(value, 105, 0.08) * 100 + max(0, pct) * 1.2 - max(0, -pct) * 0.5)
        if value >= 120:
            if pct < 0:
                return ScoredMetric(metric, score, "尾部风险高位回落", "VVIX仍处于高位区间，但边际回落显示期权市场对波动率二阶风险的追价有所降温。")
            return ScoredMetric(metric, score, "尾部风险溢价抬升", "VVIX处于高位区间，说明市场正在为VIX自身波动和尾部对冲支付更高溢价。")
        if value >= 105:
            if pct < -1:
                return ScoredMetric(metric, score, "尾部风险边际缓和", "VVIX从偏紧区间回落，显示波动率市场的尾部保护需求有所降温，但尚未回到低压状态。")
            return ScoredMetric(metric, score, "尾部风险偏紧", "VVIX位于偏紧区间，期权市场仍保留一定尾部风险溢价。")
        if pct <= -1:
            return ScoredMetric(metric, score, "尾部保护需求回落", "VVIX处于常态区间并边际下行，说明波动率曲面的压力正在缓和，风险偏好有一定修复。")
        if pct >= 5:
            return ScoredMetric(metric, score, "尾部保护需求升温", "VVIX在常态区间内快速上行，边际变化提示市场开始增加对波动率冲击的保护。")
        if value < 85:
            return ScoredMetric(metric, score, "尾部风险定价偏低", "VVIX处于偏低区间，市场对波动率二阶风险的定价较为克制。")
        return ScoredMetric(metric, score, "尾部风险中性", "VVIX位于常态区间，当前更像波动率风险的正常再定价，而非系统性压力。")

    score = _clamp(_logistic(value, 20, 0.35) * 100 + max(0, pct) * 1.6 - max(0, -pct) * 0.6)
    if value < 15 and pct <= 5:
        return ScoredMetric(metric, score, "低波动压缩", "VIX处于低位，市场对短期尾部风险的定价仍然有限。")
    if pct >= 8:
        return ScoredMetric(metric, score, "波动率上行", "VIX的边际变化比绝对水平更重要，避险需求已有抬头。")
    if value >= 25:
        if pct < 0:
            return ScoredMetric(metric, score, "波动高位回落", "VIX仍处于偏高区间，但边际下行显示避险需求正在从高位释放。")
        return ScoredMetric(metric, score, "宏观风险释放", "VIX处于高位，市场正在提高权益风险溢价要求。")
    if pct <= -5:
        return ScoredMetric(metric, score, "波动率回落", "VIX边际回落，说明短期避险需求有所缓和，但仍需与美元、利率和信用条件交叉验证。")
    return ScoredMetric(metric, score, "波动温和", "VIX位于常态区间，尚未构成系统性压力。")


def _score_cnn_fear_greed(metric: MarketMetric) -> ScoredMetric:
    value = metric.value or 0
    change = metric.change or 0
    if value < 25:
        return ScoredMetric(metric, 78, "极端恐惧", "CNN情绪指标处于极端恐惧区间，风险偏好显著降温，但也可能反映短期过度避险定价。")
    if value < 45:
        return ScoredMetric(metric, 62, "恐惧区间", "市场情绪仍偏谨慎，需要结合VIX、信用利差与美元确认是否演化为宏观risk-off。")
    if value < 55:
        return ScoredMetric(metric, 45, "情绪中性", "情绪指标处于中性区间，对宏观regime的边际解释力有限。")
    if value < 75:
        score = 58 + max(0, change) * 0.4
        return ScoredMetric(metric, _clamp(score), "贪婪区间", "市场风险偏好较强，但尚未单独构成泡沫化信号，需观察利率与美元是否形成约束。")
    return ScoredMetric(metric, 76, "极端贪婪", "情绪指标进入极端贪婪区间，说明风险资产定价对负面宏观扰动的缓冲垫下降。")


def _score_naaim_exposure(metric: MarketMetric) -> ScoredMetric:
    value = metric.value or 0
    change = metric.change or 0
    if value >= 100:
        return ScoredMetric(metric, 74, "机构仓位拥挤", "NAAIM显示主动管理人平均权益敞口接近或超过满仓，风险偏好较强但仓位缓冲下降。")
    if value >= 80:
        if change < -10:
            return ScoredMetric(metric, 60, "高仓位降敞口", "主动管理人权益敞口仍偏高，但周度降幅较大，说明机构风险偏好开始边际降温。")
        return ScoredMetric(metric, 64, "机构仓位偏高", "主动管理人权益敞口处于偏高区间，市场上行需要继续依赖流动性和盈利叙事配合。")
    if value >= 55:
        if change < -10:
            return ScoredMetric(metric, 55, "机构仓位降温", "机构权益敞口从高位回落，尚未转向防御，但风险预算已有收敛迹象。")
        return ScoredMetric(metric, 48, "机构仓位中性偏多", "主动管理人权益敞口位于中性偏多区间，对风险偏好的边际解释力温和。")
    if value >= 30:
        return ScoredMetric(metric, 58, "机构仓位谨慎", "主动管理人权益敞口偏低，说明机构风险预算较为克制。")
    return ScoredMetric(metric, 68, "机构仓位防御", "主动管理人权益敞口处于防御区间，反映机构层面对权益风险的规避。")


def _score_yield(metric: MarketMetric) -> ScoredMetric:
    value = metric.value or 0
    change = metric.change or 0
    center = 2.0 if metric.key == "real_yield_10y" else 4.5 if metric.key == "treasury_10y" else 4.3
    score = _clamp(_logistic(value, center, 2.4) * 100 + max(0, change) * 8)
    if metric.key == "real_yield_10y" and value >= 2:
        return ScoredMetric(metric, score, "实际利率约束", "实际利率处于高位，对黄金和高估值成长资产的贴现率压力更直接。")
    if metric.key == "treasury_10y" and value >= 4.5:
        return ScoredMetric(metric, score, "higher-for-longer定价", "长端收益率处于敏感区间，市场正在重新定价higher-for-longer利率环境。")
    if change > 0.06:
        return ScoredMetric(metric, score, "利率上行", "收益率边际上行抬高贴现率，金融条件边际收紧。")
    return ScoredMetric(metric, score, "利率中性", "利率信号暂未形成新的方向性冲击。")


def _score_curve(metric: MarketMetric) -> ScoredMetric:
    value = metric.value or 0
    score = 70 if value < -50 else 55 if value < 0 else 45
    if value < 0:
        return ScoredMetric(metric, score, "曲线倒挂", "期限利差仍反映增长放缓或政策限制性环境。")
    return ScoredMetric(metric, score, "曲线正常化", "期限结构对衰退风险的定价压力有所缓和。")


def _score_fx(metric: MarketMetric) -> ScoredMetric:
    pct = metric.change_pct or 0
    value = metric.value or 0
    if metric.key == "dxy":
        score = _clamp(_logistic(value, 104, 0.55) * 100 + max(0, pct) * 6)
        if value >= 104 and pct > 0:
            return ScoredMetric(metric, score, "美元流动性收紧", "美元走强与风险资产估值压力具有一致性，全球金融条件边际收紧。")
        return ScoredMetric(metric, score, "美元中性", "美元指数尚未释放强烈的全球流动性挤压信号。")
    return ScoredMetric(metric, _clamp(45 + abs(pct) * 4), "汇率交叉验证", "主要汇率用于验证美元强弱是否具有广谱性。")


def _score_commodity(metric: MarketMetric, metrics: dict[str, MarketMetric]) -> ScoredMetric:
    pct = metric.change_pct or 0
    if metric.key == "gold":
        pressure = 8 if (_value(metrics, "real_yield_10y") or 0) > 2 else 0
        pressure += 6 if (_change_pct(metrics, "dxy") or 0) > 0.3 else 0
        return ScoredMetric(metric, _clamp(50 - pct * 4 + pressure), "实际利率敏感", "黄金走势需要结合实际利率而非单看通胀；实际利率上行会削弱黄金配置吸引力。")
    return ScoredMetric(metric, _clamp(50 + max(0, pct) * 3), "通胀与增长信号", "油价上行可能同时指向需求韧性与通胀黏性，需要与利率端联动解读。")


def _score_stress(metric: MarketMetric) -> ScoredMetric:
    pct = metric.change_pct or 0
    if metric.key == "move":
        value = metric.value or 0
        score = _clamp(_logistic(value, 120, 0.05) * 100 + max(0, pct) * 2)
        if pct <= -1:
            if value >= 110:
                return ScoredMetric(metric, score, "美债波动高位回落", "MOVE虽处偏高区间但边际回落，债券波动压力有所缓和，仍需观察是否继续向常态区间收敛。")
            return ScoredMetric(metric, score, "美债波动压力缓和", "MOVE回落显示债券市场波动边际降温，跨资产流动性压力较前一交易日有所缓和。")
        if pct >= 1:
            return ScoredMetric(metric, score, "美债波动压力升温", "MOVE上行意味着债券市场波动扩散，通常比单一VIX更能提示流动性压力。")
        if value >= 110:
            return ScoredMetric(metric, score, "美债波动仍处高位", "MOVE绝对水平仍偏高，债券市场波动尚未完全回到常态区间。")
        return ScoredMetric(metric, score, "美债波动压力", "MOVE未出现明显扩散，债券波动对跨资产风险的边际扰动有限。")
    return ScoredMetric(metric, _clamp(_logistic(metric.value or 0, 5, 0.9) * 100), "信用风险补偿", "信用利差用于区分普通risk-off与融资条件收紧。")


def _score_liquidity_metric(metric: MarketMetric) -> ScoredMetric:
    pct = metric.change_pct or 0
    tightening = pct < -0.5 if metric.key in {"fed_balance_sheet", "bank_reserves", "rrp"} else pct > 0.5
    return ScoredMetric(metric, 68 if tightening else 45, "流动性抽离" if tightening else "流动性中性", "该指标用于判断美元流动性是否对风险资产形成支撑或约束。")


def _adaptive_weights(metrics: dict[str, MarketMetric]) -> dict[str, float]:
    weights = {
        "nasdaq": 0.14, "sp500": 0.08, "russell2000": 0.05, "vix": 0.10, "vvix": 0.04,
        "treasury_10y": 0.14, "treasury_2y": 0.08, "real_yield_10y": 0.10, "curve_2s10s": 0.05,
        "dxy": 0.10, "gold": 0.04, "oil": 0.03, "move": 0.08, "credit_spread_hy": 0.07,
        "cnn_fear_greed": 0.05, "naaim_exposure": 0.04,
    }
    ten_year = _value(metrics, "treasury_10y") or 0
    two_year_change = _change(metrics, "treasury_2y") or 0
    ten_year_change = _change(metrics, "treasury_10y") or 0
    real_yield = _value(metrics, "real_yield_10y") or 0
    dxy = _value(metrics, "dxy") or 0
    dxy_pct = _change_pct(metrics, "dxy") or 0
    vix = _value(metrics, "vix") or 0
    vvix_pct = _change_pct(metrics, "vvix") or 0
    move_pct = _change_pct(metrics, "move") or 0
    credit_pct = _change_pct(metrics, "credit_spread_hy") or 0
    nasdaq_pct = _change_pct(metrics, "nasdaq") or 0

    if ten_year >= 4.5:
        _add_weights(weights, {"treasury_10y": 0.05, "real_yield_10y": 0.04, "nasdaq": 0.03})
    if dxy >= 104:
        _add_weights(weights, {"dxy": 0.04, "move": 0.02})

    financial_conditions_tightening = (
        (ten_year_change >= 0.06 or two_year_change >= 0.06 or real_yield >= 2)
        and (dxy_pct >= 0.25 or dxy >= 104)
    )
    if financial_conditions_tightening:
        _add_weights(
            weights,
            {
                "treasury_10y": 0.04,
                "treasury_2y": 0.03,
                "real_yield_10y": 0.04,
                "dxy": 0.04,
                "nasdaq": 0.02,
                "gold": 0.02,
            },
        )

    hidden_tail_risk = vix < 20 and (vvix_pct >= 5 or move_pct >= 5 or credit_pct >= 3)
    if hidden_tail_risk:
        _add_weights(weights, {"vvix": 0.05, "move": 0.05, "credit_spread_hy": 0.03, "vix": 0.02})

    if move_pct >= 8 and dxy_pct >= 0.25:
        _add_weights(weights, {"move": 0.04, "dxy": 0.03, "credit_spread_hy": 0.03})

    if nasdaq_pct <= -1 and (ten_year_change > 0 or dxy_pct > 0):
        _add_weights(weights, {"nasdaq": 0.03, "treasury_10y": 0.02, "dxy": 0.02})

    naaim = _value(metrics, "naaim_exposure")
    naaim_change = _change(metrics, "naaim_exposure") or 0
    if naaim is not None and (naaim >= 90 or naaim_change <= -15):
        _add_weights(weights, {"naaim_exposure": 0.03, "cnn_fear_greed": 0.01, "nasdaq": 0.01})

    available = {k: v for k, v in weights.items() if k in metrics and metrics[k].value is not None and metrics[k].status == "ok"}
    total = sum(available.values()) or 1
    return {k: v / total for k, v in available.items()}


def _add_weights(weights: dict[str, float], adjustments: dict[str, float]) -> None:
    for key, value in adjustments.items():
        if key in weights:
            weights[key] += value


def _nonlinear_score(scored: dict[str, ScoredMetric], weights: dict[str, float], metrics: dict[str, MarketMetric]) -> int:
    base = sum(scored[key].score * weight for key, weight in weights.items() if key in scored)
    adjustment = 0
    if (_value(metrics, "treasury_10y") or 0) >= 4.5 and (_change_pct(metrics, "nasdaq") or 0) < 0:
        adjustment += 8
    if (_change_pct(metrics, "dxy") or 0) > 0.4 and (_change_pct(metrics, "nasdaq") or 0) < 0:
        adjustment += 6
    if (_change_pct(metrics, "move") or 0) > 5:
        adjustment += 6
    return _clamp(base + adjustment)


def _iron_condor_filter(metrics: dict[str, MarketMetric]) -> IronCondorAssessment:
    score = 70
    positives: list[str] = []
    warnings: list[str] = []
    blockers: list[str] = []

    def missing(key: str, text: str) -> None:
        if _value(metrics, key) is None:
            warnings.append(text)

    vix = _value(metrics, "vix")
    vix_pct = _change_pct(metrics, "vix")
    vvix_pct = _change_pct(metrics, "vvix")
    move_pct = _change_pct(metrics, "move")
    nasdaq_pct = _change_pct(metrics, "nasdaq")
    sp500_pct = _change_pct(metrics, "sp500")
    russell_pct = _change_pct(metrics, "russell2000")
    dxy_pct = _change_pct(metrics, "dxy")
    ten_year = _value(metrics, "treasury_10y")
    credit_pct = _change_pct(metrics, "credit_spread_hy")

    missing("vix", "VIX不可用，缺少隐含波动率主锚。")
    missing("vvix", "VVIX不可用，缺少波动率二阶风险确认。")
    missing("move", "MOVE不可用，缺少债券波动压力确认。")
    missing("sp500", "标普500不可用，缺少大盘方向波动确认。")
    missing("credit_spread_hy", "信用利差不可用，融资压力确认不足。")

    if vix is not None:
        if 15 <= vix <= 22:
            score += 8
            positives.append("VIX处于温和区间，隐含波动率补偿尚可且未进入压力状态。")
        if vix < 13:
            score -= 10
            warnings.append("VIX低于13，期权权利金可能偏薄，卖波动策略的容错空间下降。")
        if vix >= 25:
            score -= 20
            warnings.append("VIX高于25，权益避险需求已明显抬升。")
        if vix >= 30:
            blockers.append("VIX高于30，市场已进入高波动压力区间。")

    if vix_pct is not None:
        if vix_pct <= 0:
            score += 6
            positives.append("VIX边际回落，短端避险需求未扩散。")
        if vix_pct >= 8:
            score -= 18
            warnings.append("VIX单日升幅超过8%，波动率正在扩张。")
        if vix_pct >= 15:
            blockers.append("VIX单日升幅超过15%，不适合区间型卖波动环境。")

    if vvix_pct is not None:
        if vvix_pct <= 0:
            score += 5
            positives.append("VVIX稳定或回落，波动率曲面的尾部保护需求未升温。")
        if vvix_pct >= 5:
            score -= 12
            warnings.append("VVIX升幅超过5%，隐含尾部风险正在重新定价。")
        if vvix_pct >= 10:
            blockers.append("VVIX升幅超过10%，波动率二阶风险显著扩散。")

    if move_pct is not None:
        if move_pct <= 0:
            score += 5
            positives.append("MOVE稳定或回落，债券波动暂未对跨资产风险形成额外扰动。")
        if move_pct >= 5:
            score -= 15
            warnings.append("MOVE升幅超过5%，利率波动可能扰动权益区间结构。")
        if move_pct >= 10:
            blockers.append("MOVE升幅超过10%，债券波动扩散构成关键阻断项。")

    if nasdaq_pct is not None:
        if abs(nasdaq_pct) < 1:
            score += 6
            positives.append("纳指100单日波动低于1%，高久期成长资产仍在可控区间内。")
        if nasdaq_pct <= -1.5:
            score -= 15
            warnings.append("纳指100跌幅超过1.5%，单边下行风险上升。")
        if nasdaq_pct <= -2.5:
            blockers.append("纳指100跌幅超过2.5%，区间突破风险过高。")

    if sp500_pct is not None:
        if abs(sp500_pct) < 0.8:
            score += 5
            positives.append("标普500单日波动低于0.8%，大盘方向性压力有限。")
        if sp500_pct <= -1.2:
            score -= 12
            warnings.append("标普500跌幅超过1.2%，市场风险偏好出现明显降温。")
        if sp500_pct <= -2:
            blockers.append("标普500跌幅超过2%，大盘单边压力不利于铁鹰环境。")

    if russell_pct is not None:
        if russell_pct <= -2:
            score -= 10
            warnings.append("罗素2000跌幅超过2%，小盘风险承压显示市场宽度转弱。")

    if dxy_pct is not None and nasdaq_pct is not None and dxy_pct > 0.4 and nasdaq_pct < 0:
        score -= 10
        warnings.append("美元走强与纳指回落同步，全球美元流动性边际收紧。")

    if ten_year is not None and nasdaq_pct is not None and ten_year >= 4.5 and nasdaq_pct < 0:
        score -= 10
        warnings.append("10年期收益率高于4.5%且纳指下跌，高久期资产承受实际利率约束。")

    if credit_pct is not None:
        if credit_pct <= 1:
            score += 4
            positives.append("信用利差未明显扩大，融资压力暂未系统性抬升。")
        if credit_pct >= 3:
            score -= 12
            warnings.append("信用利差扩大超过3%，融资条件边际收紧。")
        if credit_pct >= 6:
            blockers.append("信用利差扩大超过6%，信用压力构成阻断项。")

    liquidity = _liquidity_regime(metrics, _data_health(metrics))
    if liquidity in {"Dollar Funding Stress", "Liquidity Stress"}:
        blockers.append("流动性状态指向美元融资压力或流动性压力。")

    if not positives:
        warnings.append("缺少明确的低波动、区间震荡或压力回落确认。")

    final_score = _clamp(score)
    if blockers or final_score < 50:
        return IronCondorAssessment(
            final_score,
            "不适合铁鹰 / Unfavourable",
            "#c92a2a",
            "当前存在波动率扩散、债券波动上行或权益单日大幅回撤，Iron Condor容易受到单边突破和隐含波动率上行冲击。",
            positives,
            warnings,
            blockers,
        )
    if final_score >= 75:
        return IronCondorAssessment(
            final_score,
            "适合观察铁鹰 / Suitable",
            "#2f9e44",
            "当前波动率温和、VVIX/MOVE未扩散、权益波动仍在可控区间，环境相对适合观察Iron Condor这类区间型卖波动策略。",
            positives,
            warnings,
            blockers,
        )
    return IronCondorAssessment(
        final_score,
        "中性偏谨慎 / Neutral",
        "#b7791f",
        "当前环境并非明确risk-off，但利率、美元或波动率边际变化仍可能扰动区间策略，Iron Condor需要更严格的风险控制。",
        positives,
        warnings,
        blockers,
    )


def _infer_regime(metrics: dict[str, MarketMetric], health: dict[str, int]) -> RegimeAssessment:
    ten_year = _value(metrics, "treasury_10y")
    real_yield = _value(metrics, "real_yield_10y")
    dxy = _value(metrics, "dxy")
    fear_greed = _value(metrics, "cnn_fear_greed")
    naaim = _value(metrics, "naaim_exposure")
    vix = _value(metrics, "vix")
    move = _value(metrics, "move")
    nasdaq_pct = _change_pct(metrics, "nasdaq") or 0
    dxy_pct = _change_pct(metrics, "dxy") or 0
    ten_year_change = _change(metrics, "treasury_10y") or 0
    gold_pct = _change_pct(metrics, "gold") or 0
    oil_pct = _change_pct(metrics, "oil") or 0

    name, label = "Goldilocks", "温和增长与风险偏好修复"
    if (ten_year or 0) >= 4.5 and dxy_pct > 0 and nasdaq_pct <= 0:
        name, label = "Higher for Longer", "higher-for-longer与实际利率约束"
    elif (vix or 0) >= 25 or (move or 0) >= 140:
        name, label = "Liquidity Stress", "波动率扩散与流动性压力"
    elif dxy is not None and dxy >= 105 and nasdaq_pct < 0:
        name, label = "Dollar Liquidity Squeeze", "美元流动性挤压"
    elif ten_year_change < -0.05 and nasdaq_pct > 0:
        name, label = "Disinflation Rally", "通胀回落交易与贴现率下行"
    elif oil_pct > 2 and ten_year_change > 0:
        name, label = "Stagflation Risk", "油价与利率同步上行的滞胀风险"
    elif nasdaq_pct > 1 and (ten_year or 0) >= 4.4:
        name, label = "AI Melt-up", "AI主线驱动的高久期资产重估"

    liquidity_regime = _liquidity_regime(metrics, health)
    yield_driver = _yield_driver(ten_year_change, real_yield, gold_pct, oil_pct)
    consistency, raw_confidence = _consistency(metrics, name)
    confidence_score = _clamp(raw_confidence - _data_confidence_penalty(health))
    confidence = "高置信度" if confidence_score >= 75 else "中等置信度" if confidence_score >= 55 else "信号分歧"
    summary = _regime_summary(label, liquidity_regime, yield_driver, consistency, health)
    return RegimeAssessment(
        name=name,
        label=label,
        liquidity_regime=liquidity_regime,
        yield_driver=yield_driver,
        confidence=confidence,
        confidence_score=confidence_score,
        consistency=consistency,
        summary=summary,
        knowns=_knowns(metrics, label),
        unknowns=_unknowns(metrics, health),
    )


def _liquidity_regime(metrics: dict[str, MarketMetric], health: dict[str, int]) -> str:
    liquidity_keys = ["bank_reserves", "fed_balance_sheet", "tga", "rrp", "credit_spread_hy", "move"]
    available = sum(1 for key in liquidity_keys if _value(metrics, key) is not None)
    if available < 3:
        return "基于可用市场价格推断"
    dxy_pct = _change_pct(metrics, "dxy") or 0
    move_pct = _change_pct(metrics, "move") or 0
    reserves = _change_pct(metrics, "bank_reserves")
    fed_bs = _change_pct(metrics, "fed_balance_sheet")
    tga = _change_pct(metrics, "tga")
    if dxy_pct > 0.5 and move_pct > 5:
        return "Dollar Funding Stress"
    if (reserves is not None and reserves < -0.5) or (fed_bs is not None and fed_bs < -0.3) or (tga is not None and tga > 1):
        return "Liquidity Tightening"
    if (reserves is not None and reserves > 0.5) or (fed_bs is not None and fed_bs > 0.2):
        return "Liquidity Expansion"
    return "Liquidity Neutral"


def _yield_driver(ten_year_change: float, real_yield: float | None, gold_pct: float, oil_pct: float) -> str:
    if ten_year_change <= 0:
        return "收益率未形成上行冲击"
    if real_yield is not None and real_yield >= 2 and gold_pct < 0:
        return "实际利率上行 / term premium重估"
    if oil_pct > 1.5:
        return "通胀预期与供给风险驱动"
    return "增长预期或期限溢价重估"


def _consistency(metrics: dict[str, MarketMetric], regime_name: str) -> tuple[str, int]:
    nasdaq_pct = _change_pct(metrics, "nasdaq") or 0
    dxy_pct = _change_pct(metrics, "dxy") or 0
    ten_year_change = _change(metrics, "treasury_10y") or 0
    gold_pct = _change_pct(metrics, "gold") or 0
    score = 70
    conflicts: list[str] = []
    if dxy_pct > 0 and ten_year_change > 0 and nasdaq_pct < 0:
        score += 15
    if dxy_pct > 0 and ten_year_change > 0 and nasdaq_pct > 0.8:
        score -= 18
        conflicts.append("美元与长端利率走强但权益仍上涨，可能存在流动性或主题交易支撑。")
    if ten_year_change > 0 and gold_pct > 0.8:
        score -= 10
        conflicts.append("收益率上行但黄金同步走强，需区分实际利率与避险需求。")
    if regime_name == "Liquidity Stress" and nasdaq_pct > 0:
        score -= 12
        conflicts.append("压力指标上行但权益未同步定价，短期信号存在错位。")
    if conflicts:
        return "当前市场信号存在分歧，需警惕宏观叙事切换。" + " ".join(conflicts), _clamp(score)
    return "跨资产信号相对一致，宏观叙事与价格行为基本匹配。", _clamp(score)


def _regime_summary(label: str, liquidity: str, yield_driver: str, consistency: str, health: dict[str, int]) -> str:
    limitation = ""
    if health["aux_missing"] >= 2:
        limitation = " 由于部分流动性或信用辅助数据暂不可用，流动性判断基于可用市场价格推断。"
    if health["core_cached"] > 0:
        limitation += " 部分核心指标使用缓存，需等待实时源恢复后复核。"
    return f"当前主导框架为“{label}”。流动性状态为{liquidity}，收益率驱动更接近“{yield_driver}”。{consistency}{limitation}"


def _knowns(metrics: dict[str, MarketMetric], label: str) -> list[str]:
    items = [f"当前市场主线更接近“{label}”。"]
    ten_year = _value(metrics, "treasury_10y")
    dxy = _value(metrics, "dxy")
    fear_greed = _value(metrics, "cnn_fear_greed")
    naaim = _value(metrics, "naaim_exposure")
    if ten_year is not None:
        items.append(f"10年期美债收益率处于{ten_year:.2f}%附近，是高久期资产估值的核心约束。")
    if dxy is not None:
        items.append(f"DXY位于{dxy:.2f}，美元方向仍是全球风险偏好的关键变量。")
    if fear_greed is not None:
        items.append(f"CNN恐惧与贪婪指数为{fear_greed:.0f}，可作为美股情绪拥挤度的辅助观察。")
    if naaim is not None:
        items.append(f"NAAIM主动管理人权益敞口为{naaim:.0f}，用于观察机构风险预算的边际变化。")
    return items


def _unknowns(metrics: dict[str, MarketMetric], health: dict[str, int]) -> list[str]:
    unknowns = ["通胀粘性与美联储反应函数仍是核心不确定性。", "财政供给与term premium重估是否延续仍需观察。"]
    if _value(metrics, "real_yield_10y") is None:
        unknowns.append("实际利率数据缺失，黄金与成长股敏感度判断置信度下降。")
    if _value(metrics, "credit_spread_hy") is None:
        unknowns.append("信用利差不可用，普通risk-off与融资压力的区分能力下降。")
    if health["aux_missing"] >= 2:
        unknowns.append("部分流动性辅助指标暂不可用，美元流动性 regime 不应被过度精确解读。")
    return unknowns


def _build_summary(metrics: dict[str, MarketMetric], regime: RegimeAssessment, health: dict[str, int]) -> str:
    ten_year = _value(metrics, "treasury_10y")
    dxy_pct = _change_pct(metrics, "dxy")
    nasdaq_pct = _change_pct(metrics, "nasdaq")
    parts = [regime.summary]
    if ten_year is not None and ten_year >= 4.5:
        parts.append("长端收益率位于权益久期敏感区间，实际利率与term premium的边际变化对纳指估值更具解释力。")
    if dxy_pct is not None and dxy_pct > 0:
        parts.append("美元走强意味着离岸美元流动性与全球金融条件边际收紧。")
    if nasdaq_pct is not None and nasdaq_pct > 0 and ten_year is not None and ten_year >= 4.5:
        parts.append("纳指上涨并不必然代表宏观压力解除，更可能反映主题交易或流动性韧性。")
    return " ".join(parts)


def _build_risks(metrics: dict[str, MarketMetric], regime: RegimeAssessment, health: dict[str, int]) -> list[str]:
    risks = [regime.consistency]
    if (_value(metrics, "treasury_10y") or 0) >= 4.5:
        risks.append("长端收益率高位运行，实际利率上行仍可能压制高估值成长资产。")
    if (_change_pct(metrics, "dxy") or 0) > 0.3:
        risks.append("美元与长端收益率同步走强，金融条件边际收紧。")
    if (_change_pct(metrics, "vix") or 0) > 8:
        risks.append("VIX单日跳升，波动率边际变化提示避险需求升温。")
    if health["core_cached"] or health["core_missing"]:
        risks.append("部分核心数据并非实时有效值，需将价格结论视为暂定判断。")
    return list(dict.fromkeys(risks))[:4]


def _build_action(score: int, regime: RegimeAssessment, health: dict[str, int]) -> str:
    qualifier = "在当前数据可得性约束下，" if health["core_cached"] or health["aux_missing"] >= 2 else ""
    if score >= 72:
        return f"策略含义：{qualifier}风险预算宜保持克制。当前{regime.label}占优，优先等待利率、美元或波动率至少一项转向确认。"
    if score >= 45:
        return f"策略含义：{qualifier}维持中性偏审慎。当前不是简单risk-on/risk-off，关键在于{regime.yield_driver}是否继续强化。"
    return f"策略含义：{qualifier}风险环境相对温和，但仍需确认流动性扩张能否持续，并警惕低波动环境下的尾部风险重定价。"


def _data_health(metrics: dict[str, MarketMetric]) -> dict[str, int]:
    return {
        "core_live": sum(1 for m in metrics.values() if m.importance == "core" and m.status == "ok" and m.freshness not in {"cache", "missing"}),
        "core_cached": sum(1 for m in metrics.values() if m.importance == "core" and m.status == "ok" and m.freshness == "cache"),
        "core_missing": sum(1 for m in metrics.values() if m.importance == "core" and m.status != "ok"),
        "aux_missing": sum(1 for m in metrics.values() if m.importance == "auxiliary" and m.status != "ok"),
        "suspicious": sum(1 for m in metrics.values() if m.status == "suspicious"),
    }


def _data_quality(health: dict[str, int]) -> str:
    if health["suspicious"] > 0 or health["core_missing"] >= 2:
        return "数据异常"
    if health["core_cached"] > 0:
        return "使用缓存"
    if health["core_missing"] == 1 or health["aux_missing"] >= 2:
        return "部分缺失"
    return "正常"


def _data_confidence_penalty(health: dict[str, int]) -> int:
    return health["core_missing"] * 22 + health["core_cached"] * 10 + min(health["aux_missing"] * 3, 15) + health["suspicious"] * 18


def _regime_transition(previous: str | None, current: str) -> str:
    if not previous:
        return "暂无可比历史叙事，今日作为后续regime记忆的起点。"
    if previous == current:
        return f"宏观叙事延续：市场仍处于{current}框架内，价格行为正在验证前一交易日判断。"
    return f"宏观叙事切换：由{previous}转向{current}，需重点观察跨资产价格是否继续确认。"


def _light(score: int) -> tuple[str, str, str]:
    if score <= 39:
        return "绿灯", "#2f9e44", "宏观压力相对可控，但并不等同于单边看多。"
    if score <= 70:
        return "黄灯", "#b7791f", "跨资产信号进入观察区，风险偏好需要更多确认。"
    return "红灯", "#c92a2a", "金融条件收紧或波动扩散正在抬升风险溢价。"


def _value(metrics: dict[str, MarketMetric], key: str) -> float | None:
    metric = metrics.get(key)
    if metric is None or metric.value is None or metric.status != "ok":
        return None
    return metric.value


def _change(metrics: dict[str, MarketMetric], key: str) -> float | None:
    metric = metrics.get(key)
    if metric is None or metric.status != "ok":
        return None
    return metric.change


def _change_pct(metrics: dict[str, MarketMetric], key: str) -> float | None:
    metric = metrics.get(key)
    if metric is None or metric.status != "ok":
        return None
    return metric.change_pct


def _logistic(value: float, center: float, steepness: float) -> float:
    return 1 / (1 + math.exp(-steepness * (value - center)))


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, round(value)))
