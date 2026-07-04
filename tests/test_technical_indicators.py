from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_report.technical_indicators import PriceBar, indicator_snapshot, macd_snapshot, true_ranges


def _bar(close: float, high: float | None = None, low: float | None = None, volume: float = 1000) -> PriceBar:
    return PriceBar(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=close,
        high=high if high is not None else close + 1,
        low=low if low is not None else close - 1,
        close=close,
        volume=volume,
    )


def test_true_ranges_use_previous_close() -> None:
    bars = (
        _bar(104, high=105, low=99),
        _bar(102, high=106, low=101),
    )
    assert true_ranges(bars) == pytest.approx((6, 5))


def test_indicator_snapshot_handles_short_history() -> None:
    snapshot = indicator_snapshot(tuple(_bar(100 + index) for index in range(10)))
    assert snapshot.ema5 is not None
    assert snapshot.ema10 is not None
    assert snapshot.ema21 is not None
    assert snapshot.sma50 is None
    assert snapshot.sma200 is None
    assert snapshot.atr14 is None
    assert snapshot.macd_histogram is None
    assert snapshot.macd is None
    assert snapshot.return_20d is None
    assert snapshot.return_60d is None
    assert snapshot.average_volume_20 is None


def test_indicator_snapshot_calculates_shared_values() -> None:
    bars = tuple(_bar(100 + index * 0.5, volume=1000 + index) for index in range(220))
    snapshot = indicator_snapshot(bars)
    assert snapshot.ema21 is not None
    assert snapshot.sma50 is not None
    assert snapshot.sma200 is not None
    assert snapshot.atr14 == pytest.approx(2)
    assert snapshot.rsi14 == pytest.approx(100)
    assert snapshot.macd_histogram is not None
    assert snapshot.macd is not None
    assert (snapshot.macd.fast, snapshot.macd.slow, snapshot.macd.signal) == (10, 23, 8)
    assert snapshot.return_20d == pytest.approx(((209.5 / 199.5) - 1) * 100)
    assert snapshot.return_60d == pytest.approx(((209.5 / 179.5) - 1) * 100)
    assert snapshot.average_volume_20 == pytest.approx(sum(range(1200, 1220)) / 20)


def test_macd_snapshot_describes_cross_and_histogram_trend() -> None:
    values = [
        100,
        99.8,
        99.6,
        99.4,
        99.2,
        99.0,
        98.8,
        98.6,
        98.4,
        98.2,
        98.0,
        97.8,
        97.6,
        97.4,
        97.2,
        97.0,
        96.8,
        96.6,
        96.4,
        96.2,
        96.0,
        95.8,
        95.6,
        95.4,
        95.2,
        96.8,
    ]

    snapshot = macd_snapshot(values, fast=3, slow=6, signal=3)

    assert snapshot is not None
    assert snapshot.cross == "bullish"
    assert snapshot.position == "above_signal"
    assert snapshot.histogram_trend == "expanding"
    assert snapshot.histogram_streak >= 1
