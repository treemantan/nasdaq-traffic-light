from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from market_report.config import _resolve_mag7_iv_tickers


class IVTickerConfigTests(unittest.TestCase):
    def test_momentum_override_appends_to_default_universe(self) -> None:
        with patch.dict(os.environ, {"MOMENTUM_IV_TICKERS": "CRWD, PLTR"}, clear=True):
            tickers = _resolve_mag7_iv_tickers()

        self.assertEqual(
            tickers,
            [
                "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
                "INTC", "AVGO", "MRVL", "NBIS", "BE", "CRWD", "PLTR",
            ],
        )

    def test_momentum_append_is_deduplicated_against_configured_universe(self) -> None:
        with patch.dict(os.environ, {"MOMENTUM_IV_TICKERS": "BE,CRWD,crwd"}, clear=True):
            tickers = _resolve_mag7_iv_tickers(["AAPL", "TSLA", "BE"])

        self.assertEqual(tickers, ["AAPL", "TSLA", "BE", "CRWD"])

    def test_blank_override_uses_configured_or_default_universe(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            configured = _resolve_mag7_iv_tickers(["AAPL", "TSLA", "BE"])
            defaulted = _resolve_mag7_iv_tickers()

        self.assertEqual(configured, ["AAPL", "TSLA", "BE"])
        self.assertEqual(defaulted[-5:], ["INTC", "AVGO", "MRVL", "NBIS", "BE"])

    def test_full_override_remains_highest_priority(self) -> None:
        with patch.dict(
            os.environ,
            {"MAG7_IV_TICKERS": "QQQ,SPY", "MOMENTUM_IV_TICKERS": "CRWD"},
            clear=True,
        ):
            tickers = _resolve_mag7_iv_tickers()

        self.assertEqual(tickers, ["QQQ", "SPY"])


if __name__ == "__main__":
    unittest.main()
