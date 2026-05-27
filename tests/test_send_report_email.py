from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_send_report_email_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "send_report_email.py"
    spec = importlib.util.spec_from_file_location("send_report_email", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SendReportEmailTests(unittest.TestCase):
    def test_full_mode_uses_email_optimized_renderer(self) -> None:
        module = _load_send_report_email_module()
        payload = {
            "report_date": "2026-05-27",
            "fetched_at": "2026-05-27T21:15:00+01:00",
            "fetched_timezone": "Europe/London",
            "overall_score": 41,
            "light_label": "黄灯",
            "light_color": "#b7791f",
            "headline": "跨资产信号进入观察区。",
            "metrics": {},
            "weights": {},
            "summary": "测试摘要。",
            "risks": [],
            "action": "保持观察。",
            "regime": {
                "name": "Test",
                "label": "测试宏观框架",
                "liquidity_regime": "Neutral",
                "yield_driver": "Mixed",
                "confidence": "Medium",
                "confidence_score": 70,
                "consistency": "mixed",
                "summary": "测试。",
                "knowns": [],
                "unknowns": [],
            },
            "iron_condor": {
                "score": 60,
                "label": "中性偏谨慎 / Neutral",
                "color": "#b7791f",
                "summary": "测试。",
                "positives": [],
                "warnings": [],
                "blockers": [],
            },
            "etf_monitor": None,
            "data_warnings": [],
            "data_quality": "正常",
            "data_health": {"core_cached": 0, "aux_missing": 0},
        }

        subject, html, text = module._render_message(
            "full",
            Path("output/market-report-2026-05-27.html"),
            "<html><style>.web-only{}</style><body>web page</body></html>",
            payload,
        )

        self.assertEqual(subject, "Macro Regime Radar - 2026-05-27")
        self.assertIn("Macro Regime Radar：宏观状态雷达", html)
        self.assertIn("background:#0b1017", html)
        self.assertNotIn("<style>", html)
        self.assertIn("email-optimized HTML", text)


if __name__ == "__main__":
    unittest.main()
