from __future__ import annotations

import unittest
from datetime import date, timedelta

from market_report.etf_monitor import ETFSpec, _backtest_entry_environment


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
        self.assertGreater(stats.sample_size, 0)
        self.assertLessEqual(stats.good_count, stats.sample_size)
        self.assertIsNotNone(stats.all_forward_3m)
        self.assertGreater(stats.similar_count, 0)
        self.assertIsNotNone(stats.similar_forward_3m)
        self.assertIn(stats.reliability, {"历史支持", "温和支持", "未验证优势", "样本偏少"})
