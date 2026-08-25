from __future__ import annotations

import json
import unittest
from datetime import date
from types import SimpleNamespace

from market_report.etf_monitor import ETFMonitor, PortfolioPosition
from market_report.portfolio_review import build_daily_portfolio_review
from market_report.render import _render_daily_portfolio_review
from market_report.render_email import _render_daily_portfolio_review_email
from market_report.technical_swing import SwingZone, TechnicalSwingReport


def _position(symbol: str, weight: float, **kwargs) -> PortfolioPosition:
    return PortfolioPosition(
        symbol=symbol,
        weight_pct=weight,
        quantity=kwargs.pop("quantity", 1.0),
        average_cost_gbp=100.0,
        current_price_gbp=100.0,
        market_value_gbp=weight * 100.0,
        unrealized_pnl_gbp=0.0,
        unrealized_pnl_pct=0.0,
        day_change_pct=0.0,
        monitor_status=kwargs.pop("monitor_status", "uncovered"),
        native_currency=kwargs.pop("native_currency", "USD"),
        current_price_native=kwargs.pop("current_price_native", 100.0),
        **kwargs,
    )


class DailyPortfolioReviewTests(unittest.TestCase):
    def test_fresh_pullback_above_sma200_becomes_conditional_add_candidate(self) -> None:
        positions = [
            _position(
                "MU",
                4.2,
                drawdown_from_year_peak_pct=-20.0,
                distance_sma200_pct=65.0,
                rsi14=45.0,
                support_20d_native=95.0,
                current_price_native=98.0,
                ibkr_data_status="manual-fallback",
                ibkr_activity_as_of="2026-08-21",
                ibkr_trade_as_of="2026-08-21",
            ),
            _position("VUAG.L", 20.0, drawdown_from_year_peak_pct=-2.0, distance_sma200_pct=8.0),
        ]

        review = build_daily_portfolio_review(positions, 30_000.0, as_of=date(2026, 8, 22))

        assert review is not None
        self.assertEqual(review.add_candidates[0].symbol, "MU")
        self.assertIn("$95.00", review.add_candidates[0].trigger)
        self.assertIn("时效合格", review.data_quality)

    def test_eod_add_trigger_reuses_technical_swing_support_zone(self) -> None:
        positions = [
            _position(
                "MU",
                4.2,
                drawdown_from_year_peak_pct=-20.0,
                distance_sma200_pct=65.0,
                rsi14=45.0,
                support_20d_native=739.0,
                current_price_native=925.0,
                ibkr_data_status="live",
                ibkr_activity_as_of="2026-08-25",
            )
        ]
        assessment = SimpleNamespace(
            symbol="MU",
            current_price=925.0,
            supports=(SwingZone("support", 889.54, 917.30, 80, 3, ("pivot",)),),
        )
        technical_swing = TechnicalSwingReport(
            generated_at="2026-08-25T21:00:00+00:00",
            assessments=(assessment,),
        )

        review = build_daily_portfolio_review(
            positions,
            30_000.0,
            as_of=date(2026, 8, 25),
            technical_swing=technical_swing,
        )

        assert review is not None
        self.assertIn("$889.54–917.30", review.add_candidates[0].trigger)
        self.assertIn("强度 80/100", review.add_candidates[0].trigger)
        self.assertNotIn("$739", review.add_candidates[0].trigger)

        monitor = ETFMonitor(
            summary="test",
            assets=[],
            warnings=[],
            portfolio_positions=positions,
            portfolio_total_value_gbp=30_000.0,
        )
        for rendered in (
            _render_daily_portfolio_review(monitor, technical_swing=technical_swing),
            _render_daily_portfolio_review_email(monitor, technical_swing=technical_swing),
        ):
            self.assertIn("$889.54–917.30", rendered)
            self.assertNotIn("$739", rendered)

    def test_stale_statement_suppresses_add_and_reduce_actions(self) -> None:
        positions = [
            _position(
                "MU",
                4.2,
                drawdown_from_year_peak_pct=-20.0,
                distance_sma200_pct=65.0,
                ibkr_activity_as_of="2026-08-10",
            )
        ]

        review = build_daily_portfolio_review(positions, 30_000.0, as_of=date(2026, 8, 22))

        assert review is not None
        self.assertEqual(review.add_candidates, ())
        self.assertEqual(review.reduce_candidates, ())
        self.assertIn("先更新并对账", review.most_important_action)

    def test_uncovered_short_put_is_promoted_to_maximum_risk(self) -> None:
        legs = [
            {
                "underlying": "COHR", "expiry": "2026-09-18", "right": "P",
                "strike": 240.0, "signed_contracts": -1.0, "multiplier": 100.0,
                "currency": "USD", "fx_rate_to_base": 0.74,
            }
        ]
        positions = [
            _position(
                "VUAG.L",
                20.0,
                option_legs_json=json.dumps(legs),
                ibkr_data_status="live",
                ibkr_activity_as_of="2026-08-21",
                drawdown_from_year_peak_pct=-2.0,
                distance_sma200_pct=8.0,
            )
        ]

        review = build_daily_portfolio_review(positions, 30_000.0, as_of=date(2026, 8, 22))

        assert review is not None
        self.assertIn("COHR", review.max_risk)
        self.assertIn("USD 24,000", review.max_risk)
        self.assertIn("£17,760", review.max_risk)
        self.assertIn("现金覆盖", review.most_important_action)

    def test_html_and_email_render_action_sections(self) -> None:
        monitor = ETFMonitor(
            summary="test",
            assets=[],
            warnings=[],
            portfolio_positions=[
                _position(
                    "MU",
                    4.2,
                    drawdown_from_year_peak_pct=-20.0,
                    distance_sma200_pct=65.0,
                    support_20d_native=95.0,
                    current_price_native=98.0,
                    ibkr_data_status="live",
                    ibkr_activity_as_of=date.today().isoformat(),
                )
            ],
            portfolio_total_value_gbp=30_000.0,
        )

        html = _render_daily_portfolio_review(monitor)
        email = _render_daily_portfolio_review_email(monitor)

        for rendered in (html, email):
            self.assertIn("每日 EOD 组合审视", rendered)
            self.assertIn("加仓观察", rendered)
            self.assertIn("减仓/风险处理", rendered)
            self.assertIn("数据截止", rendered)


if __name__ == "__main__":
    unittest.main()
