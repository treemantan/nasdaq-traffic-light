from __future__ import annotations

import unittest

from market_report.etf_monitor import PortfolioClosedTrade, PortfolioPerformance
from market_report.render_email import _render_closed_trade_breakdown_email
from market_report.render import _render_closed_trade_breakdown


class PortfolioClosedTradeRenderTests(unittest.TestCase):
    def test_closed_trade_breakdown_groups_all_lots_by_symbol_without_truncating(self) -> None:
        bnp_trades = (
            PortfolioClosedTrade("BNP", "2025-10-21", "2025-12-11", 51, 16.77441621, 999.87, 1121.5375, 1121.4599, 0.0776, 121.5899),
            PortfolioClosedTrade("BNP", "2025-10-28", "2025-12-11", 44, 16.88392857, 1000.29, 1128.8595, 1128.7814, 0.0781, 128.4914),
            PortfolioClosedTrade("BNP", "2025-10-28", "2025-12-11", 44, 42.11476895, 2463.06, 2815.7935, 2815.5987, 0.1947, 352.5387),
        )
        newer_trades = tuple(
            PortfolioClosedTrade(f"T{i}", "2026-01-01", "2026-06-01", 151, 1, 10, 11, 11, 0, 1)
            for i in range(12)
        )
        performance = PortfolioPerformance(closed_trades=newer_trades + bnp_trades)

        html = _render_closed_trade_breakdown(performance)

        self.assertIn("BNP", html)
        self.assertIn("3个已平仓批次", html)
        self.assertIn("+£602.62", html)
        self.assertEqual(html.count("2025-10-28"), 2)
        self.assertIn("GBP 会计口径", html)
        self.assertIn("FIFO成本/股GBP", html)

    def test_email_closed_trade_breakdown_groups_all_lots_by_symbol(self) -> None:
        trades = (
            PortfolioClosedTrade("BNP", "2025-10-21", "2025-12-11", 51, 16.77441621, 999.87, 1121.5375, 1121.4599, 0.0776, 121.5899),
            PortfolioClosedTrade("BNP", "2025-10-28", "2025-12-11", 44, 16.88392857, 1000.29, 1128.8595, 1128.7814, 0.0781, 128.4914),
            PortfolioClosedTrade("BNP", "2025-10-28", "2025-12-11", 44, 42.11476895, 2463.06, 2815.7935, 2815.5987, 0.1947, 352.5387),
        )
        performance = PortfolioPerformance(closed_trades=trades)

        html = _render_closed_trade_breakdown_email(performance)

        self.assertIn("BNP", html)
        self.assertIn("3个已平仓批次", html)
        self.assertIn("+£602.62", html)


if __name__ == "__main__":
    unittest.main()
