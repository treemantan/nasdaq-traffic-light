from __future__ import annotations

from dataclasses import asdict
import importlib.util
from pathlib import Path
import unittest

from market_report.news_monitor import NewsEvent, NewsMonitor
from market_report.policy_risk_monitor import build_policy_risk_monitor
from market_report.render import _render_policy_risk_monitor as render_web_policy_risk


def _load_send_report_email_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "send_report_email.py"
    spec = importlib.util.spec_from_file_location("send_report_email_policy_risk", path)
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
    impact: str = "medium",
    confidence: str = "medium",
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


class PolicyRiskMonitorTests(unittest.TestCase):
    def test_tariff_and_export_control_news_raise_policy_risk(self) -> None:
        monitor = NewsMonitor(
            fetched_at="2026-06-27T12:00:00+01:00",
            status="ok",
            summary="test",
            events=(
                _event(
                    "Trump announces new semiconductor tariff and China export control review",
                    themes=("trade", "semiconductor"),
                    tickers=("NVDA", "AVGO"),
                    impact="high",
                    confidence="high",
                    source_type="official",
                ),
            ),
            warnings=(),
        )

        result = build_policy_risk_monitor(monitor)

        self.assertEqual(result.status, "ok")
        self.assertGreaterEqual(result.overall_score, 60)
        self.assertIn("policy risk", result.summary.lower())
        self.assertTrue(any(factor.key == "tariff_trade" for factor in result.factors))
        tariff_factor = next(factor for factor in result.factors if factor.key == "tariff_trade")
        self.assertEqual(tariff_factor.direction, "risk_up")
        self.assertIn("NVDA", tariff_factor.affected_tickers)
        self.assertIn("Semiconductors", tariff_factor.affected_assets)

    def test_conflicting_policy_events_mark_mixed_signals(self) -> None:
        monitor = NewsMonitor(
            fetched_at="2026-06-27T12:00:00+01:00",
            status="ok",
            summary="test",
            events=(
                _event(
                    "White House considers AI chip export restrictions",
                    themes=("AI", "semiconductor"),
                    impact="high",
                    confidence="high",
                ),
                _event(
                    "US officials discuss tariff exemptions for technology supply chains",
                    themes=("trade",),
                    direction="positive",
                    impact="medium",
                    confidence="medium",
                ),
            ),
            warnings=(),
        )

        result = build_policy_risk_monitor(monitor)

        self.assertEqual(result.status, "ok")
        self.assertTrue(any(factor.direction == "mixed" for factor in result.factors))
        self.assertGreaterEqual(result.overall_score, 40)

    def test_broad_aggregated_news_does_not_saturate_policy_score(self) -> None:
        monitor = NewsMonitor(
            fetched_at="2026-06-27T12:00:00+01:00",
            status="部分来源不可用",
            summary="test",
            events=tuple(
                _event(
                    f"Market report flags tariff uncertainty and semiconductor export controls {index}",
                    themes=("trade", "semiconductor"),
                    tickers=("NVDA", "AVGO", "AMD"),
                    impact="medium",
                    confidence="medium",
                    source_type="新闻聚合",
                )
                for index in range(6)
            ),
            warnings=("GDELT新闻聚合暂不可用：RuntimeError",),
        )

        result = build_policy_risk_monitor(monitor)

        self.assertLess(result.overall_score, 90)
        self.assertTrue(all(factor.score < 100 for factor in result.factors))
        tariff_factor = next(factor for factor in result.factors if factor.key == "tariff_trade")
        self.assertLessEqual(tariff_factor.score, 78)

    def test_empty_news_monitor_degrades_gracefully(self) -> None:
        monitor = NewsMonitor(
            fetched_at="2026-06-27T12:00:00+01:00",
            status="ok",
            summary="test",
            events=(),
            warnings=(),
        )

        result = build_policy_risk_monitor(monitor)

        self.assertEqual(result.status, "no_data")
        self.assertEqual(result.overall_score, 0)
        self.assertEqual(result.factors, ())

    def test_web_renderer_exposes_scores_and_evidence(self) -> None:
        result = build_policy_risk_monitor(
            NewsMonitor(
                fetched_at="2026-06-27T12:00:00+01:00",
                status="ok",
                summary="test",
                events=(
                    _event(
                        "Trump tariff risk hits AI semiconductor supply chains",
                        themes=("trade", "AI"),
                        tickers=("NVDA",),
                        impact="high",
                        confidence="high",
                    ),
                ),
                warnings=(),
            )
        )

        html = render_web_policy_risk(result)

        self.assertIn("政策与地缘事件风险雷达", html)
        self.assertIn("NVDA", html)
        self.assertIn("查看证据新闻", html)

    def test_cloud_payload_reconstruction_preserves_policy_risk_monitor(self) -> None:
        from market_report.scoring import IronCondorAssessment, RegimeAssessment, ScoredReport

        result = build_policy_risk_monitor(
            NewsMonitor(
                fetched_at="2026-06-27T12:00:00+01:00",
                status="ok",
                summary="test",
                events=(
                    _event(
                        "White House considers AI chip export restrictions",
                        themes=("AI", "semiconductor"),
                        tickers=("NVDA",),
                        impact="high",
                        confidence="high",
                    ),
                ),
                warnings=(),
            )
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
            policy_risk_monitor=result,
        )

        restored = _load_send_report_email_module()._report_from_payload(asdict(report))

        self.assertIsNotNone(restored.policy_risk_monitor)
        self.assertIn("NVDA", restored.policy_risk_monitor.factors[0].affected_tickers)


if __name__ == "__main__":
    unittest.main()
