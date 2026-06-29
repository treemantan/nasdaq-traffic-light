from __future__ import annotations

from dataclasses import asdict
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

from market_report.event_risk_ledger import build_event_risk_ledger, _normalize_symbol
from market_report.news_monitor import NewsEvent, NewsMonitor
from market_report.policy_risk_monitor import build_policy_risk_monitor
from market_report.render import _render_event_risk_ledger as render_web_event_ledger
from market_report.render_email import _render_event_risk_ledger as render_email_event_ledger


def _load_send_report_email_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "send_report_email.py"
    spec = importlib.util.spec_from_file_location("send_report_email_event_ledger", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _event(
    title: str,
    *,
    themes: tuple[str, ...] = (),
    tickers: tuple[str, ...] = (),
    direction: str = "negative",
    impact: str = "high",
    confidence: str = "high",
    source_type: str = "official",
) -> NewsEvent:
    return NewsEvent(
        title=title,
        source="Test Source",
        published_at="2026-06-27T12:00:00+01:00",
        url="https://example.com/event",
        themes=themes,
        tickers=tickers,
        direction=direction,
        impact=impact,
        confidence=confidence,
        source_type=source_type,
    )


def _news_monitor(events: tuple[NewsEvent, ...]) -> NewsMonitor:
    return NewsMonitor(
        fetched_at="2026-06-27T12:00:00+01:00",
        status="ok",
        summary="test",
        events=events,
        warnings=(),
    )


class EventRiskLedgerTests(unittest.TestCase):
    def test_event_ledger_maps_policy_risk_to_portfolio_symbols(self) -> None:
        news = _news_monitor(
            (
                _event(
                    "Trump announces new semiconductor tariff and China export control review",
                    themes=("trade", "semiconductor"),
                    tickers=("NVDA", "AVGO"),
                ),
            )
        )
        policy = build_policy_risk_monitor(news)
        positions = (
            SimpleNamespace(symbol="NVDA", weight_pct=6.2, market_value_gbp=2200),
            SimpleNamespace(symbol="CNX1.L", weight_pct=7.1, market_value_gbp=2500),
        )

        ledger = build_event_risk_ledger(policy, news, positions)

        self.assertEqual(ledger.status, "ok")
        self.assertGreaterEqual(len(ledger.entries), 1)
        mapped = [entry for entry in ledger.entries if "NVDA" in entry.portfolio_symbols]
        self.assertGreaterEqual(len(mapped), 1)
        self.assertTrue(all(entry.portfolio_weight_pct == 6.2 for entry in mapped))
        self.assertIn("https://example.com/event", mapped[0].source_urls)
        self.assertEqual(mapped[0].market_confirmation, "待价格验证")

    def test_event_ledger_validates_against_cross_asset_market_action(self) -> None:
        news = _news_monitor(
            (
                _event(
                    "Trump announces new semiconductor tariff and China export control review",
                    themes=("trade", "semiconductor"),
                    tickers=("NVDA",),
                ),
            )
        )
        policy = build_policy_risk_monitor(news)
        metrics = {
            "nasdaq": SimpleNamespace(change_pct=-0.9),
            "sp500": SimpleNamespace(change_pct=-0.5),
            "dxy": SimpleNamespace(change_pct=0.3),
            "treasury_10y": SimpleNamespace(change=0.04),
            "vix": SimpleNamespace(change_pct=4.0),
        }

        ledger = build_event_risk_ledger(policy, news, (), metrics)

        self.assertEqual(ledger.entries[0].market_confirmation, "价格行为初步确认")
        self.assertIn("纳指100-0.90%", ledger.entries[0].validation_note)
        self.assertIn("DXY+0.30%", ledger.entries[0].validation_note)

    def test_event_ledger_degrades_when_no_policy_factor_exists(self) -> None:
        news = _news_monitor(())
        policy = build_policy_risk_monitor(news)

        ledger = build_event_risk_ledger(policy, news, ())

        self.assertEqual(ledger.status, "no_data")
        self.assertEqual(ledger.entries, ())

    def test_symbol_normalization_supports_common_market_suffixes(self) -> None:
        self.assertEqual(_normalize_symbol("DFNG.L"), "DFNG")
        self.assertEqual(_normalize_symbol("^VIX"), "VIX")
        self.assertEqual(_normalize_symbol("nvda"), "NVDA")

    def test_web_and_email_renderers_expose_ledger_entries(self) -> None:
        news = _news_monitor(
            (
                _event(
                    "White House considers AI chip export restrictions",
                    themes=("AI", "semiconductor"),
                    tickers=("NVDA",),
                ),
            )
        )
        ledger = build_event_risk_ledger(
            build_policy_risk_monitor(news),
            news,
            (SimpleNamespace(symbol="NVDA", weight_pct=6.2, market_value_gbp=2200),),
        )

        web_html = render_web_event_ledger(ledger)
        email_html = render_email_event_ledger(ledger)

        self.assertIn("NVDA", web_html)
        self.assertIn("NVDA", email_html)
        self.assertIn("6.2", web_html)
        self.assertIn("6.2", email_html)

    def test_event_ledger_exposes_lifecycle_for_merged_event_cluster(self) -> None:
        news = _news_monitor(
            (
                _event(
                    "Trump announces new semiconductor tariff and China export control review",
                    themes=("trade", "semiconductor"),
                    tickers=("NVDA",),
                ),
                _event(
                    "White House weighs further AI chip export restrictions",
                    themes=("trade", "AI", "semiconductor"),
                    tickers=("NVDA", "AVGO"),
                ),
            )
        )

        ledger = build_event_risk_ledger(build_policy_risk_monitor(news), news, ())

        self.assertGreaterEqual(len(ledger.entries), 1)
        entry = ledger.entries[0]
        self.assertTrue(entry.event_id)
        self.assertEqual(entry.lifecycle, "延续事件")
        self.assertEqual(entry.evidence_count, 2)
        self.assertIn(entry.event_id, render_web_event_ledger(ledger))
        self.assertIn("延续事件", render_email_event_ledger(ledger))

    def test_cloud_payload_reconstruction_preserves_event_risk_ledger(self) -> None:
        from market_report.scoring import IronCondorAssessment, RegimeAssessment, ScoredReport

        news = _news_monitor(
            (
                _event(
                    "Trump tariff risk hits AI semiconductor supply chains",
                    themes=("trade", "AI"),
                    tickers=("NVDA",),
                ),
            )
        )
        ledger = build_event_risk_ledger(
            build_policy_risk_monitor(news),
            news,
            (SimpleNamespace(symbol="NVDA", weight_pct=6.2, market_value_gbp=2200),),
        )
        report = ScoredReport(
            report_date="2026-06-27",
            fetched_at="2026-06-27T21:15:00+01:00",
            fetched_timezone="Europe/London",
            overall_score=50,
            light_label="yellow",
            light_color="#b7791f",
            headline="test",
            metrics={},
            weights={},
            summary="test",
            risks=[],
            action="watch",
            regime=RegimeAssessment("Test", "test", "Neutral", "Mixed", "Medium", 60, "mixed", "test", [], []),
            iron_condor=IronCondorAssessment(60, "neutral", "#b7791f", "test", [], [], []),
            etf_monitor=None,
            data_warnings=[],
            data_quality="normal",
            data_health={},
            event_risk_ledger=ledger,
        )

        restored = _load_send_report_email_module()._report_from_payload(asdict(report))

        self.assertIsNotNone(restored.event_risk_ledger)
        self.assertIn("NVDA", restored.event_risk_ledger.entries[0].portfolio_symbols)


if __name__ == "__main__":
    unittest.main()
