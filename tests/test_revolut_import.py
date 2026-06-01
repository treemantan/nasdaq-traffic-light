from __future__ import annotations

import tempfile
import unittest
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_revolut_statement.py"
SPEC = spec_from_file_location("import_revolut_statement", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_reconstruct_positions = MODULE._reconstruct_positions


class RevolutImportTests(unittest.TestCase):
    def test_multiple_statements_are_combined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "isa.csv"
            second = Path(directory) / "general.csv"
            first.write_text(
                "Ticker,Type,Quantity,Price per share\n"
                "VUAG,BUY - MARKET,2,GBP 100\n",
                encoding="utf-8",
            )
            second.write_text(
                "Ticker,Type,Quantity,Price per share\n"
                "VUAG,BUY - MARKET,1,GBP 110\n",
                encoding="utf-8",
            )
            positions = _reconstruct_positions([first, second])

        self.assertEqual(positions["VUAG"]["quantity"], 3)
        self.assertEqual(positions["VUAG"]["cost_gbp"], 310)

    def test_usd_position_keeps_native_value_and_adds_gbp_reference(self) -> None:
        quotes = {
            "GBPUSD=X": (1.25, 1.24, "USD", []),
            "GBPEUR=X": (1.18, 1.17, "EUR", []),
            "NFLX": (
                100.0,
                90.0,
                "USD",
                [(date(2026, 1, 2), 120.0), (date(2026, 5, 29), 100.0)],
            ),
        }
        with patch.object(MODULE, "_latest_quote", side_effect=lambda symbol: quotes[symbol]):
            rows = MODULE._build_portfolio_rows({"NFLX": {"quantity": 2.0, "cost_gbp": 100.0}})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_currency"], "USD")
        self.assertEqual(rows[0]["current_price_native"], "100.0000")
        self.assertEqual(rows[0]["market_value_native"], "200.0000")
        self.assertEqual(rows[0]["estimated_market_value_gbp"], "160.00")
        self.assertEqual(rows[0]["fx_pair"], "GBP/USD")
        self.assertEqual(rows[0]["fx_rate"], "1.2500")
        self.assertEqual(rows[0]["drawdown_from_year_peak_pct"], "-16.6667")
        self.assertIn("红色观察", rows[0]["peak_watch"])

    def test_peak_watch_uses_current_calendar_year(self) -> None:
        peak, peak_date, drawdown = MODULE._year_peak_snapshot(
            [
                (date(2025, 12, 31), 200.0),
                (date(2026, 1, 2), 100.0),
                (date(2026, 5, 29), 96.0),
            ]
        )

        self.assertEqual(peak, 100.0)
        self.assertEqual(peak_date, date(2026, 1, 2))
        self.assertAlmostEqual(drawdown or 0, -4.0)
        self.assertIn("常态", MODULE._peak_watch_label(drawdown))


    def test_drawdown_regime_distinguishes_normal_pullback_from_trend_break(self) -> None:
        normal = MODULE._drawdown_regime_label(-8.0, 4.0, 1.2)
        broken = MODULE._drawdown_regime_label(-12.0, -4.0, 2.4)

        self.assertIn("正常回调观察", normal)
        self.assertIn("趋势破坏风险", broken)

    def test_portfolio_drawdown_snapshot_uses_sma200_and_robust_volatility(self) -> None:
        history = [
            (date(2025, 1, 1), 100 + index * 0.2 + (index % 5 - 2))
            for index in range(220)
        ]
        snapshot = MODULE._portfolio_drawdown_snapshot(history, -6.0)

        self.assertIsNotNone(snapshot[0])
        self.assertIsNotNone(snapshot[1])
        self.assertIsNotNone(snapshot[2])
        self.assertIsNotNone(snapshot[3])


if __name__ == "__main__":
    unittest.main()
