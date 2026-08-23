from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .etf_monitor import PortfolioPosition
from .price_history import InstrumentIdentity, PriceHistory, fetch_price_history
from .technical_indicators import IndicatorSnapshot, MacdSnapshot, PriceBar, indicator_snapshot


TECHNICAL_STATE_PATH = Path("output") / "cache" / "technical_swing_state.json"


@dataclass(frozen=True)
class SwingUniverseItem:
    symbol: str
    origin: str
    position: PortfolioPosition | None = None


@dataclass(frozen=True)
class SwingPivot:
    kind: str
    index: int
    price: float
    timestamp: datetime
    volume: float | None


@dataclass(frozen=True)
class SwingZone:
    kind: str
    lower: float
    upper: float
    score: int
    touches: int
    components: tuple[str, ...]


@dataclass(frozen=True)
class TechnicalScorecard:
    above_ema5: bool | None
    above_ema10: bool | None
    above_ema21: bool | None
    above_sma50: bool | None
    above_sma200: bool | None
    trend_score: int
    momentum_score: int
    breakout_score: int
    total_score: int
    benchmark_return_20d: float | None = None
    relative_strength_20d: float | None = None
    regime: str = "中性混合 / Neutral"
    interpretation: str = "数据不足"
    components: tuple[str, ...] = ()


@dataclass(frozen=True)
class TechnicalStructureDiagnostic:
    channel_window: int
    channel_lower: float | None
    channel_mid: float | None
    channel_upper: float | None
    channel_position_pct: float | None
    channel_slope_20d_pct: float | None
    efficiency_ratio_20d: float | None
    short_term_state: str
    medium_term_state: str
    long_term_state: str
    phase: str
    continuation_tendency: str
    reversal_risk: str
    bar_patterns: tuple[str, ...] = ()
    summary: str = ""
    confirmation: str = ""
    invalidation: str = ""


@dataclass(frozen=True)
class SwingAssessment:
    symbol: str
    origin: str
    identity: InstrumentIdentity
    current_price: float | None
    change_pct: float | None
    indicators: IndicatorSnapshot
    trend: str
    technical_status: str
    supports: tuple[SwingZone, ...]
    resistances: tuple[SwingZone, ...]
    invalidation_level: float | None
    volume_ratio: float | None
    volume_label: str
    volume_confirmation: str
    note: str
    data_source: str
    data_timestamp: str
    data_quality: str
    asset_class: str
    position_weight_pct: float | None = None
    average_cost_gbp: float | None = None
    unrealized_pnl_gbp: float | None = None
    unrealized_pnl_pct: float | None = None
    scorecard: TechnicalScorecard | None = None
    structure: TechnicalStructureDiagnostic | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TechnicalSwingReport:
    generated_at: str
    assessments: tuple[SwingAssessment, ...] = ()
    warnings: tuple[str, ...] = ()
    summary: str = ""


