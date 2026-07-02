from __future__ import annotations

import unittest
from datetime import date, timedelta
import os
from types import SimpleNamespace
from unittest.mock import patch

from market_report.options_gamma import (
    OptionContract,
    OptionGammaAssessment,
    OptionsGammaConfig,
    OptionsGammaMonitor,
    assess_gamma_for_contracts,
    black_scholes_gamma,
    build_options_gamma_monitor,
    classify_trade_location,
    fetch_alpha_vantage_option_chain,
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
        self.assertEqual(assessment.data_status, "available")
        self.assertIn("OTM call", assessment.notable_flow)

    def test_seller_initiated_flow_returns_available_assessment(self) -> None:
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

        self.assertEqual(assessment.data_status, "available")
        self.assertEqual(assessment.call_wall, 500)
        self.assertEqual(assessment.put_wall, 490)

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

    def test_render_compacts_insufficient_gamma_items(self) -> None:
        def insufficient(symbol: str, warning: str) -> OptionGammaAssessment:
            return OptionGammaAssessment(
                symbol=symbol,
                origin="holding",
                spot_price=None,
                nearest_expiry="N/A",
                regime_label="insufficient",
                data_status="insufficient",
                call_wall=None,
                put_wall=None,
                near_spot_oi_strike=None,
                largest_gamma_strike=None,
                pin_strike=None,
                gross_call_gamma=0.0,
                gross_put_gamma=0.0,
                notable_flow="Options gamma data unavailable for this ticker today.",
                interpretation="Insufficient option-chain data for dealer hedging estimate.",
                warnings=[warning],
            )

        monitor = OptionsGammaMonitor(
            generated_at="2026-06-30T12:00:00+01:00",
            summary="Gamma monitor test",
            assessments=[
                insufficient("VUAG.L", "LSE/UK UCITS ticker has no usable Yahoo option chain"),
                insufficient("NVDA", "HTTP Error 401: Unauthorized"),
            ],
            warnings=["NVDA: options chain fetch failed: HTTP Error 401: Unauthorized"],
        )

        html = _render_options_gamma(monitor)

        self.assertIn("VUAG.L", html)
        self.assertIn("NVDA", html)
        self.assertIn("gamma-panel-compact", html)
        self.assertNotIn('<div class="gamma-grid">', html)
        self.assertNotIn('<div class="gamma-title">VUAG.L</div>', html)
        self.assertNotIn('<div class="gamma-title">NVDA</div>', html)
        self.assertNotIn("Spot / expiry</span><strong>N/A / N/A", html)

    def test_render_accepts_serialized_gamma_monitor(self) -> None:
        item = OptionGammaAssessment(
            symbol="NVDA",
            origin="holding",
            spot_price=None,
            nearest_expiry="N/A",
            regime_label="insufficient",
            data_status="insufficient",
            call_wall=None,
            put_wall=None,
            near_spot_oi_strike=None,
            largest_gamma_strike=None,
            pin_strike=None,
            gross_call_gamma=0.0,
            gross_put_gamma=0.0,
            notable_flow="Options gamma data unavailable for this ticker today.",
            interpretation="Insufficient option-chain data for dealer hedging estimate.",
            warnings=["HTTP Error 401: Unauthorized"],
        )
        payload = {
            "generated_at": "2026-06-30T12:00:00+01:00",
            "summary": "Serialized gamma monitor",
            "assessments": [item.__dict__],
            "warnings": ["NVDA: options chain fetch failed: HTTP Error 401: Unauthorized"],
        }

        html = _render_options_gamma(payload)

        self.assertIn("Serialized gamma monitor", html)
        self.assertIn("NVDA", html)
        self.assertIn("gamma-panel-compact", html)
        self.assertNotIn('<div class="gamma-title">NVDA</div>', html)

    def test_alpha_vantage_option_chain_normalizes_rows(self) -> None:
        expiry = (date.today() + timedelta(days=21)).isoformat()
        payload = {
            "data": [
                {
                    "contractID": "QQQ260717C00500000",
                    "type": "call",
                    "strike": "500",
                    "expiration": expiry,
                    "open_interest": "1,200",
                    "volume": "340",
                    "bid": "4.10",
                    "ask": "4.30",
                    "last": "4.25",
                    "implied_volatility": "0.31",
                    "underlying_price": "501.5",
                },
                {
                    "contractID": "QQQ260717P00490000",
                    "type": "put",
                    "strike": "490",
                    "expiration": expiry,
                    "openInterest": "900",
                    "volume": "120",
                    "bid": "3.00",
                    "ask": "3.20",
                    "lastPrice": "3.05",
                    "impliedVolatility": "31%",
                    "underlyingPrice": "501.5",
                },
            ]
        }

        with patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "demo"}, clear=False), patch(
            "market_report.options_gamma._read_json", return_value=payload
        ):
            spot, contracts, warnings = fetch_alpha_vantage_option_chain(
                "QQQ",
                OptionsGammaConfig(alpha_vantage_fetch_spot_quote=False, expirations_to_include=1),
            )

        self.assertEqual(spot, 501.5)
        self.assertEqual(len(contracts), 2)
        self.assertEqual(contracts[0].option_type, "call")
        self.assertEqual(contracts[0].open_interest, 1200)
        self.assertAlmostEqual(contracts[1].implied_volatility or 0, 0.31)
        self.assertTrue(any("Alpha Vantage" in warning for warning in warnings))

    def test_default_fetcher_falls_back_to_yahoo_after_alpha_failure(self) -> None:
        expiry = date.today() + timedelta(days=14)
        yahoo_contract = OptionContract("QQQ", "call", 500, expiry, 1000, 200, 1.0, 1.2, 1.19, 0.3)
        etf_monitor = SimpleNamespace(assets=[], portfolio_positions=[])

        with patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "demo"}, clear=False), patch(
            "market_report.options_gamma.fetch_alpha_vantage_option_chain", side_effect=RuntimeError("quota")
        ), patch(
            "market_report.options_gamma.fetch_yahoo_option_chain",
            return_value=(500.0, [yahoo_contract], ["Yahoo fallback"]),
        ):
            monitor = build_options_gamma_monitor(
                OptionsGammaConfig(
                    enabled=True,
                    benchmark_tickers=("QQQ",),
                    data_source_priority=("alpha_vantage", "yahoo"),
                ),
                etf_monitor,
            )

        self.assertEqual(len(monitor.assessments), 1)
        self.assertEqual(monitor.assessments[0].data_status, "available")
        self.assertTrue(any("Alpha Vantage" in warning for warning in monitor.assessments[0].warnings))
        self.assertTrue(any("Yahoo fallback" in warning for warning in monitor.assessments[0].warnings))

    def test_default_fetcher_falls_back_to_yahoo_after_alpha_empty_result(self) -> None:
        expiry = date.today() + timedelta(days=14)
        yahoo_contract = OptionContract("QQQ", "call", 500, expiry, 1000, 200, 1.0, 1.2, 1.19, 0.3)
        etf_monitor = SimpleNamespace(assets=[], portfolio_positions=[])

        with patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "demo"}, clear=False), patch(
            "market_report.options_gamma.fetch_alpha_vantage_option_chain",
            return_value=(500.0, [], ["Alpha Vantage returned no usable option contracts."]),
        ), patch(
            "market_report.options_gamma.fetch_yahoo_option_chain",
            return_value=(500.0, [yahoo_contract], ["Yahoo fallback"]),
        ):
            monitor = build_options_gamma_monitor(
                OptionsGammaConfig(
                    enabled=True,
                    benchmark_tickers=("QQQ",),
                    data_source_priority=("alpha_vantage", "yahoo"),
                ),
                etf_monitor,
            )

        self.assertEqual(len(monitor.assessments), 1)
        self.assertEqual(monitor.assessments[0].data_status, "available")
        self.assertTrue(any("no usable option contracts" in warning for warning in monitor.assessments[0].warnings))
        self.assertTrue(any("Yahoo fallback" in warning for warning in monitor.assessments[0].warnings))


if __name__ == "__main__":
    unittest.main()
