from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from market_report.data_sources import MarketMetric
from market_report.shock_backtest import analyze_market_shock_history


def _metric(key: str, value: float, previous: float) -> MarketMetric:
    return MarketMetric(
        key=key,
        label=key,
        description=key,
        symbol=key,
        source="test",
        value=value,
        previous_value=previous,
        as_of=date(2026, 6, 5),
        fetched_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )


def _history(start_value: float, moves: list[float]) -> list[tuple[date, float]]:
    rows = [(date(2024, 1, 1), start_value)]
    value = start_value
    for index, move in enumerate(moves, start=1):
        value *= 1 + move / 100
        rows.append((date(2024, 1, 1 + index), round(value, 4)))
    return rows


class MarketShockBacktestTests(unittest.TestCase):
    def test_finds_similar_shock_days_and_forward_paths(self) -> None:
        histories = {
            "nasdaq": _history(100, [0, -3.2, 1.0, 2.0, -0.5, 1.5, 0.8, -4.1, -1.0, 3.0, 2.0, 1.0]),
            "sp500": _history(100, [0, -2.2, 0.4, 1.0, -0.3, 0.6, 0.5, -2.9, -0.6, 1.5, 1.2, 0.7]),
            "vix": _history(15, [0, 20.0, -8.0, -5.0, 2.0, -4.0, -2.0, 28.0, 4.0, -10.0, -7.0, -4.0]),
            "vvix": _history(85, [0, 12.0, -4.0, -2.0, 1.0, -3.0, -1.0, 16.0, 2.0, -6.0, -5.0, -3.0]),
            "dxy": _history(100, [0, 0.6, -0.1, 0.0, 0.2, -0.1, 0.0, 0.5, 0.2, -0.2, 0.0, -0.1]),
        }
        metrics = {
            "nasdaq": _metric("nasdaq", 96.0, 100.0),
            "sp500": _metric("sp500", 97.0, 100.0),
            "vix": _metric("vix", 19.5, 15.0),
            "vvix": _metric("vvix", 98.6, 85.0),
            "dxy": _metric("dxy", 100.6, 100.0),
        }

        result = analyze_market_shock_history(metrics, histories=histories, max_samples=5, horizons=(2, 5))

        self.assertTrue(result.triggered)
        self.assertGreaterEqual(result.sample_count, 2)
        self.assertGreaterEqual(result.independent_phase_count, 2)
        self.assertEqual(result.samples[0].as_of, "2024-01-09")
        self.assertIsNotNone(result.forward_5d_avg)
        self.assertIsNotNone(result.drawdown_5d_avg)
        self.assertIn("权益急跌", result.shock_type)

    def test_no_trigger_returns_not_applicable(self) -> None:
        metrics = {
            "nasdaq": _metric("nasdaq", 100.2, 100.0),
            "sp500": _metric("sp500", 100.1, 100.0),
            "vix": _metric("vix", 14.8, 15.0),
        }

        result = analyze_market_shock_history(metrics, histories={})

        self.assertFalse(result.triggered)
        self.assertEqual(result.reliability, "未触发市场冲击")
        self.assertEqual(result.samples, ())


if __name__ == "__main__":
    unittest.main()
