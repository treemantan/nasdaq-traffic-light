from __future__ import annotations

from pathlib import Path
import unittest

from market_report.serenity_report import build_serenity_report, render_serenity_html


def _payload() -> dict:
    return {
        "report_date": "2026-06-06",
        "overall_score": 58,
        "light_label": "黄灯",
        "regime": {
            "label": "Higher for Longer",
            "confidence_score": 72,
            "summary": "长端收益率与美元仍对成长资产形成约束。",
        },
        "risks": ["实际利率仍处于高位。"],
        "etf_monitor": {
            "portfolio_total_value_gbp": 25000,
            "portfolio_summary": ["组合加权TER约0.15%。"],
            "portfolio_warnings": [
                "红色回撤观察：NFLX、META。",
                "趋势破坏风险复核：NFLX。",
            ],
            "portfolio_positions": [
                {
                    "symbol": "VUAG.L",
                    "weight_pct": 30,
                    "unrealized_pnl_pct": 10,
                    "drawdown_from_year_peak_pct": -1,
                    "distance_sma200_pct": 11,
                    "drawdown_regime": "常态波动",
                    "price_source": "Yahoo quote:VUAG.L",
                },
                {
                    "symbol": "NFLX",
                    "weight_pct": 8,
                    "unrealized_pnl_pct": -17,
                    "drawdown_from_year_peak_pct": -22,
                    "red_drawdown_threshold_pct": 15,
                    "distance_sma200_pct": -19,
                    "drawdown_regime": "趋势破坏风险",
                    "price_source": "Yahoo quote:NFLX",
                },
                {
                    "symbol": "META",
                    "weight_pct": 6,
                    "unrealized_pnl_pct": -5,
                    "drawdown_from_year_peak_pct": -18,
                    "red_drawdown_threshold_pct": 15,
                    "distance_sma200_pct": -8,
                    "drawdown_regime": "趋势破坏风险",
                    "price_source": "Yahoo quote:META",
                },
                {
                    "symbol": "NVDA",
                    "weight_pct": 5,
                    "unrealized_pnl_pct": 23,
                    "drawdown_from_year_peak_pct": -4,
                    "distance_sma200_pct": 28,
                    "drawdown_regime": "常态波动",
                    "price_source": "Yahoo quote:NVDA",
                },
                {
                    "symbol": "SEMI.L",
                    "weight_pct": 10,
                    "unrealized_pnl_pct": 19,
                    "drawdown_from_year_peak_pct": 0,
                    "distance_sma200_pct": 35,
                    "drawdown_regime": "常态波动",
                    "price_source": "Yahoo quote:SEMI.L",
                },
                {
                    "symbol": "KO",
                    "weight_pct": 4,
                    "unrealized_pnl_pct": 12,
                    "drawdown_from_year_peak_pct": -3,
                    "distance_sma200_pct": 5,
                    "drawdown_regime": "常态波动",
                    "price_source": "Yahoo quote:KO",
                },
            ],
            "portfolio_exposures": [
                {"symbol": "NVDA", "label": "NVIDIA", "weight_pct": 9.0},
                {"symbol": "AVGO", "label": "Broadcom", "weight_pct": 8.1},
            ],
            "portfolio_exposure_notes": ["当前已识别ETF权重72%。"],
            "assets": [
                {
                    "symbol": "VUAG.L",
                    "theme": "S&P 500",
                    "entry_score": 76,
                    "crowding_score": 52,
                    "entry_label": "趋势结构完好",
                    "valuation_label": "估值偏高",
                    "risk_management_note": "跌破50日线后需要重新评估。",
                    "warnings": [],
                },
                {
                    "symbol": "SEMI.L",
                    "theme": "Semiconductor",
                    "entry_score": 45,
                    "crowding_score": 88,
                    "entry_label": "追高风险较高",
                    "valuation_label": "估值偏高",
                    "risk_management_note": "关注拥挤度与资本开支预期。",
                    "warnings": ["PE历史分位样本不足。"],
                },
            ],
        },
        "portfolio_event_monitor": {
            "events": [
                {
                    "symbols": ["NFLX"],
                    "title": "Netflix Q2财报预计窗口",
                    "status": "预计日期",
                    "event_time_label": "2026-07-16 14:30 UK",
                    "watch_items": ["利润率guidance", "广告业务"],
                    "source_label": "Netflix IR",
                    "source_url": "https://ir.netflix.net/",
                }
            ],
            "review_required_symbols": ["META"],
        },
        "news_monitor": {
            "events": [
                {
                    "title": "AI资本开支预期出现分化",
                    "tickers": ["NVDA", "META"],
                    "themes": ["半导体与AI基础设施"],
                    "direction": "风险偏好降温",
                    "confidence": "中",
                    "source": "Example News",
                    "url": "https://example.com/ai",
                }
            ]
        },
    }


