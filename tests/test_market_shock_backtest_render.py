from __future__ import annotations

import unittest

from market_report.render import _render_market_shock_backtest
from market_report.render_email import _render_market_shock_backtest as _render_email_market_shock_backtest
from market_report.shock_backtest import MarketShockBacktest, MarketShockSample


def _backtest() -> MarketShockBacktest:
    return MarketShockBacktest(
        triggered=True,
        shock_type="权益急跌 + 波动率扩张",
        reliability="历史可比性中等",
        sample_count=2,
        independent_phase_count=2,
        avg_distance=0.72,
        forward_1d_avg=1.2,
        forward_5d_avg=3.4,
        forward_20d_avg=-2.1,
        hit_rate_5d=50,
        drawdown_5d_avg=-4.2,
        drawdown_20d_avg=-8.5,
        tail_phase_count=1,
        tail_phase_rate=50,
        samples=(
            MarketShockSample(
                as_of="2024-01-09",
                distance=0.42,
                nasdaq_change_pct=-4.1,
                sp500_change_pct=-2.9,
                vix_change_pct=28,
                vvix_change_pct=16,
                dxy_change_pct=0.5,
                forward_1d=-1.0,
                forward_5d=5.0,
                forward_20d=-2.0,
                drawdown_5d=-1.0,
                drawdown_20d=-8.0,
                phase_id="P1",
                phase_representative=True,
            ),
        ),
        notes=("历史类比只使用候选日期当时已经可见的当日变化，不使用未来收益参与匹配。",),
    )


class MarketShockBacktestRenderTests(unittest.TestCase):
    def test_web_renderer_displays_samples_and_no_prediction_note(self) -> None:
        html = _render_market_shock_backtest(_backtest())

        self.assertIn("市场冲击历史类比", html)
        self.assertIn("2024-01-09", html)
        self.assertIn("不使用未来收益参与匹配", html)

    def test_email_renderer_displays_compact_summary(self) -> None:
        html = _render_email_market_shock_backtest(_backtest())

        self.assertIn("市场冲击历史类比", html)
        self.assertIn("权益急跌", html)
        self.assertIn("2024-01-09", html)


if __name__ == "__main__":
    unittest.main()
