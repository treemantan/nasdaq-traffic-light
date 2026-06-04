from __future__ import annotations

import unittest

from market_report.etf_monitor import ETFMonitor, PortfolioPosition
from market_report.render_email import _render_portfolio_email


class PortfolioEmailRenderingTests(unittest.TestCase):
    def test_portfolio_section_uses_email_friendly_cards(self) -> None:
        monitor = ETFMonitor(
            summary="测试",
            assets=[],
            warnings=[],
            portfolio_positions=[
                PortfolioPosition(
                    symbol="RKLB",
                    weight_pct=7.38,
                    quantity=30.0,
                    average_cost_gbp=87.22,
                    current_price_gbp=85.41,
                    market_value_gbp=2562.37,
                    unrealized_pnl_gbp=-54.23,
                    unrealized_pnl_pct=-2.07,
                    day_change_pct=-6.99,
                    monitor_status="uncovered",
                    native_currency="USD",
                    current_price_native=114.70,
                    market_value_native=3441.0,
                    fx_pair="GBP/USD",
                    fx_rate=1.3429,
                    price_source="Yahoo quote:RKLB | FX:GBP/USD",
                    drawdown_from_year_peak_pct=-23.65,
                    peak_watch="趋势破坏风险：回撤较深且中期趋势或波动结构已转弱",
                )
            ],
            portfolio_total_value_gbp=34710.95,
        )

        html = _render_portfolio_email(monitor)

        self.assertIn("邮件友好的卡片布局", html)
        self.assertIn("RKLB", html)
        self.assertIn("Native市值", html)
        self.assertIn("GBP参考", html)
        self.assertIn("收益", html)
        self.assertIn("价格与风险观察", html)
        self.assertIn("组合占比", html)
        self.assertNotIn("<th", html)
        self.assertNotIn("距年内高点</th>", html)


if __name__ == "__main__":
    unittest.main()
