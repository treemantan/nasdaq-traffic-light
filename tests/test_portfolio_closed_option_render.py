from __future__ import annotations

import json
import unittest

from market_report.etf_monitor import (
    PortfolioClosedOptionTrade,
    PortfolioPerformance,
    PortfolioPosition,
    _portfolio_performance_summary,
)
from market_report.render import _render_closed_option_trade_breakdown


class PortfolioClosedOptionRenderTests(unittest.TestCase):
    def test_closed_option_json_is_loaded_into_portfolio_performance(self) -> None:
        payload = [
            {
                "underlying": "NFLX",
                "expiry": "2026-07-24",
                "right": "P",
                "strike": 70,
                "legs": 2,
                "opened_at": "2026-06-16",
                "closed_at": "2026-06-22",
                "currency": "USD",
                "realized_pnl_native": 100.0,
                "realized_pnl_gbp": 74.5,
            }
        ]
        position = PortfolioPosition(
            symbol="NFLX",
            weight_pct=10,
            quantity=1,
            average_cost_gbp=100,
            current_price_gbp=90,
            market_value_gbp=90,
            unrealized_pnl_gbp=-10,
            unrealized_pnl_pct=-10,
            day_change_pct=0,
            monitor_status="outside-monitor-pool",
            _closed_option_trades_json=json.dumps(payload),
        )

        performance = _portfolio_performance_summary([position])

        self.assertIsNotNone(performance)
        assert performance is not None
        self.assertEqual(len(performance.closed_option_trades), 1)
        self.assertEqual(performance.closed_option_trades[0].underlying, "NFLX")
        self.assertAlmostEqual(performance.closed_option_trades[0].realized_pnl_gbp, 74.5)

    def test_closed_option_breakdown_is_rendered_separately_from_stock_fifo(self) -> None:
        performance = PortfolioPerformance(
            realized_pnl_gbp=74.5,
            closed_option_trades=(
                PortfolioClosedOptionTrade(
                    underlying="NFLX",
                    expiry="2026-07-24",
                    right="P",
                    strike=70,
                    opened_at="2026-06-16",
                    closed_at="2026-06-22",
                    legs=2,
                    currency="USD",
                    realized_pnl_native=100.0,
                    realized_pnl_gbp=74.5,
                ),
            ),
        )

        html = _render_closed_option_trade_breakdown(performance)

        self.assertIn("已平仓期权现金流归因", html)
        self.assertIn("NFLX", html)
        self.assertIn("70P", html)
        self.assertIn("+USD 100.00", html)
        self.assertIn("+£74.50", html)
        self.assertIn("已经计入上方", html)


if __name__ == "__main__":
    unittest.main()
