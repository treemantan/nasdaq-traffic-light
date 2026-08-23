from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from market_report.etf_monitor import ETFMonitor, PortfolioPosition
from market_report.mag7_iv_monitor import Mag7IVConfig, build_mag7_iv_monitor
from market_report.options_gamma import OptionContract, OptionsGammaConfig, fetch_yahoo_option_chain_near_dte
from market_report.render import _render_daily_portfolio_review, _render_mag7_iv_monitor
from market_report.render_email import _render_daily_portfolio_review_email, _render_mag7_iv_monitor_email


def _contracts(as_of: date, iv: float, *, expiry_days: int = 31) -> list[OptionContract]:
    expiry = as_of + timedelta(days=expiry_days)
    return [
        OptionContract("TSLA", "call", 100.0, expiry, 1000, 100, 4.0, 4.2, 4.1, iv),
        OptionContract("TSLA", "put", 100.0, expiry, 1000, 100, 3.8, 4.0, 3.9, iv + 0.02),
    ]


class Mag7IVMonitorTests(unittest.TestCase):
    @patch("market_report.options_gamma._read_json")
    def test_live_fetch_selects_only_expiry_nearest_30d(self, read_json) -> None:
        today = datetime.now(timezone.utc).date()
        epochs = [
            int(datetime.combine(today + timedelta(days=days), datetime.min.time(), tzinfo=timezone.utc).timestamp())
            for days in (7, 29, 60)
        ]
        read_json.side_effect = [
            {
                "optionChain": {
                    "result": [{"quote": {"regularMarketPrice": 100.0}, "expirationDates": epochs}]
                }
            },
            {
                "optionChain": {
                    "result": [
                        {
                            "options": [
                                {
                                    "calls": [{"strike": 100, "impliedVolatility": 0.3}],
                                    "puts": [{"strike": 100, "impliedVolatility": 0.32}],
                                }
                            ]
                        }
                    ]
                }
            },
        ]

        spot, contracts, warnings = fetch_yahoo_option_chain_near_dte(
            "TSLA", OptionsGammaConfig(max_days_to_expiry=75), target_dte=30
        )

        self.assertEqual(spot, 100.0)
        self.assertEqual(len(contracts), 2)
        self.assertFalse(warnings)
        self.assertIn(f"date={epochs[1]}", read_json.call_args_list[1].args[0])

    def test_low_rank_and_percentile_trigger_only_with_sufficient_history(self) -> None:
        as_of = date(2026, 8, 22)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mag7_iv_history.json"
            rows = [
                {"date": (as_of - timedelta(days=offset)).isoformat(), "atm_iv": 0.40 + offset / 1000}
                for offset in range(1, 22)
            ]
            path.write_text(json.dumps({"version": 1, "snapshots": {"TSLA": rows}}), encoding="utf-8")

            monitor = build_mag7_iv_monitor(
                Mag7IVConfig(tickers=("TSLA",), minimum_history_points=20, minimum_history_span_days=20),
                path,
                fetcher=lambda symbol, config: (100.0, _contracts(as_of, 0.20), []),
                as_of=as_of,
            )

            item = monitor.assessments[0]
            self.assertEqual(item.status, "low_iv_window")
            self.assertEqual(item.iv_rank, 0.0)
            self.assertEqual(item.iv_percentile, 0.0)
            self.assertAlmostEqual(item.atm_iv_pct or 0.0, 21.0)

    def test_history_gate_suppresses_false_low_iv_signal(self) -> None:
        as_of = date(2026, 8, 22)
        with tempfile.TemporaryDirectory() as folder:
            monitor = build_mag7_iv_monitor(
                Mag7IVConfig(tickers=("TSLA",), minimum_history_points=20, minimum_history_span_days=20),
                Path(folder) / "history.json",
                fetcher=lambda symbol, config: (100.0, _contracts(as_of, 0.20), []),
                as_of=as_of,
            )

            item = monitor.assessments[0]
            self.assertEqual(item.status, "building_history")
            self.assertIsNone(item.iv_rank)
            self.assertIsNone(item.iv_percentile)

    def test_nearest_30d_expiry_is_used_and_rendered(self) -> None:
        as_of = date(2026, 8, 22)
        contracts = _contracts(as_of, 0.70, expiry_days=7) + _contracts(as_of, 0.30, expiry_days=29)
        with tempfile.TemporaryDirectory() as folder:
            monitor = build_mag7_iv_monitor(
                Mag7IVConfig(
                    tickers=("TSLA",), minimum_history_points=1, minimum_history_span_days=0
                ),
                Path(folder) / "history.json",
                fetcher=lambda symbol, config: (100.0, contracts, []),
                as_of=as_of,
            )

            item = monitor.assessments[0]
            self.assertEqual(item.days_to_expiry, 29)
            self.assertAlmostEqual(item.atm_iv_pct or 0.0, 31.0)
            for rendered in (_render_mag7_iv_monitor(monitor), _render_mag7_iv_monitor_email(monitor)):
                self.assertIn("EOD 期权隐含波动率观察", rendered)
                self.assertIn("TSLA", rendered)
                self.assertIn("31.0%", rendered)

    def test_iv_monitor_is_rendered_inside_eod_review_with_distinct_groups(self) -> None:
        as_of = date(2026, 8, 22)
        with tempfile.TemporaryDirectory() as folder:
            monitor = build_mag7_iv_monitor(
                Mag7IVConfig(
                    tickers=("TSLA", "INTC"), minimum_history_points=1, minimum_history_span_days=0
                ),
                Path(folder) / "history.json",
                fetcher=lambda symbol, config: (100.0, _contracts(as_of, 0.30), []),
                as_of=as_of,
            )
            position = PortfolioPosition(
                symbol="TSLA",
                weight_pct=5.0,
                quantity=1.0,
                average_cost_gbp=100.0,
                current_price_gbp=100.0,
                market_value_gbp=100.0,
                unrealized_pnl_gbp=0.0,
                unrealized_pnl_pct=0.0,
                day_change_pct=0.0,
                monitor_status="uncovered",
                ibkr_data_status="live",
                ibkr_activity_as_of=date.today().isoformat(),
            )
            portfolio = ETFMonitor(
                summary="test",
                assets=[],
                warnings=[],
                portfolio_positions=[position],
                portfolio_total_value_gbp=2_000.0,
            )

            html = _render_daily_portfolio_review(portfolio, monitor)
            email = _render_daily_portfolio_review_email(portfolio, monitor)

            for rendered in (html, email):
                self.assertIn("每日 EOD 组合审视", rendered)
                self.assertIn("EOD 期权隐含波动率观察", rendered)
                self.assertIn("MAG7 IV", rendered)
                self.assertIn("动量股 IV", rendered)


if __name__ == "__main__":
    unittest.main()
