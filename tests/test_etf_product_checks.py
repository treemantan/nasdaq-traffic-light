from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from market_report.etf_monitor import (
    ETFAssetMonitor,
    ETFHolding,
    ETFSpec,
    _audit_metadata,
    _load_portfolio_summary,
    _parse_compact_number,
)
from market_report.render import _max_holdings_overlap


class ETFProductCheckTests(unittest.TestCase):
    def test_parse_compact_assets_value(self) -> None:
        self.assertEqual(_parse_compact_number("3.03B"), 3_030_000_000)

    def test_metadata_audit_rejects_wrong_semiconductor_mapping(self) -> None:
        status, note = _audit_metadata(
            ETFSpec("chip", "Semiconductor", "CHIP.L", "Semiconductor", "Demo"),
            {"exchangeName": "LSE", "instrumentType": "ETF", "longName": "China Market ETF"},
        )
        self.assertEqual(status, "异常")
        self.assertIn("Semiconductor", note)

    def test_overlap_uses_top_holdings_weights(self) -> None:
        holdings_a = (ETFHolding("NVDA", "NVIDIA", 10), ETFHolding("AMD", "AMD", 8))
        holdings_b = (ETFHolding("NVDA", "NVIDIA", 6), ETFHolding("AMD", "AMD", 3))
        assets = [self._asset("A.L", holdings_a), self._asset("B.L", holdings_b)]
        self.assertEqual(_max_holdings_overlap(assets), ("A.L", "B.L", 9))

    def test_portfolio_csv_generates_weighted_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portfolio.csv"
            path.write_text("symbol,weight_pct\nA.L,60\nB.L,40\n", encoding="utf-8")
            summary, warnings, positions, total = _load_portfolio_summary(
                [self._asset("A.L", (), ter=0.10), self._asset("B.L", (), ter=0.30)],
                path,
            )
        self.assertFalse(warnings)
        self.assertEqual(len(positions), 2)
        self.assertIsNone(total)
        self.assertTrue(any("组合加权TER约0.18%" in item for item in summary))

    @staticmethod
    def _asset(symbol: str, holdings: tuple[ETFHolding, ...], ter: float = 0.10) -> ETFAssetMonitor:
        return ETFAssetMonitor(
            key=symbol.lower(),
            label=symbol,
            symbol=symbol,
            theme="Demo",
            provider="Demo",
            currency="GBP",
            value=1,
            previous_value=1,
            as_of=date(2026, 1, 1),
            fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ter=ter,
            holdings=holdings,
        )


if __name__ == "__main__":
    unittest.main()
