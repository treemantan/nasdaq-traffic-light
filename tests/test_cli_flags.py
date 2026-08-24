from __future__ import annotations

import unittest
from types import SimpleNamespace

from market_report.cli import _eod_technical_watchlist, _merge_temporary_technical_tickers, build_parser


class CliFlagTests(unittest.TestCase):
    def test_technical_tickers_accept_comma_list_and_repeated_flag(self) -> None:
        args = build_parser().parse_args(
            [
                "--technical-tickers", "CRWD, PLTR",
                "--technical-ticker", "NBIS",
                "--technical-tickers", "crwd",
            ]
        )

        tickers = _merge_temporary_technical_tickers(args.technical_tickers)

        self.assertEqual(tickers, ("CRWD", "PLTR", "NBIS"))

    def test_cli_tickers_merge_with_environment_without_duplicates(self) -> None:
        tickers = _merge_temporary_technical_tickers(["CRWD,PLTR"], "TSLA,CRWD")

        self.assertEqual(tickers, ("TSLA", "CRWD", "PLTR"))

    def test_eod_technical_watchlist_always_includes_monitored_gold_etfs(self) -> None:
        monitor = SimpleNamespace(
            assets=(
                SimpleNamespace(symbol="SGLN.L", theme="Gold"),
                SimpleNamespace(symbol="PHAU.L", theme="Gold"),
                SimpleNamespace(symbol="SGBX.L", theme="Gold"),
                SimpleNamespace(symbol="VWRL.L", theme="Global Equity"),
            )
        )

        tickers = _eod_technical_watchlist(("CRWD", "SGLN.L"), monitor)

        self.assertEqual(tickers, ("CRWD", "SGLN.L", "PHAU.L", "SGBX.L"))


if __name__ == "__main__":
    unittest.main()
