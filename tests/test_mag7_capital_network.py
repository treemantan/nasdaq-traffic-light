from __future__ import annotations

from dataclasses import asdict
import importlib.util
from pathlib import Path
import unittest

from market_report.mag7_capital_network import build_mag7_capital_network
from market_report.render import _render_mag7_capital_network as render_web_network
from market_report.render_email import _render_mag7_capital_network as render_email_network


def _load_send_report_email_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "send_report_email.py"
    spec = importlib.util.spec_from_file_location("send_report_email_mag7", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Mag7CapitalNetworkTests(unittest.TestCase):
    def test_official_relationship_snapshot_covers_named_ai_links(self) -> None:
        network = build_mag7_capital_network()
        targets = {item.target_ticker for item in network.relations}

        self.assertTrue({"CRWV", "COHR", "LITE", "MRVL", "IREN"}.issubset(targets))
        self.assertIn("PRIVATE", targets)
        self.assertEqual(network.aggregate_disclosures[0].investor_ticker, "GOOGL")
        self.assertTrue(all(item.source_url.startswith("https://") for item in network.relations))
        self.assertTrue(any("可识别下限" in item for item in network.warnings))

    def test_web_and_email_renderers_disclose_scope(self) -> None:
        network = build_mag7_capital_network()

        web_html = render_web_network(network)
        email_html = render_email_network(network)

        self.assertIn("MAG7企业资本关系图谱", web_html)
        self.assertIn("NVIDIA · NVDA", web_html)
        self.assertIn("Alphabet · GOOGL", web_html)
        self.assertIn("可识别下限", email_html)
        self.assertIn("CoreWeave", email_html)

    def test_cloud_payload_reconstruction_preserves_network(self) -> None:
        from market_report.scoring import IronCondorAssessment, RegimeAssessment, ScoredReport

        report = ScoredReport(
            report_date="2026-06-01",
            fetched_at="2026-06-01T21:15:00+01:00",
            fetched_timezone="Europe/London",
            overall_score=50,
            light_label="黄灯",
            light_color="#b7791f",
            headline="测试。",
            metrics={},
            weights={},
            summary="测试。",
            risks=[],
            action="观察。",
            regime=RegimeAssessment("Test", "测试", "Neutral", "Mixed", "Medium", 60, "mixed", "测试", [], []),
            iron_condor=IronCondorAssessment(60, "中性", "#b7791f", "测试", [], [], []),
            etf_monitor=None,
            data_warnings=[],
            data_quality="正常",
            data_health={},
            mag7_capital_network=build_mag7_capital_network(),
        )

        restored = _load_send_report_email_module()._report_from_payload(asdict(report))

        self.assertIsNotNone(restored.mag7_capital_network)
        self.assertEqual(restored.mag7_capital_network.relations[0].investor_ticker, "MSFT")
        self.assertEqual(restored.mag7_capital_network.relations[0].themes, ("AI模型", "Azure", "云基础设施"))


if __name__ == "__main__":
    unittest.main()
