from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence


@dataclass(frozen=True)
class PriceBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class IndicatorSnapshot:
    ema5: float | None = None
    ema10: float | None = None
    ema21: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    atr14: float | None = None
    rsi14: float | None = None
    macd_histogram: float | None = None
    return_20d: float | None = None
    return_60d: float | None = None
    average_volume_20: float | None = None


def sma(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def ema_series(values: Sequence[float], window: int) -> tuple[float, ...]:
    if not values or window <= 0:
        return ()
    alpha = 2 / (window + 1)
    result = float(values[0])
    series = [result]
    for value in values[1:]:
        result = alpha * float(value) + (1 - alpha) * result
        series.append(result)
    return tuple(series)


def ema(values: Sequence[float], window: int) -> float | None:
    series = ema_series(values, window)
    return series[-1] if series else None


def macd_histogram(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> float | None:
    if min(fast, slow, signal) <= 0 or len(values) < slow + signal:
        return None
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    macd_line = tuple(fast_value - slow_value for fast_value, slow_value in zip(fast_series, slow_series))
    signal_series = ema_series(macd_line, signal)
    if not signal_series:
        return None
    return macd_line[-1] - signal_series[-1]


def period_return(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) <= window:
        return None
    base = values[-window - 1]
    if base == 0:
        return None
    return (values[-1] / base - 1) * 100


def rsi(values: Sequence[float], window: int = 14) -> float | None:
    if window <= 0 or len(values) <= window:
        return None
    changes = [current - previous for current, previous in zip(values[1:], values[:-1])]
    seed = changes[:window]
    average_gain = sum(max(change, 0) for change in seed) / window
    average_loss = sum(max(-change, 0) for change in seed) / window
    for change in changes[window:]:
        average_gain = ((window - 1) * average_gain + max(change, 0)) / window
        average_loss = ((window - 1) * average_loss + max(-change, 0)) / window
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def true_ranges(bars: Sequence[PriceBar]) -> tuple[float, ...]:
    ranges: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        if previous_close is None:
            value = bar.high - bar.low
        else:
            value = max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        ranges.append(value)
        previous_close = bar.close
    return tuple(ranges)


def wilder_average(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    result = sum(values[:window]) / window
    for value in values[window:]:
        result = ((window - 1) * result + value) / window
    return result


def atr(bars: Sequence[PriceBar], window: int = 14) -> float | None:
    return wilder_average(true_ranges(bars), window)


def average_volume(bars: Iterable[PriceBar], window: int = 20) -> float | None:
    volumes = [bar.volume for bar in bars if bar.volume is not None]
    if window <= 0 or len(volumes) < window:
        return None
    return sum(volumes[-window:]) / window


def indicator_snapshot(bars: Sequence[PriceBar]) -> IndicatorSnapshot:
    closes = [bar.close for bar in bars]
    return IndicatorSnapshot(
        ema5=ema(closes, 5),
        ema10=ema(closes, 10),
        ema21=ema(closes, 21),
        sma50=sma(closes, 50),
        sma200=sma(closes, 200),
        atr14=atr(bars, 14),
        rsi14=rsi(closes, 14),
        macd_histogram=macd_histogram(closes),
        return_20d=period_return(closes, 20),
        return_60d=period_return(closes, 60),
        average_volume_20=average_volume(bars, 20),
    )
