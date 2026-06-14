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
    ema21: float | None
    sma50: float | None
    sma200: float | None
    atr14: float | None
    rsi14: float | None
    average_volume_20: float | None


def sma(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def ema(values: Sequence[float], window: int) -> float | None:
    if not values or window <= 0:
        return None
    alpha = 2 / (window + 1)
    result = float(values[0])
    for value in values[1:]:
        result = alpha * float(value) + (1 - alpha) * result
    return result


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
        ema21=ema(closes, 21),
        sma50=sma(closes, 50),
        sma200=sma(closes, 200),
        atr14=atr(bars, 14),
        rsi14=rsi(closes, 14),
        average_volume_20=average_volume(bars, 20),
    )
