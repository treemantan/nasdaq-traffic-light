from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from market_report.etf_monitor import (
    ETFAssetMonitor,
    ETFHolding,
    PortfolioPosition,
    ETFSpec,
    _audit_metadata,
    _load_portfolio_summary,
    _parse_ishares_portfolio_valuation,
    _parse_compact_number,
    _portfolio_exposure_summary,
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

    def test_parse_ishares_portfolio_valuation_with_disclosure_date(self) -> None:
        values = _parse_ishares_portfolio_valuation(
            """
            <div>P/E Ratio</div><div>as of 21/May/2026</div><div>46.17</div>
            <div>P/B Ratio</div><div>as of 21/May/2026</div><div>10.02</div>
            """
        )
        self.assertEqual(values["trailingPE"], 46.17)
        self.assertEqual(values["priceToBook"], 10.02)
        self.assertEqual(values["asOf"], "2026-05-21")

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

    def test_portfolio_exposure_combines_direct_and_etf_top_holdings(self) -> None:
        asset = self._asset("A.L", (ETFHolding("NVDA", "NVIDIA", 10), ETFHolding("AVGO", "Broadcom", 5)))
        positions = [
            PortfolioPosition("A.L", 40, None, None, None, None, None, None, None, "covered"),
            PortfolioPosition("NVDA", 6, None, None, None, None, None, None, None, "outside-monitor-pool"),
        ]
        exposures, notes = _portfolio_exposure_summary([asset], positions)
        exposure_map = {item.symbol: item for item in exposures}
        self.assertEqual(exposure_map["NVDA"].weight_pct, 10)
        self.assertEqual(exposure_map["NVDA"].direct_weight_pct, 6)
        self.assertEqual(exposure_map["NVDA"].etf_weight_pct, 4)
        self.assertTrue(any("可识别暴露下限" in item for item in notes))

    def test_portfolio_exposure_recognizes_korean_hbm_holdings_by_name(self) -> None:
        asset = self._asset(
            "FLRK.L",
            (
                ETFHolding("005930.KS", "Samsung Electronics Co Ltd", 25),
                ETFHolding("000660.KS", "SK hynix Inc", 12),
            ),
        )
        positions = [PortfolioPosition("FLRK.L", 40, None, None, None, None, None, None, None, "covered")]
        exposures, notes = _portfolio_exposure_summary([asset], positions)
        exposure_map = {item.symbol: item for item in exposures}
        self.assertEqual(exposure_map["005930"].weight_pct, 10)
        self.assertEqual(exposure_map["000660"].weight_pct, 4.8)
        self.assertTrue(any("HBM / 存储链" in item for item in notes))

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
