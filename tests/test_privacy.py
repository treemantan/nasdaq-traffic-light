from __future__ import annotations

import unittest

from market_report.privacy import without_portfolio


class ReportPrivacyTests(unittest.TestCase):
    def test_without_portfolio_removes_private_fields_and_dynamic_assets(self) -> None:
        payload = {
            "portfolio_event_monitor": {"events": [{"event_id": "private-event"}]},
            "iron_condor": {
                "warnings": [
                    "组合层面已有红色回撤复核项。",
                    "MOVE上行，债券波动扩散。",
                ],
                "positives": ["波动率温和。"],
                "blockers": [],
            },
            "etf_monitor": {
                "assets": [
                    {"key": "vuag", "symbol": "VUAG.L", "provider": "Vanguard"},
                    {
                        "key": "portfolio-secret-l",
                        "symbol": "SECRET.L",
                        "provider": "Portfolio",
                        "theme": "Portfolio Supplement",
                    },
                ],
                "summary": ["VUAG.L 正常", "SECRET.L 动态加入观察池"],
                "warnings": ["SECRET.L 数据暂不可用"],
                "change_summary": ["SECRET.L 新增仓位环境变为70"],
                "portfolio_positions": [{"symbol": "SECRET.L", "quantity": 10}],
                "portfolio_summary": ["私人摘要"],
                "portfolio_warnings": ["私人预警"],
                "portfolio_total_value_gbp": 1234.0,
                "portfolio_performance": {"total_return_gbp": 12.0},
                "portfolio_exposures": [{"name": "AI"}],
                "portfolio_exposure_notes": ["私人暴露"],
                "portfolio_mag7_exposures": [{"name": "NVDA"}],
                "portfolio_mag7_notes": ["私人MAG7"],
            },
        }

        sanitized = without_portfolio(payload)

        self.assertIsNone(sanitized["portfolio_event_monitor"])
        self.assertEqual(
            [item["symbol"] for item in sanitized["etf_monitor"]["assets"]],
            ["VUAG.L"],
        )
        self.assertEqual(sanitized["etf_monitor"]["summary"], ["VUAG.L 正常"])
        self.assertEqual(sanitized["etf_monitor"]["warnings"], [])
        self.assertEqual(sanitized["etf_monitor"]["change_summary"], [])
        self.assertEqual(sanitized["etf_monitor"]["portfolio_positions"], [])
        self.assertIsNone(sanitized["etf_monitor"]["portfolio_total_value_gbp"])
        self.assertIsNone(sanitized["etf_monitor"]["portfolio_performance"])
        self.assertEqual(
            sanitized["iron_condor"]["warnings"],
            ["MOVE上行，债券波动扩散。"],
        )
        self.assertEqual(
            payload["etf_monitor"]["portfolio_positions"],
            [{"symbol": "SECRET.L", "quantity": 10}],
        )


if __name__ == "__main__":
    unittest.main()
