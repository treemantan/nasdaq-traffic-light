from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from market_report.options_gamma import (
    OptionContract,
    OptionsGammaConfig,
    assess_gamma_for_contracts,
    black_scholes_gamma,
    build_options_gamma_monitor,
    classify_trade_location,
    gamma_exposure,
)
from market_report.privacy import without_portfolio
from market_report.render import _render_options_gamma


class OptionsGammaTests(unittest.TestCase):
    def test_black_scholes_gamma_and_exposure_scale_with_open_interest(self) -> None:
        gamma = black_scholes_gamma(spot=100, strike=100, days_to_expiry=14, implied_volatility=0.35)

        low_oi = OptionContract("QQQ", "call", 100, date(2026, 7, 17), 100, 10, 1.0, 1.1, 1.05, 0.35)
        high_oi = OptionContract("QQQ", "call", 100, date(2026, 7, 17), 200, 10, 1.0, 1.1, 1.05, 0.35)

        self.assertGreater(gamma, 0)
        self.assertAlmostEqual(gamma_exposure(high_oi, 100), gamma_exposure(low_oi, 100) * 2, places=6)

    def test_trade_location_uses_bid_ask_bands(self) -> None:
        self.assertEqual(classify_trade_location(last_price=1.19, bid=1.0, ask=1.2), "ask")
        self.assertEqual(classify_trade_location(last_price=1.01, bid=1.0, ask=1.2), "bid")
        self.assertEqual(classify_trade_location(last_price=1.1, bid=1.0, ask=1.2), "mid")
        self.assertEqual(classify_trade_location(last_price=None, bid=1.0, ask=1.2), "unknown")

    def test_call_wall_put_wall_and_negative_gamma_from_otm_call_buying(self) -> None:
        contracts = [
            OptionContract("QQQ", "call", 105, date(2026, 7, 17), 300, 900, 1.0, 1.2, 1.2, 0.45),
            OptionContract("QQQ", "call", 110, date(2026, 7, 17), 1200, 120, 0.5, 0.6, 0.55, 0.42),
            OptionContract("QQQ", "put", 95, date(2026, 7, 17), 1000, 90, 1.1, 1.3, 1.2, 0.46),
        ]

        assessment = assess_gamma_for_contracts(
            "QQQ",
            "benchmark",
            100,
            contracts,
            generated_at="2026-06-27T12:00:00+01:00",
            min_volume_threshold=100,
            min_open_interest_threshold=100,
        )

        self.assertEqual(assessment.call_wall, 110)
        self.assertEqual(assessment.put_wall, 95)
        self.assertIn("负Gamma", assessment.regime_label)
        self.assertIn("OTM call", assessment.notable_flow)

    def test_seller_initiated_flow_can_flag_positive_gamma(self) -> None:
        contracts = [
            OptionContract("SPY", "call", 500, date(2026, 7, 17), 800, 700, 1.0, 1.2, 1.01, 0.25),
            OptionContract("SPY", "put", 490, date(2026, 7, 17), 600, 650, 1.0, 1.2, 1.01, 0.28),
        ]

        assessment = assess_gamma_for_contracts(
            "SPY",
            "benchmark",
            495,
            contracts,
            generated_at="2026-06-27T12:00:00+01:00",
            min_volume_threshold=100,
            min_open_interest_threshold=100,
        )

        self.assertIn("正Gamma", assessment.regime_label)

    def test_build_monitor_scope_uses_benchmarks_covered_etfs_and_holdings(self) -> None:
        seen: list[str] = []

        def fake_fetcher(symbol: str, config: OptionsGammaConfig):
            seen.append(symbol)
            return 100.0, [], ["mock unavailable"]

        etf_monitor = SimpleNamespace(
            assets=[SimpleNamespace(symbol="VUAG.L"), SimpleNamespace(symbol="QQQ")],
            portfolio_positions=[SimpleNamespace(symbol="NVDA"), SimpleNamespace(symbol="VUAG.L")],
        )

        monitor = build_options_gamma_monitor(
            OptionsGammaConfig(enabled=True, benchmark_tickers=("SPY", "QQQ")),
            etf_monitor,
            fetcher=fake_fetcher,
        )

        self.assertEqual(seen, ["SPY", "QQQ", "VUAG.L", "NVDA"])
        self.assertEqual([item.origin for item in monitor.assessments], ["benchmark", "benchmark", "covered_etf", "holding"])

    def test_render_and_privacy_filter_holding_gamma(self) -> None:
        monitor = build_options_gamma_monitor(
            OptionsGammaConfig(enabled=True, benchmark_tickers=("SPY",)),
            SimpleNamespace(assets=[], portfolio_positions=[SimpleNamespace(symbol="NVDA")]),
            fetcher=lambda symbol, config: (100.0, [], ["mock unavailable"]),
        )

        html = _render_options_gamma(monitor)
        self.assertIn("Options Gamma / Dealer Hedging", html)

        payload = {"options_gamma": {"assessments": [item.__dict__ for item in monitor.assessments], "summary": "x"}}
        sanitized = without_portfolio(payload)

        symbols = [item["symbol"] for item in sanitized["options_gamma"]["assessments"]]
        self.assertEqual(symbols, ["SPY"])


if __name__ == "__main__":
    unittest.main()
