from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from market_report.options_sentiment import (
    OptionsSentimentConfig,
    build_options_sentiment_monitor,
    fetch_alpha_vantage_sentiment,
)


class OptionsSentimentTests(unittest.TestCase):
    def test_alpha_vantage_put_call_ratio_parses_short_premium_context(self) -> None:
        payload = {
            "symbol": "RKLB",
            "put_call_ratio_full_chain": "1.42",
            "put_call_ratio_by_expiration": [
                {"date": "2026-07-10", "value": "1.70"},
                {"date": "2026-07-17", "value": "0.95"},
            ],
        }

        with patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "demo"}, clear=False), patch(
            "market_report.options_sentiment._read_json", return_value=payload
        ):
            context = fetch_alpha_vantage_sentiment("RKLB", "holding", OptionsSentimentConfig())

        self.assertEqual(context.symbol, "RKLB")
        self.assertEqual(context.origin, "holding")
        self.assertAlmostEqual(context.put_call_ratio, 1.42)
        self.assertEqual(context.nearest_expiry, "2026-07-10")
        self.assertIn("Put-side", context.bias)
        self.assertTrue(context.expiration_ratios)

    def test_monitor_targets_benchmarks_holdings_and_watchlist(self) -> None:
        etf_monitor = SimpleNamespace(
            assets=[SimpleNamespace(symbol="SPY")],
            portfolio_positions=[SimpleNamespace(symbol="RKLB")],
        )

        seen: list[tuple[str, str]] = []

        def fake_fetcher(symbol: str, origin: str, config: OptionsSentimentConfig):
            seen.append((symbol, origin))
            return None

        monitor = build_options_sentiment_monitor(
            OptionsSentimentConfig(benchmark_tickers=("SPY",), tickers=("NVDA",)),
            etf_monitor,
            fetcher=fake_fetcher,
        )

        self.assertEqual(seen, [("SPY", "benchmark"), ("RKLB", "holding"), ("NVDA", "watchlist")])
        self.assertIn("3 tickers", monitor.summary)


if __name__ == "__main__":
    unittest.main()
