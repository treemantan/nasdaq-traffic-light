from __future__ import annotations

import unittest
from datetime import date, timedelta

from market_report.etf_monitor import (
    ETFSpec,
    _backtest_entry_environment,
    _entry_similarity_features,
    _rolling_sensitivities,
)


class ETFBacktestTests(unittest.TestCase):
    def test_etf_backtest_uses_threshold_and_forward_windows(self) -> None:
        start = date(2020, 1, 1)
        history = []
        value = 100.0
        for index in range(720):
            value *= 1.0007
            if index % 90 == 0:
                value *= 0.96
            history.append((start + timedelta(days=index), value))

        stats = _backtest_entry_environment(
            ETFSpec("demo", "Demo ETF", "DEMO.L", "Demo", "Demo"),
            history,
            threshold=60,
        )

        self.assertEqual(stats.threshold, 60)
        self.assertEqual(stats.crowding_ceiling, 70)
        self.assertGreater(stats.sample_size, 0)
        self.assertLessEqual(stats.good_count, stats.sample_size)
        self.assertIsNotNone(stats.all_forward_3m)
        self.assertGreater(stats.similar_count, 0)
        self.assertIsNotNone(stats.similar_forward_3m)
        self.assertIsNotNone(stats.similar_forward_3m_p50)
        self.assertGreater(len(stats.similar_samples), 0)
        self.assertTrue(stats.similar_samples[0].as_of)
        self.assertEqual([item.threshold for item in stats.threshold_calibrations], [60, 70, 75])
        self.assertEqual([item.crowding_ceiling for item in stats.threshold_calibrations], [70, 70, 70])
        self.assertTrue(stats.best_threshold_label)
        self.assertIn(stats.reliability, {"历史支持", "温和支持", "未验证优势", "样本偏少"})

    def test_similarity_features_include_market_environment_when_available(self) -> None:
        start = date(2020, 1, 1)
        history = []
        value = 100.0
        for index in range(330):
            value *= 1.0005
            history.append((start + timedelta(days=index), value))

        market_histories = {
            "spy": [(day, close * 1.1) for day, close in history],
            "vix": [(day, 18.0 + (index % 15) * 0.2) for index, (day, _) in enumerate(history)],
            "dxy": [(day, 100.0 + index * 0.01) for index, (day, _) in enumerate(history)],
        }

        features = _entry_similarity_features(
            ETFSpec("demo", "Demo ETF", "DEMO.L", "Demo", "Demo"),
            history,
            market_histories=market_histories,
        )

        self.assertIsNotNone(features)
        assert features is not None
        self.assertIn("mkt_spy_1m", features)
        self.assertIn("mkt_vix_level", features)
        self.assertIn("mkt_dxy_1m", features)

    def test_rolling_sensitivity_tracks_correlated_factor(self) -> None:
        start = date(2026, 1, 1)
        factor = []
        asset = []
        factor_value = 100.0
        asset_value = 50.0
        for index in range(90):
            move = 0.004 if index % 2 == 0 else -0.002
            factor_value *= 1 + move
            asset_value *= 1 + move * 1.5
            day = start + timedelta(days=index)
            factor.append((day, factor_value))
            asset.append((day, asset_value))

        sensitivities = _rolling_sensitivities(asset, {"qqq": factor})
        qqq = next(item for item in sensitivities if item.factor == "qqq")
        self.assertIsNotNone(qqq.correlation)
        self.assertGreater(qqq.correlation or 0, 0.99)
        self.assertAlmostEqual(qqq.beta or 0, 1.5, places=1)
