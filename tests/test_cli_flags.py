from __future__ import annotations

import unittest

from market_report.cli import _merge_temporary_technical_tickers, build_parser


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


if __name__ == "__main__":
    unittest.main()