def parse_ticker_list(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    parts = value.split(",") if isinstance(value, str) else value
    return tuple(
        dict.fromkeys(
            str(item).strip().upper()
            for item in parts
            if str(item).strip()
        )
    )


def resolve_swing_universe(
    holdings: Sequence[PortfolioPosition] | Sequence[str],
    watchlist: Sequence[str] | str | None,
    temporary_tickers: Sequence[str] | str | None,
) -> tuple[SwingUniverseItem, ...]:
    resolved: dict[str, SwingUniverseItem] = {}
    for holding in holdings:
        position = holding if isinstance(holding, PortfolioPosition) else None
        symbol = (holding.symbol if position else str(holding)).strip().upper()
        if symbol:
            resolved[symbol] = SwingUniverseItem(symbol, "holding", position)
    for origin, values in (
        ("watchlist", parse_ticker_list(watchlist)),
        ("temporary", parse_ticker_list(temporary_tickers)),
    ):
        for symbol in values:
            resolved.setdefault(symbol, SwingUniverseItem(symbol, origin))
    return tuple(resolved.values())


def detect_pivots(bars: Sequence[PriceBar]) -> tuple[SwingPivot, ...]:
    pivots: list[SwingPivot] = []
    for index in range(2, len(bars) - 2):
        current = bars[index]
        neighbours = (bars[index - 2], bars[index - 1], bars[index + 1], bars[index + 2])
        if all(current.low < item.low for item in neighbours):
            pivots.append(SwingPivot("support", index, current.low, current.timestamp, current.volume))
        if all(current.high > item.high for item in neighbours):
            pivots.append(SwingPivot("resistance", index, current.high, current.timestamp, current.volume))
    return tuple(pivots)


def cluster_pivots(
    pivots: Sequence[SwingPivot],
    *,
    kind: str,
    atr_value: float | None,
    current_price: float,
    bars_count: int,
    baseline_volume: float | None = None,
) -> tuple[SwingZone, ...]:
    selected = sorted((pivot for pivot in pivots if pivot.kind == kind), key=lambda item: item.price)
    if not selected:
        return ()
    tolerance = min(atr_value or current_price * 0.02, current_price * 0.03)
    max_width = min((atr_value or current_price * 0.03) * 2, current_price * 0.06)
    clusters: list[list[SwingPivot]] = []
    for pivot in selected:
        if not clusters:
            clusters.append([pivot])
            continue
        center = sum(item.price for item in clusters[-1]) / len(clusters[-1])
        candidate_prices = [item.price for item in clusters[-1]] + [pivot.price]
        if abs(pivot.price - center) <= tolerance and max(candidate_prices) - min(candidate_prices) <= max_width:
            clusters[-1].append(pivot)
        else:
            clusters.append([pivot])
    zones = [
        _zone_from_cluster(cluster, kind, atr_value, current_price, bars_count, baseline_volume)
        for cluster in clusters
    ]
    return tuple(sorted(zones, key=lambda zone: zone.score, reverse=True))


def _zone_from_cluster(
    cluster: Sequence[SwingPivot],
    kind: str,
    atr_value: float | None,
    current_price: float,
    bars_count: int,
    baseline_volume: float | None,
) -> SwingZone:
    center = sum(item.price for item in cluster) / len(cluster)
    padding = min((atr_value or current_price * 0.02) * 0.5, current_price * 0.015)
    latest_index = max(item.index for item in cluster)
    recency = max(0, 25 - int((bars_count - 1 - latest_index) / max(bars_count, 1) * 25))
    touch_score = min(45, len(cluster) * 15)
    volume_values = [item.volume for item in cluster if item.volume is not None]
    volume_ratio = (
        (sum(volume_values) / len(volume_values)) / baseline_volume
        if volume_values and baseline_volume and baseline_volume > 0
        else None
    )
    if volume_ratio is None:
        volume_score = 0
        volume_component = "成交量比N/A"
    elif volume_ratio < 1.0:
        volume_score = 0
        volume_component = f"成交量比{volume_ratio:.2f}x"
    elif volume_ratio < 1.5:
        volume_score = 5
        volume_component = f"成交量比{volume_ratio:.2f}x"
    else:
        volume_score = 10
        volume_component = f"成交量比{volume_ratio:.2f}x"
    score = max(1, min(100, 20 + touch_score + recency + volume_score))
    components = (f"{len(cluster)}次触及", f"新近度+{recency}", volume_component, f"成交量+{volume_score}")
    return SwingZone(kind, center - padding, center + padding, score, len(cluster), components)


def classify_trend(price: float, indicators: IndicatorSnapshot, asset_class: str = "equity") -> str:
    if asset_class == "cash_like":
        return "现金与短债结构"
    ema21, sma50, sma200 = indicators.ema21, indicators.sma50, indicators.sma200
    if None in (ema21, sma50, sma200):
        return "数据不足"
    if price > ema21 > sma50 > sma200:
        return "强势上行"
    if price < ema21 and ema21 > sma50 > sma200:
        return "上升趋势中的回调"
    if price < sma50 and ema21 < sma50 and sma50 > sma200:
        return "中期动能转弱"
    if price < ema21 < sma50 < sma200:
        return "空头结构"
    return "中性/混合"


def classify_volume(ratio: float | None) -> str:
    if ratio is None:
        return "成交量数据不足"
    if ratio < 0.7:
        return "低量"
    if ratio <= 1.2:
        return "正常"
    if ratio <= 1.5:
        return "小幅放量"
    if ratio <= 2:
        return "明显放量"
    return "异常放量"


def _above(price: float, level: float | None) -> bool | None:
    if level is None:
        return None
    return price > level


def _score_true(values: Iterable[bool | None]) -> int:
    return sum(1 for value in values if value is True)


def _scorecard_regime(price: float, indicators: IndicatorSnapshot, asset_class: str) -> str:
    if asset_class == "cash_like":
        return "现金/短债：趋势评分不适用"
    ema21, sma50, sma200 = indicators.ema21, indicators.sma50, indicators.sma200
    if ema21 is None or sma50 is None or sma200 is None:
        return "数据不足"
    if price > ema21 > sma50 > sma200:
        return "强势多头 / Strong Bull"
    if price < ema21 and sma50 > sma200:
        return "多头回调 / Bull Pullback"
    if price > ema21 and ema21 < sma50:
        return "趋势修复 / Repairing"
    if price > ema21 and sma50 < sma200:
        return "空头反弹 / Bear Rally"
    if price < ema21 < sma50 < sma200:
        return "空头结构 / Bear"
    return "中性混合 / Neutral"


def _scorecard_interpretation(total_score: int) -> str:
    if total_score <= 5:
        return "弱势/暂不宜追"
    if total_score <= 9:
        return "反弹观察"
    if total_score <= 12:
        return "趋势修复"
    if total_score <= 15:
        return "强突破"
    return "高动量，注意过热"


def _calculate_scorecard(
    bars: Sequence[PriceBar],
    indicators: IndicatorSnapshot,
    *,
    benchmark_return_20d: float | None,
    asset_class: str,
) -> TechnicalScorecard:
    price = bars[-1].close
    above_ema5 = _above(price, indicators.ema5)
    above_ema10 = _above(price, indicators.ema10)
    above_ema21 = _above(price, indicators.ema21)
    above_sma50 = _above(price, indicators.sma50)
    above_sma200 = _above(price, indicators.sma200)
    trend_score = _score_true((above_ema5, above_ema10, above_ema21, above_sma50, above_sma200))

    relative_strength_20d = (
        indicators.return_20d - benchmark_return_20d
        if indicators.return_20d is not None and benchmark_return_20d is not None
        else None
    )
    momentum_score = _score_true(
        (
            indicators.rsi14 is not None and indicators.rsi14 > 50,
            indicators.macd_histogram is not None and indicators.macd_histogram > 0,
            indicators.return_20d is not None and indicators.return_20d > 0,
            indicators.return_60d is not None and indicators.return_60d > 0,
            relative_strength_20d is not None and relative_strength_20d > 0,
        )
    )

    previous_indicators = indicator_snapshot(bars[:-1]) if len(bars) >= 2 else IndicatorSnapshot()
    previous_close = bars[-2].close if len(bars) >= 2 else None
    crossed_ema21 = (
        previous_close is not None
        and previous_indicators.ema21 is not None
        and indicators.ema21 is not None
        and previous_close <= previous_indicators.ema21
        and price > indicators.ema21
    )
    stayed_above_ema21 = (
        previous_close is not None
        and previous_indicators.ema21 is not None
        and indicators.ema21 is not None
        and previous_close > previous_indicators.ema21
        and price > indicators.ema21
    )
    above_ema21_buffer = indicators.ema21 is not None and price >= indicators.ema21 * 1.01
    volume_above_avg = (
        bars[-1].volume is not None
        and indicators.average_volume_20 is not None
        and bars[-1].volume > indicators.average_volume_20
    )
    close_above_10d_high = len(bars) > 10 and price > max(bar.high for bar in bars[-11:-1])
    breakout_score = _score_true(
        (crossed_ema21, stayed_above_ema21, above_ema21_buffer, volume_above_avg, close_above_10d_high)
    )

    raw_score = trend_score + momentum_score + breakout_score
    total_score = max(0, min(20, int(round(raw_score / 15 * 20))))
    relative_text = (
        f"20D相对基准 {relative_strength_20d:+.2f}%"
        if relative_strength_20d is not None
        else "20D相对基准 N/A"
    )
    components = (
        f"均线位置 {trend_score}/5",
        f"动量确认 {momentum_score}/5",
        f"突破确认 {breakout_score}/5",
        relative_text,
    )
    return TechnicalScorecard(
        above_ema5=above_ema5,
        above_ema10=above_ema10,
        above_ema21=above_ema21,
        above_sma50=above_sma50,
        above_sma200=above_sma200,
        trend_score=trend_score,
        momentum_score=momentum_score,
        breakout_score=breakout_score,
        total_score=total_score,
        benchmark_return_20d=benchmark_return_20d,
        relative_strength_20d=relative_strength_20d,
        regime=_scorecard_regime(price, indicators, asset_class),
        interpretation=_scorecard_interpretation(total_score),
        components=components,
    )


def _build_structure_diagnostic(
    bars: Sequence[PriceBar],
    indicators: IndicatorSnapshot,
    scorecard: TechnicalScorecard,
    *,
    asset_class: str,
) -> TechnicalStructureDiagnostic | None:
    if asset_class != "equity" or len(bars) < 30:
        return None
    window = min(90, len(bars))
    scoped = bars[-window:]
    closes = [bar.close for bar in scoped]
    lower, mid, upper, slope_pct = _regression_channel(closes)
    price = bars[-1].close
    position_pct = (
        (price - lower) / (upper - lower) * 100
        if lower is not None and upper is not None and upper > lower
        else None
    )
    efficiency = _efficiency_ratio([bar.close for bar in bars], 20)
    short_state = _short_term_state(price, indicators)
    medium_state = _medium_term_state(price, indicators)
    long_state = _long_term_state(price, indicators)
    patterns = _bar_patterns(bars, indicators)
    phase = _structure_phase(short_state, medium_state, long_state, patterns)
    continuation = _continuation_tendency(short_state, medium_state, long_state, efficiency, patterns)
    reversal = _reversal_risk(indicators.rsi14, position_pct, short_state, long_state, patterns)
    summary, confirmation, invalidation = _structure_narrative(
        price,
        lower,
        mid,
        upper,
        indicators,
        short_state,
        medium_state,
        long_state,
        phase,
        patterns,
    )
    return TechnicalStructureDiagnostic(
        channel_window=window,
        channel_lower=lower,
        channel_mid=mid,
        channel_upper=upper,
        channel_position_pct=position_pct,
        channel_slope_20d_pct=slope_pct,
        efficiency_ratio_20d=efficiency,
        short_term_state=short_state,
        medium_term_state=medium_state,
        long_term_state=long_state,
        phase=phase,
        continuation_tendency=continuation,
        reversal_risk=reversal,
        bar_patterns=patterns,
        summary=summary,
        confirmation=confirmation,
        invalidation=invalidation,
    )


def _regression_channel(closes: Sequence[float]) -> tuple[float | None, float | None, float | None, float | None]:
    count = len(closes)
    if count < 20:
        return None, None, None, None
    x_mean = (count - 1) / 2
    y_mean = sum(closes) / count
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    if denominator <= 0:
        return None, None, None, None
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(closes)) / denominator
    intercept = y_mean - slope * x_mean
    fitted = [intercept + slope * index for index in range(count)]
    residual_sigma = math.sqrt(sum((value - fit) ** 2 for value, fit in zip(closes, fitted)) / count)
    mid = fitted[-1]
    width = max(2 * residual_sigma, abs(mid) * 0.005)
    slope_pct = slope * 20 / mid * 100 if mid else None
    return mid - width, mid, mid + width, slope_pct