class SerenityReportTests(unittest.TestCase):
    def test_incomplete_cost_basis_is_described_as_partial_not_total_portfolio_pnl(self) -> None:
        payload = _payload()
        payload["etf_monitor"]["portfolio_summary"].append(
            "可识别总收益 +808.19 GBP：未实现盈亏 -14.86 GBP。"
        )
        payload["etf_monitor"]["portfolio_warnings"].append(
            "成本基础不完整：Revolut QBTS 于2026-06-05卖出 £2,325.46，当前账单窗口缺少对应买入成本。"
        )

        report = build_serenity_report(payload)

        observations = " ".join(report.portfolio_observations)
        self.assertIn("不是完整账户收益", observations)
        self.assertIn("QBTS", observations)

    def test_cash_like_holding_is_not_treated_as_red_drawdown(self) -> None:
        payload = _payload()
        payload["etf_monitor"]["portfolio_positions"].append(
            {
                "symbol": "ERNS.L",
                "weight_pct": 40,
                "unrealized_pnl_pct": 0,
                "drawdown_from_year_peak_pct": -12,
                "red_drawdown_threshold_pct": 10,
                "distance_sma200_pct": -4,
                "drawdown_regime": "趋势破坏风险",
                "price_source": "Yahoo quote:ERNS.L",
            }
        )
        payload["etf_monitor"]["assets"].append(
            {
                "symbol": "ERNS.L",
                "theme": "GBP Ultrashort Bond / Cash-like",
                "provider": "iShares",
                "equity_like": False,
                "entry_score": 58,
                "crowding_score": 45,
                "liquidity_label": "流动性可用",
                "liquidity_note": "规模与成交较好",
            }
        )

        report = build_serenity_report(payload)
        erns = next(item for item in report.focus_holdings if item.symbol == "ERNS.L")

        self.assertNotIn("红色回撤", erns.priority_reason)
        self.assertIn("组合核心仓位", erns.priority_reason)
        self.assertIn("利率", " ".join(erns.current_state + erns.risks + erns.supporting_evidence))

    def test_stock_focus_includes_short_term_trend_and_support_diagnostics(self) -> None:
        payload = _payload()
        nflx = next(
            item
            for item in payload["etf_monitor"]["portfolio_positions"]
            if item["symbol"] == "NFLX"
        )
        nflx.update(
            {
                "current_price_native": 81.52,
                "ema21_native": 84.10,
                "distance_ema21_pct": -3.07,
                "sma50_native": 88.20,
                "distance_sma50_pct": -7.57,
                "rsi14": 38.5,
                "momentum_1m_pct": -9.2,
                "support_20d_native": 79.80,
                "support_60d_native": 75.40,
            }
        )

        report = build_serenity_report(payload)
        focus = next(item for item in report.focus_holdings if item.symbol == "NFLX")
        combined = " ".join(focus.current_state + focus.risks + focus.supporting_evidence)

        self.assertIn("EMA21", combined)
        self.assertIn("RSI14", combined)
        self.assertIn("79.80", combined)

    def test_focus_selection_prioritizes_red_alerts_and_keeps_three_to_five_holdings(self) -> None:
        report = build_serenity_report(_payload())

        symbols = [item.symbol for item in report.focus_holdings]
        self.assertGreaterEqual(len(symbols), 3)
        self.assertLessEqual(len(symbols), 5)
        self.assertEqual(symbols[:2], ["NFLX", "META"])
        self.assertIn("NVDA", symbols)

    def test_supply_chain_framework_is_explicitly_limited_for_broad_index(self) -> None:
        report = build_serenity_report(_payload())
        vuag = next(item for item in report.focus_holdings if item.symbol == "VUAG.L")

        self.assertEqual(vuag.framework_fit, "有限")
        self.assertIn("宽基", vuag.bottleneck_assessment)
        self.assertTrue(vuag.falsification_conditions)

    def test_lse_asset_metadata_is_used_in_priority_ranking(self) -> None:
        payload = _payload()
        payload["etf_monitor"]["portfolio_positions"].append(
            {
                "symbol": "WDEF.L",
                "weight_pct": 25,
                "unrealized_pnl_pct": 2,
                "drawdown_from_year_peak_pct": -2,
                "distance_sma200_pct": 8,
                "drawdown_regime": "常态波动",
                "price_source": "Yahoo quote:WDEF.L",
            }
        )
        payload["etf_monitor"]["assets"].append(
            {
                "symbol": "WDEF.L",
                "theme": "Defence",
                "entry_score": 66,
                "crowding_score": 95,
            }
        )

        report = build_serenity_report(payload)

        self.assertIn("WDEF.L", [item.symbol for item in report.focus_holdings])

    def test_full_report_puts_risks_before_supporting_case_and_keeps_sources(self) -> None:
        report = build_serenity_report(_payload())
        html = render_serenity_html(report)

        self.assertIn("Serenity 私人持仓周报", html)
        self.assertLess(html.index("主要风险与反证"), html.index("支持逻辑与观察线索"))
        self.assertIn("什么会证伪当前判断", html)
        self.assertIn("https://ir.netflix.net/", html)
        self.assertIn("非投资建议", html)


if __name__ == "__main__":
    unittest.main()
