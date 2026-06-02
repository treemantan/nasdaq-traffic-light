from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "send_cloud_report_email.py"
    spec = importlib.util.spec_from_file_location("send_cloud_report_email", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SendCloudReportEmailTests(unittest.TestCase):
    def test_without_portfolio_removes_private_fields(self) -> None:
        module = _load_module()
        payload = {
            "portfolio_event_monitor": {"events": [{"event_id": "private-event"}]},
            "etf_monitor": {
                "portfolio_positions": [{"symbol": "VUAG"}],
                "portfolio_summary": ["summary"],
                "portfolio_warnings": ["warning"],
                "portfolio_total_value_gbp": 100.0,
                "portfolio_performance": {"total_return_gbp": 10.0},
                "portfolio_exposures": [{"name": "AI"}],
                "portfolio_exposure_notes": ["note"],
                "portfolio_mag7_exposures": [{"name": "NVDA"}],
                "portfolio_mag7_notes": ["mag7"],
            }
        }
        sanitized = module._without_portfolio(payload)
        self.assertEqual(sanitized["etf_monitor"]["portfolio_positions"], [])
        self.assertIsNone(sanitized["etf_monitor"]["portfolio_total_value_gbp"])
        self.assertIsNone(sanitized["etf_monitor"]["portfolio_performance"])
        self.assertEqual(sanitized["etf_monitor"]["portfolio_mag7_exposures"], [])
        self.assertIsNone(sanitized["portfolio_event_monitor"])
        self.assertEqual(payload["etf_monitor"]["portfolio_positions"], [{"symbol": "VUAG"}])

    def test_full_portfolio_run_sends_public_and_private_editions(self) -> None:
        module = _load_module()
        report = Path("output/market-report-2026-05-27.html")
        with patch.object(module.Path, "exists", return_value=True), patch.object(
            module, "_prepare_full_report", return_value=("resend", report, "<html>report</html>", {}, ["group@example.com"])
        ), patch.object(
            module.emailer, "_render_message", side_effect=[
                ("Public", "<html>public sanitized</html>", "public"),
                ("Private", "<html>private portfolio</html>", "private"),
            ]
        ), patch.object(module, "_send", return_value=0) as send, patch.dict(
            os.environ,
            {"EMAIL_MODE": "full", "PORTFOLIO_EMAIL_TO": "private@example.com"},
            clear=False,
        ):
            self.assertEqual(module.main(), 0)
            self.assertEqual(send.call_args_list[0].args[4], ["group@example.com"])
            self.assertEqual(send.call_args_list[1].args[4], ["private@example.com"])

    def test_full_portfolio_run_without_private_recipient_sends_sanitized_group_only(self) -> None:
        module = _load_module()
        report = Path("output/market-report-2026-05-27.html")
        with patch.object(module.Path, "exists", return_value=True), patch.object(
            module, "_prepare_full_report", return_value=("resend", report, "<html>report</html>", {}, ["group@example.com"])
        ), patch.object(
            module.emailer, "_render_message", return_value=("Public", "<html>public sanitized</html>", "public")
        ), patch.object(module, "_send", return_value=0) as send, patch.dict(
            os.environ,
            {"EMAIL_MODE": "full", "PORTFOLIO_EMAIL_TO": ""},
            clear=False,
        ):
            self.assertEqual(module.main(), 0)
            self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