def _efficiency_ratio(closes: Sequence[float], window: int) -> float | None:
    if len(closes) <= window:
        return None
    scoped = closes[-window - 1:]
    path = sum(abs(current - previous) for previous, current in zip(scoped, scoped[1:]))
    if path <= 0:
        return 0.0
    return abs(scoped[-1] - scoped[0]) / path


def _short_term_state(price: float, indicators: IndicatorSnapshot) -> str:
    ema5, ema10, ema21 = indicators.ema5, indicators.ema10, indicators.ema21
    macd = indicators.macd
    if None in (ema5, ema10, ema21):
        return "数据不足"
    if price > ema5 > ema10 > ema21 and (macd is None or macd.position != "below_signal"):
        return "短线多头"
    if price < ema5 < ema10 < ema21 and (macd is None or macd.position != "above_signal"):
        return "短线空头"
    if price > ema21:
        return "短线修复"
    return "短线回调"


def _medium_term_state(price: float, indicators: IndicatorSnapshot) -> str:
    if indicators.sma50 is None:
        return "数据不足"
    if price > indicators.sma50 and (indicators.return_60d or 0) > 0:
        return "中期上升"
    if price < indicators.sma50 and (indicators.return_60d or 0) < 0:
        return "中期下行"
    return "中期震荡"


def _long_term_state(price: float, indicators: IndicatorSnapshot) -> str:
    if indicators.sma50 is None or indicators.sma200 is None:
        return "数据不足"
    if price > indicators.sma200 and indicators.sma50 > indicators.sma200:
        return "长期多头"
    if price < indicators.sma200 and indicators.sma50 < indicators.sma200:
        return "长期空头"
    if price > indicators.sma200:
        return "长期修复"
    return "长期转弱"


def _bar_patterns(bars: Sequence[PriceBar], indicators: IndicatorSnapshot) -> tuple[str, ...]:
    if len(bars) < 8:
        return ()
    current, previous = bars[-1], bars[-2]
    current_range = max(0.0, current.high - current.low)
    patterns: list[str] = []
    if current.high <= previous.high and current.low >= previous.low:
        patterns.append("Inside Bar")
    if current_range <= min(bar.high - bar.low for bar in bars[-7:]):
        patterns.append("NR7")
    if indicators.atr14 and current_range <= indicators.atr14 * 0.65:
        patterns.append("Coil/窄幅收缩")
    close_location = (current.close - current.low) / current_range if current_range > 0 else 0.5
    if close_location <= 0.25:
        patterns.append("Weak Close")
    if current.high < previous.high:
        patterns.append("Lower High")
    if current.low > previous.low:
        patterns.append("Higher Low")
    if current.close < current.open:
        patterns.append("Bearish Bar")
    elif current.close > current.open:
        patterns.append("Bullish Bar")
    return tuple(patterns)


