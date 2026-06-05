from __future__ import annotations

import tempfile
import unittest
import os
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from market_report.etf_monitor import (
    ETFAssetMonitor,
    ETFHolding,
    PortfolioPosition,
    ETFSpec,
    DEFAULT_ETF_SPECS,
    _audit_metadata,
    _asset_trend_label,
    _classify_portfolio_supplement,
    _entry_quality,
    _fetch_yahoo_price_data,
    _load_portfolio_summary,
    _parse_ishares_portfolio_valuation,
    _parse_compact_number,
    _portfolio_exposure_summary,
    _portfolio_mag7_summary,
    _with_portfolio_supplement_specs,
)
from market_report.news_monitor import NewsEvent, NewsMonitor
from market_report.render import _fmt_valuation_block, _group_etf_assets, _max_holdings_overlap, _portfolio_news_matches


class ETFProductCheckTests(unittest.TestCase):
    def test_yahoo_price_data_prefers_regular_market_quote(self) -> None:
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "currency": "GBP",
                            "regularMarketPrice": 138.91,
                            "regularMarketTime": 1780588800,
                        },
                        "timestamp": [1780444800],
                        "indicators": {"quote": [{"close": [138.64], "volume": [1000]}]},
                    }
                ]
            }
        }
        with patch("market_report.etf_monitor._read_json", return_value=payload):
            data = _fetch_yahoo_price_data("VWRL.L")

        self.assertEqual(data.history[-1][1], 138.91)
        self.assertEqual(data.meta["_price_source"], "regularMarketPrice")

    def test_erns_is_default_cash_like_etf(self) -> None:
        erns = next(spec for spec in DEFAULT_ETF_SPECS if spec.symbol == "ERNS.L")
        self.assertFalse(erns.equity_like)
        self.assertEqual(erns.theme, "GBP Ultrashort Bond / Cash-like")
        self.assertEqual(erns.ter, 0.09)

    def test_cash_like_etf_groups_and_valuation_copy_are_non_equity(self) -> None:
        asset = self._asset("ERNS.L", (), equity_like=False, theme="GBP Ultrashort Bond / Cash-like")
        groups = _group_etf_assets([asset])
        valuation, detail, pe_position = _fmt_valuation_block(asset)

        self.assertEqual(groups[0][0], "现金与短债")
        self.assertIn("久期/收益率/利率风险", valuation)
        self.assertNotIn("N/A", valuation)
        self.assertEqual(pe_position, "不适用")
        self.assertIn("收益率曲线", detail)

    def test_cash_like_entry_quality_does_not_use_200_day_trend_break(self) -> None:
        asset = self._asset(
            "ERNS.L",
            (),
            equity_like=False,
            theme="GBP Ultrashort Bond / Cash-like",
            value=98,
            sma200=100,
            momentum_1m=0.2,
            daily_sigma=0.3,
            aum=1_900_000_000,
            avg_traded_value_20d=5_000_000,
        )
        score, label, note, risk = _entry_quality(asset)

        self.assertGreaterEqual(score, 70)
        self.assertIn("现金替代", label)
        self.assertIn("不按200日均线", note)
        self.assertNotIn("趋势破坏", note + risk)

    def test_cash_like_trend_label_avoids_sma200_language(self) -> None:
        label = _asset_trend_label(
            ETFSpec("erns", "ERNS", "ERNS.L", "GBP Ultrashort Bond / Cash-like", "iShares", equity_like=False),
            98,
            99,
            99,
            100,
        )

        self.assertIn("不使用200日线", label)

    def test_portfolio_supplement_cash_like_metadata_is_auto_classified(self) -> None:
        theme, equity_like = _classify_portfolio_supplement(
            ETFSpec("portfolio-erns-l", "ERNS.L portfolio ETF holding", "ERNS.L", "Portfolio Supplement", "Portfolio"),
            {"longName": "iShares £ Ultrashort Bond UCITS ETF", "instrumentType": "ETF"},
        )

        self.assertEqual(theme, "GBP Ultrashort Bond / Cash-like")
        self.assertFalse(equity_like)

    def test_portfolio_lse_holding_extends_monitor_specs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                Path("portfolio.csv").write_text("symbol,weight_pct\nTEST.L,12\nMETA,5\n", encoding="utf-8")
                specs = _with_portfolio_supplement_specs([ETFSpec("base", "Base", "BASE.L", "Base", "Demo")])
            finally:
                os.chdir(previous)

        symbols = {spec.symbol for spec in specs}
        self.assertIn("TEST.L", symbols)
        self.assertNotIn("META.L", symbols)

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

    def test_portfolio_summary_flags_large_drawdown_from_year_peak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portfolio.csv"
            path.write_text(
                "symbol,weight_pct,drawdown_from_year_peak_pct\nA.L,100,-12.5\n",
                encoding="utf-8",
            )
            _, warnings, _, _ = _load_portfolio_summary([self._asset("A.L", ())], path)

        self.assertTrue(any("红色回撤观察" in item and "A.L -12.50%" in item for item in warnings))

    def test_cash_like_portfolio_position_uses_cash_like_drawdown_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portfolio.csv"
            path.write_text(
                "symbol,weight_pct,drawdown_from_year_peak_pct,distance_sma200_pct\nERNS.L,100,-0.2,-1.0\n",
                encoding="utf-8",
            )
            _, _, positions, _ = _load_portfolio_summary(
                [self._asset("ERNS.L", (), equity_like=False, theme="GBP Ultrashort Bond / Cash-like")],
                path,
            )

        self.assertIn("现金/短债", positions[0].drawdown_regime)

    def test_portfolio_summary_flags_high_beta_single_name_pullback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portfolio.csv"
            path.write_text(
                "symbol,weight_pct,drawdown_from_year_peak_pct,pullback_sigma_1m,monitor_status\nRKLB,10,-18,1.8,outside-monitor-pool\n",
                encoding="utf-8",
            )
            _, warnings, _, _ = _load_portfolio_summary([], path)

        self.assertTrue(any("高波动单票回撤观察" in item and "RKLB -18.00%" in item for item in warnings))

    def test_portfolio_summary_discloses_statement_cost_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portfolio.csv"
            path.write_text(
                "symbol,weight_pct,price_source\nA.L,100,statement-average-cost fallback\n",
                encoding="utf-8",
            )
            _, warnings, _, _ = _load_portfolio_summary([self._asset("A.L", ())], path)

        self.assertTrue(any("statement 平均成本降级估值" in item and "A.L" in item for item in warnings))

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

    def test_portfolio_mag7_summary_combines_direct_and_etf_lookthrough(self) -> None:
        asset = self._asset(
            "A.L",
            (
                ETFHolding("MSFT", "Microsoft Corp", 8),
                ETFHolding("AAPL", "Apple Inc", 6),
            ),
        )
        positions = [
            PortfolioPosition("A.L", 50, None, None, None, None, None, None, None, "covered"),
            PortfolioPosition("NVDA", 7, None, None, None, None, None, None, None, "outside-monitor-pool"),
        ]
        exposures, notes = _portfolio_mag7_summary([asset], positions)
        exposure_map = {item.symbol: item for item in exposures}

        self.assertEqual(exposure_map["MSFT"].weight_pct, 4)
        self.assertEqual(exposure_map["AAPL"].weight_pct, 3)
        self.assertEqual(exposure_map["NVDA"].weight_pct, 7)
        self.assertTrue(any("MAG7可识别暴露下限 14.0%" in item for item in notes))

    def test_portfolio_news_review_matches_direct_ticker_only(self) -> None:
        positions = [PortfolioPosition("NVDA", 10, None, None, None, None, None, None, None, "outside-monitor-pool")]
        monitor = NewsMonitor(
            fetched_at="2026-06-01T00:00:00Z",
            status="ok",
            summary="demo",
            warnings=(),
            events=(
                NewsEvent("NVIDIA update", "demo", "2026-06-01", "https://example.com/nvda", (), ("NVDA",), "neutral", "medium", "medium", "news"),
                NewsEvent("Apple update", "demo", "2026-06-01", "https://example.com/aapl", (), ("AAPL",), "neutral", "medium", "medium", "news"),
            ),
        )

        self.assertEqual([event.title for event in _portfolio_news_matches(positions, monitor)], ["NVIDIA update"])

    @staticmethod
    def _asset(
        symbol: str,
        holdings: tuple[ETFHolding, ...],
        ter: float = 0.10,
        equity_like: bool = True,
        theme: str = "Demo",
        value: float = 1,
        sma200: float | None = None,
        momentum_1m: float | None = None,
        daily_sigma: float | None = None,
        aum: float | None = None,
        avg_traded_value_20d: float | None = None,
    ) -> ETFAssetMonitor:
        return ETFAssetMonitor(
            key=symbol.lower(),
            label=symbol,
            symbol=symbol,
            theme=theme,
            provider="Demo",
            currency="GBP",
            value=value,
            previous_value=1,
            as_of=date(2026, 1, 1),
            fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            equity_like=equity_like,
            ter=ter,
            momentum_1m=momentum_1m,
            sma200=sma200,
            daily_sigma=daily_sigma,
            aum=aum,
            avg_traded_value_20d=avg_traded_value_20d,
            holdings=holdings,
        )


if __name__ == "__main__":
    unittest.main()
