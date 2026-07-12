from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


def _load_send_report_email_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "send_report_email.py"
    spec = importlib.util.spec_from_file_location("send_report_email", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SendReportEmailTests(unittest.TestCase):
    def test_lightweight_metric_lines_compute_change_from_previous_value(self) -> None:
        module = _load_send_report_email_module()
        payload = {
            "metrics": {
                "nasdaq": {"metric": {"value": 29120.98, "previous_value": 30407.81, "unit": ""}},
                "treasury_10y": {"metric": {"value": 4.551, "previous_value": 4.477, "unit": "%"}},
            }
        }

        self.assertEqual(module._metric_pct_line(payload, "nasdaq"), "-4.23%")
        self.assertEqual(module._metric_value_change_line(payload, "treasury_10y"), "4.551% / +0.074%")

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
            "news_monitor": {
                "fetched_at": "2026-05-27T21:14:00+01:00",
                "status": "正常",
                "summary": "新闻测试摘要。",
                "events": [
                    {
                        "title": "Trump tells crowd to buy a Dell computer",
                        "source": "Example",
                        "published_at": "2026-05-27",
                        "url": "https://example.com/dell",
                        "themes": ["半导体与AI基础设施"],
                        "tickers": ["DELL"],
                        "direction": "方向待确认",
                        "impact": "中",
                        "confidence": "中",
                        "source_type": "新闻聚合",
                    }
                ],
                "warnings": [],
                "used_cache": False,
            },
            "data_warnings": [],
            "data_quality": "正常",
            "data_health": {"core_cached": 0, "aux_missing": 0},
            "market_shock_backtest": {
                "triggered": True,
                "shock_type": "权益急跌 + 波动率扩散",
                "reliability": "历史可比性中等",
                "sample_count": 1,
                "independent_phase_count": 1,
                "avg_distance": 0.8,
                "forward_1d_avg": 1.0,
                "forward_5d_avg": -2.0,
                "forward_20d_avg": 3.0,
                "hit_rate_5d": 0.0,
                "drawdown_5d_avg": -4.0,
                "drawdown_20d_avg": -8.0,
                "tail_phase_count": 1,
                "tail_phase_rate": 100.0,
                "samples": [
                    {
                        "as_of": "2024-01-09",
                        "distance": 0.8,
                        "nasdaq_change_pct": -3.0,
                        "sp500_change_pct": -2.0,
                        "vix_change_pct": 18.0,
                        "vvix_change_pct": 12.0,
                        "dxy_change_pct": 0.5,
                        "forward_1d": 1.0,
                        "forward_5d": -2.0,
                        "forward_20d": 3.0,
                        "drawdown_5d": -4.0,
                        "drawdown_20d": -8.0,
                        "phase_id": "P1",
                        "phase_representative": True,
                    }
                ],
                "notes": ["匹配步骤不使用未来收益。"],
            },
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
        self.assertIn("LAYER 1 · DAILY DECISION BRIEF", html)
        self.assertIn("Trump tells crowd to buy a Dell computer", html)
        self.assertIn("DELL", html)
        self.assertIn("市场冲击历史类比", html)
        self.assertIn("2024-01-09", html)
        self.assertIn("email-optimized HTML", text)

    def test_serenity_package_includes_full_html_attachment(self) -> None:
        module = _load_send_report_email_module()
        payload = {
            "report_date": "2026-06-06",
            "regime": {"label": "Goldilocks", "summary": "测试。"},
            "etf_monitor": {
                "portfolio_positions": [
                    {
                        "symbol": "NVDA",
                        "weight_pct": 10,
                        "unrealized_pnl_pct": 5,
                        "drawdown_from_year_peak_pct": -3,
                        "distance_sma200_pct": 12,
                        "drawdown_regime": "常态波动",
                    }
                ]
            },
        }

        with TemporaryDirectory() as temp_dir:
            subject, html, text, attachments = module._render_serenity_package(
                payload, Path(temp_dir)
            )

        self.assertEqual(subject, "Serenity Portfolio Weekly - 2026-06-06")
        self.assertIn("私人持仓周度复核", html)
        self.assertIn("HTML附件", text)
        self.assertEqual(
            attachments[0]["filename"],
            "serenity-portfolio-report-2026-06-06.html",
        )
        self.assertIn("主要风险与反证", attachments[0]["content"])


    def test_technical_package_accepts_optional_empty_ticker_input(self) -> None:
        module = _load_send_report_email_module()
        payload = {
            "technical_swing": {
                "generated_at": "2026-06-14T12:00:00+00:00",
                "summary": "One holding assessed.",
                "assessments": [
                    {
                        "symbol": "MSFT",
                        "origin": "holding",
                        "identity": {
                            "requested_symbol": "MSFT",
                            "resolved_symbol": "MSFT",
                            "name": "Microsoft",
                            "exchange": "NMS",
                            "currency": "USD",
                            "instrument_type": "EQUITY",
                        },
                        "current_price": 500,
                        "change_pct": 1,
                        "indicators": {
                            "ema21": 490,
                            "sma50": 480,
                            "sma200": 430,
                            "atr14": 9,
                            "rsi14": 62,
                            "average_volume_20": 20_000_000,
                        },
                        "trend": "Strong",
                        "technical_status": "Near resistance",
                        "supports": [],
                        "resistances": [],
                        "invalidation_level": 470,
                        "volume_ratio": 1.1,
                        "volume_label": "Normal",
                        "volume_confirmation": "Normal volume",
                        "note": "Monitor confirmation.",
                        "data_source": "Yahoo",
                        "data_timestamp": "2026-06-13T20:00:00+00:00",
                        "data_quality": "live",
                        "asset_class": "equity",
                        "warnings": [],
                    }
                ],
                "warnings": [],
            }
        }

        with TemporaryDirectory() as temp_dir:
            subject, html, text, attachments = module._render_technical_package(
                payload, Path(temp_dir)
            )

        self.assertEqual(subject, "技术波段观察 - 2026-06-14")
        self.assertIn("MSFT", html)
        self.assertIn("HTML", text)
        self.assertEqual(
            attachments[0]["filename"],
            "technical-swing-report-2026-06-14.html",
        )

    def test_options_gamma_payload_rehydrates_for_renderer(self) -> None:
        module = _load_send_report_email_module()
        from market_report.render import _render_options_gamma

        monitor = module._options_gamma_from_payload(
            {
                "generated_at": "2026-05-27T21:14:30+01:00",
                "summary": "Options gamma test summary.",
                "assessments": [
                    {
                        "symbol": "QQQ",
                        "origin": "benchmark",
                        "spot_price": 530.25,
                        "nearest_expiry": "2026-05-29",
                        "regime_label": "Mixed / unclear",
                        "data_status": "available",
                        "call_wall": 540.0,
                        "put_wall": 520.0,
                        "near_spot_oi_strike": 530.0,
                        "largest_gamma_strike": 535.0,
                        "pin_strike": 530.0,
                        "gross_call_gamma": 1250000.0,
                        "gross_put_gamma": 980000.0,
                        "notable_flow": "OTM call flow elevated.",
                        "interpretation": "Dealer gamma estimate remains heuristic.",
                        "warnings": ["Gamma data is inferred."],
                    }
                ],
                "warnings": [],
            }
        )

        self.assertEqual(monitor.assessments[0].symbol, "QQQ")
        html = _render_options_gamma(monitor)
        self.assertIn("Options Gamma / Dealer Hedging", html)
        self.assertIn("QQQ", html)
        self.assertIn("Mixed / unclear", html)


if __name__ == "__main__":
    unittest.main()