def _structure_phase(short: str, medium: str, long: str, patterns: tuple[str, ...]) -> str:
    if any(label in patterns for label in ("Inside Bar", "NR7", "Coil/窄幅收缩")):
        return "Compression / 压缩"
    if short == "短线多头" and medium == "中期上升":
        return "Expansion / 上行扩张"
    if short in {"短线空头", "短线回调"} and long == "长期多头":
        return "Pullback / 多头回调"
    if short == "短线空头" and medium == "中期下行":
        return "Markdown / 下行阶段"
    return "Transition / 转换"


def _continuation_tendency(
    short: str,
    medium: str,
    long: str,
    efficiency: float | None,
    patterns: tuple[str, ...],
) -> str:
    bullish_alignment = short == "短线多头" and medium == "中期上升" and long == "长期多头"
    bearish_alignment = short == "短线空头" and medium == "中期下行" and long == "长期空头"
    if (bullish_alignment or bearish_alignment) and (efficiency or 0) >= 0.35:
        return "高（方向一致、路径效率较高）"
    if "Weak Close" in patterns and short in {"短线空头", "短线回调"}:
        return "中高（短线弱势延续）"
    if short.startswith("短线") and medium != "数据不足":
        return "中（等待量价确认）"
    return "低/数据不足"


def _reversal_risk(
    rsi14: float | None,
    channel_position_pct: float | None,
    short: str,
    long: str,
    patterns: tuple[str, ...],
) -> str:
    extreme = (
        rsi14 is not None and (rsi14 <= 30 or rsi14 >= 70)
    ) or (
        channel_position_pct is not None and (channel_position_pct <= 5 or channel_position_pct >= 95)
    )
    conflict = (short == "短线空头" and long == "长期多头") or (short == "短线多头" and long == "长期空头")
    if extreme and conflict:
        return "高（极端位置且周期冲突）"
    if extreme or conflict or "Inside Bar" in patterns:
        return "中（需要反转K线确认）"
    return "低（暂无极端或周期冲突）"


def _structure_narrative(
    price: float,
    lower: float | None,
    mid: float | None,
    upper: float | None,
    indicators: IndicatorSnapshot,
    short: str,
    medium: str,
    long: str,
    phase: str,
    patterns: tuple[str, ...],
) -> tuple[str, str, str]:
    summary = f"{short}；{medium}；{long}；当前处于{phase}。"
    if short in {"短线空头", "短线回调"} and long == "长期多头":
        confirmation = "等待止跌K线、重新站上EMA5，并由MACD柱线收缩或金叉确认。"
    elif short == "短线多头":
        confirmation = "等待放量突破或回踩EMA10/21不破，避免远离通道中轨追价。"
    else:
        confirmation = "等待短中周期重新同向，并观察成交量是否确认。"
    atr_value = indicators.atr14 or 0.0
    if lower is not None:
        invalidation_level = lower - 0.5 * atr_value
        invalidation = f"日线有效跌破回归通道下轨附近 {lower:.2f}；参考失效位 {invalidation_level:.2f}。"
    elif indicators.ema21 is not None:
        invalidation = f"日线跌破EMA21附近 {indicators.ema21:.2f} 且无法快速收复。"
    else:
        invalidation = "数据不足，暂不设置伪精确失效位。"
    if "Weak Close" in patterns:
        confirmation = "最新K线弱收盘；" + confirmation
    return summary, confirmation, invalidation


def assess_swing(
    history: PriceHistory,
    *,
    origin: str,
    position: PortfolioPosition | None = None,
    asset_class: str = "equity",
    benchmark_return_20d: float | None = None,
) -> SwingAssessment:
    requested = history.identity.requested_symbol.upper()
    resolved = history.identity.resolved_symbol.upper()
    warnings = list(history.warnings)
    if requested != resolved:
        warnings.append(f"请求 ticker {requested} 与数据源返回 {resolved} 不一致，已停止技术判断。")
    bars = history.bars
    indicators = indicator_snapshot(bars)
    price = bars[-1].close
    scorecard = _calculate_scorecard(
        bars,
        indicators,
        benchmark_return_20d=benchmark_return_20d,
        asset_class=asset_class,
    )
    structure = _build_structure_diagnostic(
        bars,
        indicators,
        scorecard,
        asset_class=asset_class,
    )
    previous = bars[-2].close if len(bars) >= 2 else None
    change_pct = ((price / previous) - 1) * 100 if previous else None
    volume_ratio = (
        bars[-1].volume / indicators.average_volume_20
        if bars[-1].volume is not None and indicators.average_volume_20
        else None
    )
    trend = classify_trend(price, indicators, asset_class)
    pivots = detect_pivots(bars)
    supports = cluster_pivots(
        pivots,
        kind="support",
        atr_value=indicators.atr14,
        current_price=price,
        bars_count=len(bars),
        baseline_volume=indicators.average_volume_20,
    )
    resistances = cluster_pivots(
        pivots,
        kind="resistance",
        atr_value=indicators.atr14,
        current_price=price,
        bars_count=len(bars),
        baseline_volume=indicators.average_volume_20,
    )
    nearest_support = _nearest_zone(supports, price, below=True)
    nearest_resistance = _nearest_zone(resistances, price, below=False)
    volume_label = classify_volume(volume_ratio)
    status = _classify_status(
        price,
        change_pct,
        nearest_support,
        nearest_resistance,
        supports,
        resistances,
        volume_ratio,
        trend,
        asset_class,
    )
    invalidation = (
        nearest_support.lower - 0.5 * indicators.atr14
        if nearest_support and indicators.atr14 is not None and asset_class != "cash_like"
        else None
    )
    confirmation = _volume_confirmation(change_pct, volume_ratio)
    note = _risk_note(asset_class, trend, status, nearest_support, nearest_resistance)
    if requested != resolved:
        status = "ticker身份待核验"
    visible_supports = _zones_for_report(supports, price, support=True)
    visible_resistances = _zones_for_report(resistances, price, support=False)
    return SwingAssessment(
        symbol=requested,
        origin=origin,
        identity=history.identity,
        current_price=price,
        change_pct=change_pct,
        indicators=indicators,
        trend=trend,
        technical_status=status,
        supports=visible_supports,
        resistances=visible_resistances,
        invalidation_level=invalidation,
        volume_ratio=volume_ratio,
        volume_label=volume_label,
        volume_confirmation=confirmation,
        note=note,
        data_source=history.source,
        data_timestamp=history.observation_at.isoformat() if history.observation_at else "",
        data_quality=history.quality,
        asset_class=asset_class,
        position_weight_pct=position.weight_pct if position else None,
        average_cost_gbp=position.average_cost_gbp if position else None,
        unrealized_pnl_gbp=position.unrealized_pnl_gbp if position else None,
        unrealized_pnl_pct=position.unrealized_pnl_pct if position else None,
        scorecard=scorecard,
        structure=structure,
        warnings=tuple(warnings),
    )


