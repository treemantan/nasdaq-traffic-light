import unittest
from datetime import date, datetime, timezone

from market_report.data_sources import MarketMetric, MarketSnapshot, _scale_metric
from market_report.etf_monitor import ETFMonitor
from market_report.scoring import score_snapshot


def metric(
    key,
    label,
    value,
    previous,
    unit="",
    symbol="TEST",
    source="unit",
    category="macro",
    status="ok",
):
    return MarketMetric(
        key=key,
        label=label,
        description=label,
        symbol=symbol,
        source=source,
        value=value,
        previous_value=previous,
        as_of=date(2026, 5, 14),
        fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        unit=unit,
        category=category,
        status=status,
    )


class ScoringTests(unittest.TestCase):
    def test_score_snapshot_detects_higher_for_longer_context(self):
        snapshot = MarketSnapshot(
            as_of=date(2026, 5, 14),
            fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            metrics={
                "nasdaq": metric("nasdaq", "纳斯达克100", 26200, 26600, symbol="^NDX"),
                "sp500": metric("sp500", "标普500", 6000, 6040, symbol="^GSPC"),
                "vix": metric("vix", "VIX波动率", 19, 17, symbol="^VIX"),
                "treasury_10y": metric("treasury_10y", "美国10年期收益率", 4.59, 4.49, "%", "DGS10", "FRED"),
                "treasury_2y": metric("treasury_2y", "美国2年期收益率", 4.75, 4.70, "%", "DGS2", "FRED"),
                "real_yield_10y": metric("real_yield_10y", "10年期实际利率", 2.15, 2.08, "%", "DFII10", "FRED"),
                "dxy": metric("dxy", "美元指数DXY", 105.2, 104.5, symbol="DX-Y.NYB"),
                "gold": metric("gold", "黄金", 2300, 2325, symbol="GC=F"),
                "oil": metric("oil", "WTI原油", 80, 79, symbol="CL=F"),
            },
            warnings=(),
        )

        report = score_snapshot(snapshot, previous_regime="Goldilocks")

        self.assertGreaterEqual(report.overall_score, 0)
        self.assertLessEqual(report.overall_score, 100)
        self.assertEqual(report.regime.name, "Higher for Longer")
        self.assertIn("10年期美债收益率处于4.59%", report.regime.knowns[1])
        self.assertIn(report.light_label, {"绿灯", "黄灯", "红灯"})

    def test_treasury_yield_percentage_is_not_shifted(self):
        snapshot = MarketSnapshot(
            as_of=date(2026, 5, 14),
            fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            metrics={
                "nasdaq": metric("nasdaq", "纳斯达克100", 26200, 26600),
                "vix": metric("vix", "VIX波动率", 18, 18),
                "treasury_10y": metric("treasury_10y", "美国10年期收益率", 4.59, 4.55, "%"),
                "dxy": metric("dxy", "美元指数DXY", 104, 104),
            },
            warnings=(),
        )

        report = score_snapshot(snapshot)

        self.assertEqual(report.metrics["treasury_10y"].metric.value, 4.59)
        self.assertNotEqual(report.metrics["treasury_10y"].metric.value, 0.459)

    def test_yahoo_tnx_scaling_only_applies_to_legacy_large_quote(self):
        normal_quote = metric("treasury_10y", "美国10年期收益率", 4.59, 4.55, "%", "^TNX", "Yahoo fallback")
        legacy_quote = metric("treasury_10y", "美国10年期收益率", 45.9, 45.5, "%", "^TNX", "Yahoo fallback")

        self.assertEqual(normal_quote.value, 4.59)
        self.assertEqual(_scale_metric(legacy_quote, 0.1).value, 4.59)

    def test_cnn_fear_greed_scores_extreme_greed_as_crowding_risk(self):
        snapshot = MarketSnapshot(
            as_of=date(2026, 5, 14),
            fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            metrics={
                "nasdaq": metric("nasdaq", "纳斯达克100", 26200, 26600),
                "vix": metric("vix", "VIX波动率", 18, 18),
                "treasury_10y": metric("treasury_10y", "美国10年期收益率", 4.59, 4.55, "%"),
                "dxy": metric("dxy", "美元指数DXY", 104, 104),
                "gold": metric("gold", "黄金", 2300, 2310),
                "cnn_fear_greed": metric("cnn_fear_greed", "CNN恐惧与贪婪指数", 80, 72),
            },
            warnings=(),
        )

        report = score_snapshot(snapshot)

        self.assertEqual(report.metrics["cnn_fear_greed"].signal, "极端贪婪")
        self.assertIn("CNN恐惧与贪婪指数", report.regime.knowns[-1])


    def test_adaptive_weights_raise_financial_conditions_when_rates_and_dollar_tighten(self):
        snapshot = MarketSnapshot(
            as_of=date(2026, 5, 14),
            fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            metrics={
                "nasdaq": metric("nasdaq", "Nasdaq 100", 26200, 26600),
                "treasury_10y": metric("treasury_10y", "US 10Y", 4.6, 4.48, "%"),
                "treasury_2y": metric("treasury_2y", "US 2Y", 4.8, 4.7, "%"),
                "real_yield_10y": metric("real_yield_10y", "Real yield", 2.1, 2.0, "%"),
                "dxy": metric("dxy", "DXY", 105, 104.4),
                "gold": metric("gold", "Gold", 2300, 2320),
            },
            warnings=(),
        )

        report = score_snapshot(snapshot)

        self.assertGreater(report.weights["treasury_10y"], report.weights["treasury_2y"])
        self.assertGreater(report.weights["dxy"], report.weights["gold"])
        self.assertGreater(report.weights["nasdaq"], 0.14)

    def test_adaptive_weights_raise_hidden_tail_risk_when_vix_is_low_but_move_or_vvix_jump(self):
        snapshot = MarketSnapshot(
            as_of=date(2026, 5, 14),
            fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            metrics={
                "nasdaq": metric("nasdaq", "Nasdaq 100", 26200, 26300),
                "vix": metric("vix", "VIX", 18, 18),
                "vvix": metric("vvix", "VVIX", 98, 90),
                "move": metric("move", "MOVE", 95, 85),
                "credit_spread_hy": metric("credit_spread_hy", "HY spread", 3.1, 3.0, "%"),
                "treasury_10y": metric("treasury_10y", "US 10Y", 4.4, 4.39, "%"),
                "dxy": metric("dxy", "DXY", 103, 103),
            },
            warnings=(),
        )

        report = score_snapshot(snapshot)

        self.assertGreater(report.weights["move"], report.weights["vix"])
        self.assertGreater(report.weights["vvix"], 0.04)

    def test_move_note_reflects_direction_when_falling(self):
        snapshot = MarketSnapshot(
            as_of=date(2026, 5, 14),
            fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            metrics={
                "move": metric("move", "MOVE", 75, 78.5),
            },
            warnings=(),
        )

        report = score_snapshot(snapshot)
        scored = report.metrics["move"]

        self.assertIn("缓和", scored.signal)
        self.assertIn("回落", scored.note)
        self.assertNotIn("MOVE上行", scored.note)

    def test_iron_condor_filter_is_suitable_when_volatility_and_index_moves_are_contained(self):
        snapshot = MarketSnapshot(
            as_of=date(2026, 5, 14),
            fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            metrics={
                "nasdaq": metric("nasdaq", "Nasdaq 100", 10020, 10000),
                "sp500": metric("sp500", "S&P 500", 6006, 6000),
                "russell2000": metric("russell2000", "Russell 2000", 2202, 2200),
                "vix": metric("vix", "VIX", 18, 19),
                "vvix": metric("vvix", "VVIX", 90, 92),
                "move": metric("move", "MOVE", 95, 96),
                "credit_spread_hy": metric("credit_spread_hy", "HY spread", 3.0, 3.02, "%"),
                "treasury_10y": metric("treasury_10y", "US 10Y", 4.3, 4.31, "%"),
                "dxy": metric("dxy", "DXY", 103, 103.1),
            },
            warnings=(),
        )

        report = score_snapshot(snapshot)

        self.assertGreaterEqual(report.iron_condor.score, 75)
        self.assertEqual(report.iron_condor.label, "适合观察铁鹰 / Suitable")
        self.assertFalse(report.iron_condor.blockers)
        self.assertTrue(report.score_drivers)
        self.assertGreaterEqual(report.score_drivers[0].weighted_score, report.score_drivers[-1].weighted_score)

    def test_iron_condor_filter_blocker_overrides_numeric_score(self):
        snapshot = MarketSnapshot(
            as_of=date(2026, 5, 14),
            fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            metrics={
                "nasdaq": metric("nasdaq", "Nasdaq 100", 9990, 10000),
                "sp500": metric("sp500", "S&P 500", 5990, 6000),
                "vix": metric("vix", "VIX", 19, 19),
                "vvix": metric("vvix", "VVIX", 90, 91),
                "move": metric("move", "MOVE", 110, 90),
                "credit_spread_hy": metric("credit_spread_hy", "HY spread", 3.0, 3.0, "%"),
                "treasury_10y": metric("treasury_10y", "US 10Y", 4.3, 4.31, "%"),
                "dxy": metric("dxy", "DXY", 103, 103.1),
            },
            warnings=(),
        )

        report = score_snapshot(snapshot)

        self.assertEqual(report.iron_condor.label, "不适合铁鹰 / Unfavourable")
        self.assertTrue(report.iron_condor.blockers)

    def test_iron_condor_context_reduces_score_for_portfolio_trend_break(self):
        snapshot = MarketSnapshot(
            as_of=date(2026, 5, 14),
            fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            metrics={
                "nasdaq": metric("nasdaq", "Nasdaq 100", 10020, 10000),
                "sp500": metric("sp500", "S&P 500", 6006, 6000),
                "vix": metric("vix", "VIX", 18, 19),
                "vvix": metric("vvix", "VVIX", 90, 92),
                "move": metric("move", "MOVE", 95, 96),
                "credit_spread_hy": metric("credit_spread_hy", "HY spread", 3.0, 3.02, "%"),
                "treasury_10y": metric("treasury_10y", "US 10Y", 4.3, 4.31, "%"),
                "dxy": metric("dxy", "DXY", 103, 103.1),
            },
            warnings=(),
        )
        monitor = ETFMonitor(
            summary="demo",
            assets=[],
            warnings=[],
            portfolio_warnings=["趋势破坏风险复核：NFLX。"],
        )

        plain = score_snapshot(snapshot)
        contextual = score_snapshot(snapshot, etf_monitor=monitor)

        self.assertLess(contextual.iron_condor.score, plain.iron_condor.score)
        self.assertTrue(any("组合层面" in item for item in contextual.iron_condor.warnings))


if __name__ == "__main__":
    unittest.main()
