from __future__ import annotations

import unittest
from datetime import date, timedelta

from market_report.etf_monitor import (
    ETFSpec,
    _backtest_from_cache,
    _backtest_entry_environment,
    _backtest_to_cache,
    _adaptive_feature_scales,
    _cluster_similar_samples,
    _entry_similarity_features,
    _historical_driver_notes,
    _historical_macro_metrics,
    _fetch_fred_history,
    _rolling_sensitivities,
    _similar_samples,
    _similarity_confidence,
    _similar_stats,
)
from unittest.mock import patch


class ETFBacktestTests(unittest.TestCase):
    def test_historical_macro_metrics_do_not_look_past_as_of_date(self) -> None:
        histories = {
            "real_yield": [
                (date(2026, 7, 23), 1.9),
                (date(2026, 7, 24), 2.0),
                (date(2026, 7, 27), 2.8),
            ],
            "dxy": [(date(2026, 7, 23), 100), (date(2026, 7, 24), 101), (date(2026, 7, 27), 110)],
            "tnx": [(date(2026, 7, 23), 46.4), (date(2026, 7, 24), 47.0)],
        }

        metrics = _historical_macro_metrics(histories, date(2026, 7, 24))

        self.assertEqual(metrics["real_yield_10y"].value, 2.0)
        self.assertEqual(metrics["real_yield_10y"].previous_value, 1.9)
        self.assertEqual(metrics["dxy"].value, 101)
        self.assertEqual(metrics["treasury_10y"].value, 4.7)
        self.assertAlmostEqual(metrics["treasury_10y"].change, 0.06)

    def test_fetch_fred_history_parses_valid_rows_and_skips_missing_values(self) -> None:
        payload = "observation_date,DFII10\n2026-07-23,1.90\n2026-07-24,.\n2026-07-27,2.05\n"

        with patch("market_report.etf_monitor._read_text", return_value=payload):
            history = _fetch_fred_history("DFII10")

        self.assertEqual(history, [(date(2026, 7, 23), 1.9), (date(2026, 7, 27), 2.05)])

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
        self.assertGreater(stats.similar_phase_count, 0)
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

    def test_similarity_features_ignore_prices_after_historical_as_of_date(self) -> None:
        start = date(2020, 1, 1)
        history = []
        value = 100.0
        for index in range(330):
            value *= 1.0005
            history.append((start + timedelta(days=index), value))
        historical_window = history[:300]
        as_of = historical_window[-1][0]
        known_spy = [(day, close * 1.1) for day, close in history[:300]]
        future_spy = [
            (start + timedelta(days=index), 10_000.0 + index)
            for index in range(300, 330)
        ]

        features_without_future = _entry_similarity_features(
            ETFSpec("demo", "Demo ETF", "DEMO.L", "Demo", "Demo"),
            historical_window,
            market_histories={"spy": known_spy},
        )
        features_with_future = _entry_similarity_features(
            ETFSpec("demo", "Demo ETF", "DEMO.L", "Demo", "Demo"),
            historical_window,
            market_histories={"spy": known_spy + future_spy},
        )

        self.assertEqual(historical_window[-1][0], as_of)
        self.assertEqual(features_without_future, features_with_future)

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

    def test_similarity_stats_cluster_adjacent_samples_into_independent_phases(self) -> None:
        samples = [
            {
                "as_of": "2024-12-03",
                "distance": 0.67,
                "score": 70,
                "forward_1m": -0.17,
                "forward_3m": -3.48,
                "forward_6m": -3.30,
                "drawdown_3m": -6.13,
                "features": {"crowding_score": 76, "rsi14": 72, "mkt_vix_level": 14},
            },
            {
                "as_of": "2025-07-17",
                "distance": 0.50,
                "score": 78,
                "forward_1m": 1.70,
                "forward_3m": 6.85,
                "forward_6m": 12.32,
                "drawdown_3m": -2.11,
                "features": {},
            },
            {
                "as_of": "2025-07-24",
                "distance": 0.59,
                "score": 80,
                "forward_1m": 1.84,
                "forward_3m": 6.40,
                "forward_6m": 9.71,
                "drawdown_3m": -2.11,
                "features": {},
            },
        ]

        stats = _similar_stats(samples)

        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["phase_count"], 2)
        self.assertEqual(stats["tail_phase_count"], 1)
        self.assertAlmostEqual(stats["tail_phase_rate"], 50)
        self.assertAlmostEqual(stats["closest_tail_distance"], 0.67)
        self.assertAlmostEqual(stats["forward_3m"], (-3.48 + 6.85) / 2)
        rows = stats["samples"]
        self.assertTrue(rows[0].tail_case)
        self.assertTrue(rows[0].phase_representative)
        self.assertTrue(rows[1].phase_representative)
        self.assertFalse(rows[2].phase_representative)

    def test_tail_case_driver_notes_include_known_repricing_window(self) -> None:
        notes = _historical_driver_notes({"as_of": "2024-12-03"})

        self.assertTrue(any("Fed鹰派降息" in note for note in notes))
        self.assertTrue(any("DeepSeek冲击" in note for note in notes))
        self.assertTrue(any("关税不确定性" in note for note in notes))
        self.assertIn("不代表当前环境会重复同一路径", notes[-1])

    def test_similarity_phase_does_not_chain_across_long_period(self) -> None:
        samples = [
            {"as_of": "2025-01-01", "distance": 0.8},
            {"as_of": "2025-01-22", "distance": 0.7},
            {"as_of": "2025-02-12", "distance": 0.6},
            {"as_of": "2025-03-12", "distance": 0.5},
        ]

        phases = _cluster_similar_samples(samples)

        self.assertEqual(len(phases), 2)

    def test_adaptive_scales_are_bounded_around_protective_defaults(self) -> None:
        records = [
            {"features": {"score": float(index * 10), "momentum_1m": float(index)}}
            for index in range(30)
        ]

        scales = _adaptive_feature_scales(records)

        self.assertGreaterEqual(scales["score"], 7.5)
        self.assertLessEqual(scales["score"], 30)
        self.assertGreaterEqual(scales["momentum_1m"], 4)
        self.assertLessEqual(scales["momentum_1m"], 16)

    def test_similarity_candidates_with_low_feature_coverage_are_excluded(self) -> None:
        current = {"score": 70.0, "rsi14": 60.0, "momentum_1m": 4.0, "momentum_3m": 6.0}
        records = [
            {
                "as_of": "2025-01-01",
                "score": 70,
                "distance": 0,
                "features": {"score": 70.0},
            },
            {
                "as_of": "2025-02-01",
                "score": 70,
                "distance": 0,
                "features": dict(current),
            },
        ]

        samples = _similar_samples(records, current)

        self.assertEqual([item["as_of"] for item in samples], ["2025-02-01"])
        self.assertAlmostEqual(samples[0]["feature_coverage_pct"], 100)

    def test_similarity_confidence_requires_close_well_covered_independent_phases(self) -> None:
        self.assertEqual(_similarity_confidence(5, 0.80, 92), "历史可比性较高")
        self.assertEqual(_similarity_confidence(5, 1.30, 92), "历史可比性偏低")
        self.assertEqual(_similarity_confidence(2, 0.60, 100), "历史可比性偏低")

    def test_backtest_cache_preserves_phase_and_tail_metadata(self) -> None:
        stats = _similar_stats(
            [
                {
                    "as_of": "2024-12-03",
                    "distance": 0.67,
                    "score": 70,
                    "forward_1m": -0.17,
                    "forward_3m": -3.48,
                    "forward_6m": -3.30,
                    "drawdown_3m": -6.13,
                    "features": {"crowding_score": 76},
                }
            ]
        )
        from market_report.etf_monitor import ETFBacktestStats

        backtest = ETFBacktestStats(
            threshold=60,
            crowding_ceiling=70,
            sample_size=1,
            good_count=1,
            coverage_pct=100,
            good_forward_1m=-0.17,
            all_forward_1m=-0.17,
            good_forward_3m=-3.48,
            all_forward_3m=-3.48,
            good_forward_6m=-3.30,
            all_forward_6m=-3.30,
            good_hit_rate_3m=0,
            all_hit_rate_3m=0,
            good_max_drawdown_3m=-6.13,
            all_max_drawdown_3m=-6.13,
            reliability="样本偏少",
            summary="test",
            similar_count=stats["count"],
            similar_phase_count=stats["phase_count"],
            similar_tail_phase_count=stats["tail_phase_count"],
            similar_tail_phase_rate=stats["tail_phase_rate"],
            similar_closest_tail_distance=stats["closest_tail_distance"],
            similar_samples=stats["samples"],
        )

        restored = _backtest_from_cache(_backtest_to_cache(backtest))

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.similar_phase_count, 1)
        self.assertEqual(restored.similar_tail_phase_count, 1)
        self.assertAlmostEqual(restored.similar_tail_phase_rate or 0, 100)
        self.assertAlmostEqual(restored.similar_closest_tail_distance or 0, 0.67)
        self.assertEqual(restored.similar_samples[0].phase_id, "P1")
        self.assertTrue(restored.similar_samples[0].tail_case)
        self.assertTrue(restored.similar_samples[0].driver_notes)