def build_technical_swing_report(
    positions: Sequence[PortfolioPosition],
    watchlist: Sequence[str] | str | None,
    temporary_tickers: Sequence[str] | str | None = None,
    *,
    fetcher: Callable[[str], PriceHistory] | None = None,
    asset_classes: dict[str, str] | None = None,
) -> TechnicalSwingReport:
    universe = resolve_swing_universe(positions, watchlist, temporary_tickers)
    fetch = fetcher or (lambda symbol: fetch_price_history(symbol, period="2y", interval="1d"))
    classes = {key.upper(): value for key, value in (asset_classes or {}).items()}
    benchmark_return_20d = _fetch_benchmark_return(fetch)
    assessments: list[SwingAssessment] = []
    warnings: list[str] = []
    for item in universe:
        try:
            asset_class = classes.get(item.symbol) or _infer_asset_class(item)
            assessment = assess_swing(
                fetch(item.symbol),
                origin=item.origin,
                position=item.position,
                asset_class=asset_class,
                benchmark_return_20d=benchmark_return_20d,
            )
            assessments.append(assessment)
            warnings.extend(assessment.warnings)
        except Exception as exc:
            warnings.append(f"{item.symbol} 技术分析暂不可用：{type(exc).__name__}: {exc}")
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = (
        f"已分析{len(assessments)}个标的，其中持仓"
        f"{sum(item.origin == 'holding' for item in assessments)}个、观察池"
        f"{sum(item.origin != 'holding' for item in assessments)}个。"
    )
    report = TechnicalSwingReport(generated_at, tuple(assessments), tuple(dict.fromkeys(warnings)), summary)
    save_technical_state(report)
    return report


def _fetch_benchmark_return(fetch: Callable[[str], PriceHistory]) -> float | None:
    try:
        return indicator_snapshot(fetch("QQQ").bars).return_20d
    except Exception:
        return None


def save_technical_state(report: TechnicalSwingReport, path: Path = TECHNICAL_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    public_state = {
        "generated_at": report.generated_at,
        "assessments": [
            {
                "symbol": item.symbol,
                "trend": item.trend,
                "technical_status": item.technical_status,
                "supports": [asdict(zone) for zone in item.supports],
                "resistances": [asdict(zone) for zone in item.resistances],
                "data_timestamp": item.data_timestamp,
                "scorecard": asdict(item.scorecard) if item.scorecard else None,
                "structure": asdict(item.structure) if item.structure else None,
            }
            for item in report.assessments
        ],
    }
    path.write_text(json.dumps(public_state, ensure_ascii=False, indent=2), encoding="utf-8")


def technical_swing_from_payload(raw: dict) -> TechnicalSwingReport:
    assessments = []
    for item in raw.get("assessments") or []:
        if not isinstance(item, dict):
            continue
        identity_raw = item.get("identity") or {}
        indicators_raw = item.get("indicators") or {}
        assessments.append(
            SwingAssessment(
                symbol=str(item.get("symbol") or ""),
                origin=str(item.get("origin") or "watchlist"),
                identity=InstrumentIdentity(
                    requested_symbol=str(identity_raw.get("requested_symbol") or item.get("symbol") or ""),
                    resolved_symbol=str(identity_raw.get("resolved_symbol") or item.get("symbol") or ""),
                    name=str(identity_raw.get("name") or item.get("symbol") or ""),
                    exchange=str(identity_raw.get("exchange") or ""),
                    currency=str(identity_raw.get("currency") or ""),
                    instrument_type=str(identity_raw.get("instrument_type") or ""),
                ),
                current_price=_optional_float(item.get("current_price")),
                change_pct=_optional_float(item.get("change_pct")),
                indicators=IndicatorSnapshot(
                    ema5=_optional_float(indicators_raw.get("ema5")),
                    ema10=_optional_float(indicators_raw.get("ema10")),
                    ema21=_optional_float(indicators_raw.get("ema21")),
                    sma50=_optional_float(indicators_raw.get("sma50")),
                    sma200=_optional_float(indicators_raw.get("sma200")),
                    atr14=_optional_float(indicators_raw.get("atr14")),
                    rsi14=_optional_float(indicators_raw.get("rsi14")),
                    macd_histogram=_optional_float(indicators_raw.get("macd_histogram")),
                    macd=_macd_from_payload(indicators_raw.get("macd")),
                    return_20d=_optional_float(indicators_raw.get("return_20d")),
                    return_60d=_optional_float(indicators_raw.get("return_60d")),
                    average_volume_20=_optional_float(indicators_raw.get("average_volume_20")),
                ),
                trend=str(item.get("trend") or "数据不足"),
                technical_status=str(item.get("technical_status") or "中性"),
                supports=_zones_from_payload(item.get("supports")),
                resistances=_zones_from_payload(item.get("resistances")),
                invalidation_level=_optional_float(item.get("invalidation_level")),
                volume_ratio=_optional_float(item.get("volume_ratio")),
                volume_label=str(item.get("volume_label") or "成交量数据不足"),
                volume_confirmation=str(item.get("volume_confirmation") or "量价确认不足"),
                note=str(item.get("note") or ""),
                data_source=str(item.get("data_source") or ""),
                data_timestamp=str(item.get("data_timestamp") or ""),
                data_quality=str(item.get("data_quality") or "unknown"),
                asset_class=str(item.get("asset_class") or "equity"),
                position_weight_pct=_optional_float(item.get("position_weight_pct")),
                average_cost_gbp=_optional_float(item.get("average_cost_gbp")),
                unrealized_pnl_gbp=_optional_float(item.get("unrealized_pnl_gbp")),
                unrealized_pnl_pct=_optional_float(item.get("unrealized_pnl_pct")),
                scorecard=_scorecard_from_payload(item.get("scorecard")),
                structure=_structure_from_payload(item.get("structure")),
                warnings=tuple(str(value) for value in (item.get("warnings") or [])),
            )
        )
    return TechnicalSwingReport(
        generated_at=str(raw.get("generated_at") or datetime.now(timezone.utc).isoformat()),
        assessments=tuple(assessments),
        warnings=tuple(str(value) for value in (raw.get("warnings") or [])),
        summary=str(raw.get("summary") or ""),
    )


def render_technical_swing_html(report: TechnicalSwingReport) -> str:
    holding_cards = "".join(
        _standalone_card(item)
        for item in report.assessments
        if item.origin == "holding"
    ) or "<p>当前没有可分析的持仓。</p>"
    watch_cards = "".join(
        _standalone_card(item)
        for item in report.assessments
        if item.origin != "holding"
    ) or "<p>本次没有提供额外观察标的。</p>"
    warnings = "".join(f"<li>{escape(item)}</li>" for item in report.warnings[:20])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>技术波段观察</title>
</head>
<body style="margin:0;background:#0b1017;color:#e5e7eb;font-family:Arial,'Microsoft YaHei',sans-serif;">
  <main style="max-width:1080px;margin:0 auto;padding:28px 18px 48px;">
    <h1 style="margin:0 0 8px;color:#f8fafc;">技术波段观察</h1>
    <p style="color:#9ca3af;">{escape(report.summary)} 数据生成时间：{escape(report.generated_at)}</p>
    <p style="padding:12px;background:#111827;border:1px solid #334155;">本模块用于观察支撑、阻力、趋势确认与失效条件，不构成直接买卖指令。日线突破优先等待收盘与后续 2–3 个交易日确认。</p>
    <h2>持仓技术分析</h2>
    <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px;">{holding_cards}</section>
    <h2 style="margin-top:28px;">观察池技术分析</h2>
    <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px;">{watch_cards}</section>
    <h2 style="margin-top:28px;">数据质量与回退说明</h2>
    <ul>{warnings or "<li>未发现额外数据警告。</li>"}</ul>
  </main>
</body>
</html>"""


def render_technical_swing_email(
    report: TechnicalSwingReport,
) -> tuple[str, str, str]:
    report_date = report.generated_at[:10]
    subject = f"技术波段观察 - {report_date}"
    rows = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #334155;'><strong>{escape(item.symbol)}</strong></td>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;'>{escape(item.trend)}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;'>{escape(item.technical_status)}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;'>{escape(item.volume_label)}</td></tr>"
        for item in report.assessments
    )
    html = f"""<!doctype html><html lang="zh-CN"><body style="margin:0;background:#0b1017;color:#e5e7eb;font-family:Arial,'Microsoft YaHei',sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:720px;max-width:100%;background:#111827;border:1px solid #334155;">
<tr><td style="padding:20px;"><h1 style="margin:0 0 8px;color:#f8fafc;">技术波段观察</h1>
<p style="color:#9ca3af;">{escape(report.summary)}</p>
<table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:13px;">
<tr><th align="left" style="padding:8px;border-bottom:1px solid #64748b;">标的</th><th align="left">趋势</th><th align="left">状态</th><th align="left">量能</th></tr>{rows}</table>
<p style="color:#9ca3af;">完整技术分析已作为 HTML 附件提供；本模块仅用于风险观察和入场准备，不构成交易建议。</p>
</td></tr></table></td></tr></table></body></html>"""
    text = "\n".join(
        [subject, report.summary]
        + [
            f"- {item.symbol}: {item.trend}; {item.technical_status}; {item.volume_label}"
            for item in report.assessments
        ]
        + ["完整报告见 HTML 附件。"]
    )
    return subject, html, text


def write_technical_swing_report(
    report: TechnicalSwingReport, output_dir: Path
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_date = report.generated_at[:10]
    html_path = output_dir / f"technical-swing-report-{report_date}.html"
    json_path = output_dir / f"technical-swing-report-{report_date}.json"
    html_path.write_text(render_technical_swing_html(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return html_path, json_path


def _standalone_card(item: SwingAssessment) -> str:
    support = _nearest_zone(item.supports, item.current_price or 0, below=True)
    resistance = _nearest_zone(item.resistances, item.current_price or 0, below=False)
    support_text = _zone_text(support)
    resistance_text = _zone_text(resistance)
    zone_details = _render_zone_details("支撑", support, item.current_price)
    zone_details += _render_zone_details("阻力", resistance, item.current_price)
    price = f"{item.current_price:.2f}" if item.current_price is not None else "N/A"
    invalidation = (
        f"{item.invalidation_level:.2f}"
        if item.invalidation_level is not None
        else "不适用"
    )
    pnl = (
        f"<div>持仓盈亏：{item.unrealized_pnl_pct:+.2f}%</div>"
        if item.unrealized_pnl_pct is not None
        else ""
    )
    scorecard = (
        f"{item.scorecard.total_score}/20 · {escape(item.scorecard.interpretation)}"
        if item.scorecard
        else "N/A"
    )
    scorecard_breakdown = (
        " · ".join(item.scorecard.components)
        if item.scorecard and item.scorecard.components
        else "N/A"
    )
    raw_data = _standalone_raw_data(item)
    structure = ""
    if item.structure is not None:
        patterns = " · ".join(item.structure.bar_patterns) or "无特殊K线标签"
        structure = f"""<details open style="margin-top:10px;color:#d1d5db;font-size:13px;">
          <summary style="color:#bfdbfe;cursor:pointer;">透明结构诊断</summary>
          <div>周期：{escape(item.structure.short_term_state)} / {escape(item.structure.medium_term_state)} / {escape(item.structure.long_term_state)}</div>
          <div>阶段：{escape(item.structure.phase)}</div>
          <div>通道下/中/上：{_fmt_optional(item.structure.channel_lower)} / {_fmt_optional(item.structure.channel_mid)} / {_fmt_optional(item.structure.channel_upper)}</div>
          <div>延续倾向：{escape(item.structure.continuation_tendency)}；反转风险：{escape(item.structure.reversal_risk)}</div>
          <div>确认：{escape(item.structure.confirmation)}</div>
          <div>失效：{escape(item.structure.invalidation)}</div>
          <div>K线：{escape(patterns)}</div>
        </details>"""
    return f"""<article style="background:#111827;border:1px solid #334155;padding:14px;">
      <h3 style="margin:0 0 8px;color:#f8fafc;">{escape(item.symbol)} · {escape(item.technical_status)}</h3>
      <div>当前价格：{price} {escape(item.identity.currency)}</div>
      {pnl}
      <div>趋势：{escape(item.trend)}</div>
      <div>技术评分：{scorecard}</div>
      <div>评分拆解：{escape(scorecard_breakdown)}</div>
      <div>量能：{escape(item.volume_label)}；{escape(item.volume_confirmation)}</div>
      <div>最近支撑：{support_text}</div>
      <div>最近阻力：{resistance_text}</div>
      {raw_data}
      {structure}
      {zone_details}
      <div>ATR 失效参考：{invalidation}</div>
      <p style="color:#bfdbfe;">{escape(item.note)}</p>
      <div style="font-size:12px;color:#9ca3af;">{escape(item.data_source)} · {escape(item.data_timestamp)} · {escape(item.data_quality)}</div>
    </article>"""


def _zones_from_payload(raw: object) -> tuple[SwingZone, ...]:
    return tuple(
        SwingZone(
            kind=str(item.get("kind") or ""),
            lower=float(item.get("lower") or 0),
            upper=float(item.get("upper") or 0),
            score=int(item.get("score") or 0),
            touches=int(item.get("touches") or 0),
            components=tuple(str(value) for value in (item.get("components") or [])),
        )
        for item in (raw or [])
        if isinstance(item, dict)
    )


def _standalone_raw_data(item: SwingAssessment) -> str:
    indicators = item.indicators
    benchmark = item.scorecard.benchmark_return_20d if item.scorecard else None
    relative = item.scorecard.relative_strength_20d if item.scorecard else None
    rows = (
        ("EMA5 / EMA10 / EMA21", f"{_fmt_optional(indicators.ema5)} / {_fmt_optional(indicators.ema10)} / {_fmt_optional(indicators.ema21)}"),
        ("SMA50 / SMA200", f"{_fmt_optional(indicators.sma50)} / {_fmt_optional(indicators.sma200)}"),
        ("ATR14 / RSI14", f"{_fmt_optional(indicators.atr14)} / {_fmt_optional(indicators.rsi14)}"),
        ("MACD(10,23,8)", _fmt_macd_snapshot(indicators.macd)),
        ("20D / 60D / vs QQQ 20D", f"{_fmt_optional_pct(indicators.return_20d)} / {_fmt_optional_pct(indicators.return_60d)} / {_fmt_optional_pct(relative)}"),
        ("QQQ 20D基准", _fmt_optional_pct(benchmark)),
        ("成交量比 / 20日均量", f"{_fmt_optional(item.volume_ratio)}x / {_fmt_volume(indicators.average_volume_20)}"),
    )
    items = "".join(
        "<div style='display:flex;justify-content:space-between;gap:12px;border-top:1px solid #334155;padding:5px 0;'>"
        f"<span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in rows
    )
    return f"""<details open style="margin-top:10px;color:#d1d5db;font-size:13px;">
        <summary style="color:#bfdbfe;cursor:pointer;">Raw Technical Data</summary>
        {items}
      </details>"""


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _macd_from_payload(raw: object) -> MacdSnapshot | None:
    if not isinstance(raw, dict):
        return None
    try:
        return MacdSnapshot(
            fast=int(raw.get("fast") or 10),
            slow=int(raw.get("slow") or 23),
            signal=int(raw.get("signal") or 8),
            macd_line=float(raw.get("macd_line")),
            signal_line=float(raw.get("signal_line")),
            histogram=float(raw.get("histogram")),
            previous_histogram=_optional_float(raw.get("previous_histogram")),
            histogram_trend=str(raw.get("histogram_trend") or "unknown"),
            histogram_streak=int(raw.get("histogram_streak") or 0),
            cross=str(raw.get("cross") or "none"),
            position=str(raw.get("position") or "on_signal"),
        )
    except (TypeError, ValueError):
        return None


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _optional_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _scorecard_from_payload(raw: object) -> TechnicalScorecard | None:
    if not isinstance(raw, dict):
        return None
    return TechnicalScorecard(
        above_ema5=_optional_bool(raw.get("above_ema5")),
        above_ema10=_optional_bool(raw.get("above_ema10")),
        above_ema21=_optional_bool(raw.get("above_ema21")),
        above_sma50=_optional_bool(raw.get("above_sma50")),
        above_sma200=_optional_bool(raw.get("above_sma200")),
        trend_score=_optional_int(raw.get("trend_score")),
        momentum_score=_optional_int(raw.get("momentum_score")),
        breakout_score=_optional_int(raw.get("breakout_score")),
        total_score=_optional_int(raw.get("total_score")),
        benchmark_return_20d=_optional_float(raw.get("benchmark_return_20d")),
        relative_strength_20d=_optional_float(raw.get("relative_strength_20d")),
        regime=str(raw.get("regime") or "中性混合 / Neutral"),
        interpretation=str(raw.get("interpretation") or "数据不足"),
        components=tuple(
            str(component)
            for component in (raw.get("components") or ())
            if str(component).strip()
        ),
    )


def _structure_from_payload(raw: object) -> TechnicalStructureDiagnostic | None:
    if not isinstance(raw, dict):
        return None
    return TechnicalStructureDiagnostic(
        channel_window=_optional_int(raw.get("channel_window")),
        channel_lower=_optional_float(raw.get("channel_lower")),
        channel_mid=_optional_float(raw.get("channel_mid")),
        channel_upper=_optional_float(raw.get("channel_upper")),
        channel_position_pct=_optional_float(raw.get("channel_position_pct")),
        channel_slope_20d_pct=_optional_float(raw.get("channel_slope_20d_pct")),
        efficiency_ratio_20d=_optional_float(raw.get("efficiency_ratio_20d")),
        short_term_state=str(raw.get("short_term_state") or "数据不足"),
        medium_term_state=str(raw.get("medium_term_state") or "数据不足"),
        long_term_state=str(raw.get("long_term_state") or "数据不足"),
        phase=str(raw.get("phase") or "数据不足"),
        continuation_tendency=str(raw.get("continuation_tendency") or "数据不足"),
        reversal_risk=str(raw.get("reversal_risk") or "数据不足"),
        bar_patterns=tuple(str(value) for value in (raw.get("bar_patterns") or ()) if str(value).strip()),
        summary=str(raw.get("summary") or ""),
        confirmation=str(raw.get("confirmation") or ""),
        invalidation=str(raw.get("invalidation") or ""),
    )


def _fmt_optional(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "N/A"


def _fmt_optional_pct(value: float | None) -> str:
    return f"{value:+.2f}%" if value is not None else "N/A"


def _fmt_volume(value: float | None) -> str:
    return f"{value:,.0f}" if value is not None else "N/A"


def _fmt_macd_snapshot(snapshot: MacdSnapshot | None) -> str:
    if snapshot is None:
        return "N/A"
    cross = f"{snapshot.cross} cross" if snapshot.cross != "none" else snapshot.position
    streak = f" {snapshot.histogram_streak}D" if snapshot.histogram_streak else ""
    return f"Hist {snapshot.histogram:+.2f} {snapshot.histogram_trend}{streak} / {cross}"


def _zone_text(zone: SwingZone | None) -> str:
    if zone is None:
        return "N/A"
    return f"{zone.lower:.2f}–{zone.upper:.2f}（强度 {zone.score}/100）"


def _render_zone_details(label: str, zone: SwingZone | None, current_price: float | None) -> str:
    if zone is None:
        return ""
    components = "".join(f"<li>{escape(component)}</li>" for component in zone.components)
    if not components:
        components = "<li>组成项暂无明细</li>"
    distance = _zone_distance_text(zone, current_price)
    return f"""<details style="margin-top:8px;color:#9ca3af;font-size:12px;">
        <summary style="color:#bfdbfe;cursor:pointer;">{escape(label)}强度拆解</summary>
        <ul>
          <li>区间：{zone.lower:.2f}-{zone.upper:.2f}</li>
          <li>强度：{zone.score}/100</li>
          <li>触及次数：{zone.touches}</li>
          <li>距现价 {escape(distance)}</li>
          {components}
          <li>该强度用于衡量历史结构重要性，不是上涨概率、目标价或交易胜率。</li>
        </ul>
      </details>"""


def _zone_distance_text(zone: SwingZone, current_price: float | None) -> str:
    if current_price in (None, 0):
        return "N/A"
    if zone.lower <= current_price <= zone.upper:
        return "0.00%（现价位于区间内）"
    reference = zone.upper if current_price > zone.upper else zone.lower
    distance_pct = (reference / current_price - 1) * 100
    return f"{distance_pct:+.2f}%"


def _infer_asset_class(item: SwingUniverseItem) -> str:
    if item.symbol in {"ERNS.L"}:
        return "cash_like"
    return "equity"


def _nearest_zone(zones: Sequence[SwingZone], price: float, *, below: bool) -> SwingZone | None:
    candidates = [
        zone for zone in zones
        if (zone.lower <= price if below else zone.upper >= price)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda zone: abs(((zone.lower + zone.upper) / 2) - price))


def _zones_for_report(zones: Sequence[SwingZone], price: float, *, support: bool, limit: int = 3) -> tuple[SwingZone, ...]:
    if not zones:
        return ()
    nearest = _nearest_zone(zones, price, below=support)
    if support:
        filtered = [zone for zone in zones if zone.upper <= price * 1.03]
    else:
        filtered = [zone for zone in zones if zone.lower >= price * 0.97]

    selected: list[SwingZone] = []
    if nearest is not None and nearest in filtered:
        selected.append(nearest)
    for zone in filtered:
        if zone not in selected:
            selected.append(zone)
        if len(selected) >= limit:
            break
    return tuple(selected[:limit])


def _classify_status(
    price: float,
    change_pct: float | None,
    support: SwingZone | None,
    resistance: SwingZone | None,
    supports: Sequence[SwingZone],
    resistances: Sequence[SwingZone],
    volume_ratio: float | None,
    trend: str,
    asset_class: str,
) -> str:
    if asset_class == "cash_like":
        return "收益率与净值路径观察"
    broken_resistance = max(
        (zone for zone in resistances if price > zone.upper),
        key=lambda zone: zone.upper,
        default=None,
    )
    broken_support = min(
        (zone for zone in supports if price < zone.lower),
        key=lambda zone: zone.lower,
        default=None,
    )
    if broken_resistance and (volume_ratio or 0) > 1:
        return "突破候选"
    if broken_support and (volume_ratio or 0) > 1:
        return "支撑失效"
    if support and abs(price - support.upper) / price <= 0.02:
        return "接近支撑"
    if resistance and abs(resistance.lower - price) / price <= 0.02:
        return "接近阻力"
    if trend == "上升趋势中的回调":
        return "趋势回踩"
    if trend in {"中期动能转弱", "空头结构"}:
        return "趋势修复观察"
    if change_pct is not None and abs(change_pct) >= 3:
        return "波动扩张观察"
    return "中性"


def _volume_confirmation(change_pct: float | None, ratio: float | None) -> str:
    if change_pct is None or ratio is None:
        return "量价确认不足"
    if change_pct > 0 and ratio > 1.2:
        return "上涨伴随放量，动能确认较强"
    if change_pct > 0 and ratio < 0.7:
        return "上涨但成交偏低，需防弱反弹"
    if change_pct < 0 and ratio > 1.2:
        return "下跌伴随放量，卖压确认较强"
    if change_pct < 0 and ratio < 0.7:
        return "缩量回调，暂未形成强卖压确认"
    return "成交量处于常态区间"


def _risk_note(
    asset_class: str,
    trend: str,
    status: str,
    support: SwingZone | None,
    resistance: SwingZone | None,
) -> str:
    if asset_class == "cash_like":
        return "超短债应重点观察收益率、久期、派息与净值回补，不使用权益趋势破坏语言。"
    if status == "支撑失效":
        return "日线收盘已跌破支撑区且量能扩张，需等待重新站回或形成新的稳定区间。"
    if status == "突破候选":
        return "当前仅为突破候选，优先观察2至3个交易日能否守住原阻力区。"
    if support:
        return f"最近支撑区强度{support.score}/100；结合趋势与量能观察是否形成有效承接。"
    if resistance:
        return f"最近阻力区强度{resistance.score}/100；未确认突破前不应把盘中刺穿视为趋势成立。"
    return f"当前为{trend}，历史枢轴不足时应降低技术结论置信度。"
