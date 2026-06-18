from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_revolut_statement.py"
SPEC = spec_from_file_location("import_revolut_statement", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_reconstruct_positions = MODULE._reconstruct_positions


class RevolutImportTests(unittest.TestCase):
    def test_portfolio_technical_snapshot_exposes_short_term_trend_and_supports(self) -> None:
        history = [
            (date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + offset), 100 + offset)
            for offset in range(80)
        ]

        snapshot = MODULE._portfolio_technical_snapshot(history)

        self.assertIsNotNone(snapshot["ema21"])
        self.assertIsNotNone(snapshot["sma50"])
        self.assertGreater(snapshot["rsi14"], 70)
        self.assertEqual(snapshot["support_20d"], 160)
        self.assertEqual(snapshot["support_60d"], 120)

    def test_multiple_statements_are_combined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "isa.csv"
            second = Path(directory) / "general.csv"
            first.write_text(
                "Ticker,Type,Quantity,Price per share\n"
                "VUAG,BUY - MARKET,2,GBP 100\n",
                encoding="utf-8",
            )
            second.write_text(
                "Ticker,Type,Quantity,Price per share\n"
                "VUAG,BUY - MARKET,1,GBP 110\n",
                encoding="utf-8",
            )
            positions = _reconstruct_positions([first, second])

        self.assertEqual(positions["VUAG"]["quantity"], 3)
        self.assertEqual(positions["VUAG"]["cost_gbp"], 310)

    def test_overlapping_statement_rows_are_deduplicated_before_position_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "old.csv"
            second = Path(directory) / "new.csv"
            transaction = (
                "2026-05-01T10:00:00Z,VUAG,BUY - MARKET,2,GBP 100,GBP 200,GBP,1.0000\n"
            )
            header = "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
            first.write_text(header + transaction, encoding="utf-8")
            second.write_text(header + transaction, encoding="utf-8")

            positions = _reconstruct_positions([first, second])

        self.assertEqual(positions["VUAG"]["quantity"], 2)
        self.assertEqual(positions["VUAG"]["cost_gbp"], 200)

    def test_later_statement_revision_replaces_same_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.csv"
            revised = Path(directory) / "revised.csv"
            header = "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
            old.write_text(
                header
                + "2026-06-05T19:24:53.488Z,QBTS,SELL - MARKET,132.11847577,"
                "GBP 17.57,GBP 2315.21,GBP,1.0000\n",
                encoding="utf-8",
            )
            revised.write_text(
                header
                + "2026-06-05T19:24:53.488Z,QBTS,SELL - MARKET,132.11847577,"
                "GBP 17.64,GBP 2325.46,GBP,1.0000\n",
                encoding="utf-8",
            )
            os.utime(old, (1_700_000_000, 1_700_000_000))
            os.utime(revised, (1_800_000_000, 1_800_000_000))

            rows, duplicate_count = MODULE._unique_transaction_rows([revised, old])

        self.assertEqual(duplicate_count, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Price per share"], "GBP 17.64")
        self.assertEqual(rows[0]["Total Amount"], "GBP 2325.46")

    def test_dividends_and_known_cost_sales_are_included_in_return_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            statement = Path(directory) / "statement.csv"
            statement.write_text(
                "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
                "2026-01-01T00:00:00Z,KO,BUY - MARKET,10,GBP 5,GBP 50,GBP,1.0000\n"
                "2026-02-01T00:00:00Z,KO,SELL - MARKET,4,GBP 7,GBP 28,GBP,1.0000\n"
                "2026-03-01T00:00:00Z,KO,DIVIDEND,,,GBP 2.50,GBP,1.0000\n",
                encoding="utf-8",
            )
            positions = _reconstruct_positions([statement])

        self.assertEqual(positions["KO"]["quantity"], 6)
        self.assertEqual(positions["KO"]["cost_gbp"], 30)
        self.assertEqual(positions["KO"]["realized_pnl_gbp"], 8)
        self.assertEqual(positions["KO"]["dividend_income_gbp"], 2.5)

    def test_implied_trading_costs_reduce_net_return_and_record_closed_trade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            statement = Path(directory) / "statement.csv"
            statement.write_text(
                "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
                "2026-01-01T00:00:00Z,KO,BUY - MARKET,10,GBP 5,GBP -51,GBP,1.0000\n"
                "2026-01-01T12:00:00Z,KO,SELL - MARKET,4,GBP 7,GBP 27,GBP,1.0000\n"
                "2026-03-01T00:00:00Z,KO,DIVIDEND,,,GBP 2.50,GBP,1.0000\n",
                encoding="utf-8",
            )
            positions = _reconstruct_positions([statement])

        self.assertAlmostEqual(positions["KO"]["quantity"], 6)
        self.assertAlmostEqual(positions["KO"]["cost_gbp"], 30.6)
        self.assertAlmostEqual(positions["KO"]["realized_pnl_gbp"], 6.6)
        self.assertAlmostEqual(positions["KO"]["implied_trading_cost_gbp"], 2.0)
        self.assertEqual(len(positions["KO"]["closed_trades"]), 1)
        closed_trade = positions["KO"]["closed_trades"][0]
        self.assertEqual(closed_trade["holding_days"], 0)
        self.assertAlmostEqual(closed_trade["gross_proceeds_gbp"], 28.0)
        self.assertAlmostEqual(closed_trade["net_proceeds_gbp"], 27.0)
        self.assertAlmostEqual(closed_trade["cost_basis_gbp"], 20.4)
        self.assertAlmostEqual(closed_trade["realized_pnl_gbp"], 6.6)
        cost_events = positions["KO"]["transaction_costs"]
        self.assertEqual(len(cost_events), 2)
        self.assertEqual(cost_events[0]["side"], "BUY")
        self.assertAlmostEqual(cost_events[0]["implied_trading_cost_gbp"], 1.0)
        self.assertAlmostEqual(cost_events[0]["cost_rate_pct"], 2.0)
        self.assertEqual(cost_events[1]["side"], "SELL")
        self.assertAlmostEqual(cost_events[1]["implied_trading_cost_gbp"], 1.0)
        self.assertAlmostEqual(cost_events[1]["cost_rate_pct"], 3.5714285714)

    def test_sale_without_visible_purchase_is_not_treated_as_profit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            statement = Path(directory) / "statement.csv"
            statement.write_text(
                "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
                "2026-01-01T00:00:00Z,GOOGL,SELL - MARKET,2,GBP 100,GBP 200,GBP,1.0000\n",
                encoding="utf-8",
            )
            positions = _reconstruct_positions([statement])

        self.assertEqual(positions["GOOGL"]["realized_pnl_gbp"], 0)
        self.assertEqual(positions["GOOGL"]["unmatched_sell_proceeds_gbp"], 200)
        self.assertEqual(
            positions["GOOGL"]["unmatched_sells"],
            [
                {
                    "symbol": "GOOGL",
                    "date": "2026-01-01",
                    "transaction_type": "SELL - MARKET",
                    "sell_quantity": 2.0,
                    "matched_quantity": 0.0,
                    "unmatched_quantity": 2.0,
                    "price_gbp": 100.0,
                    "net_proceeds_gbp": 200.0,
                    "reason": "missing_visible_cost_basis",
                    "broker": "Revolut",
                }
            ],
        )

    def test_portfolio_rows_include_unmatched_sell_audit_trail(self) -> None:
        quotes = {
            "GBPUSD=X": (1.25, 1.24, "USD", []),
            "GBPEUR=X": (1.18, 1.17, "EUR", []),
            "KO": (10.0, 9.5, "GBP", [(date(2026, 1, 2), 10.0)]),
        }
        position = {
            "quantity": 2.0,
            "cost_gbp": 15.0,
            "unmatched_sell_proceeds_gbp": 200.0,
            "unmatched_sells": [
                {
                    "symbol": "GOOGL",
                    "date": "2026-01-01",
                    "transaction_type": "SELL - MARKET",
                    "sell_quantity": 2.0,
                    "matched_quantity": 0.0,
                    "unmatched_quantity": 2.0,
                    "price_gbp": 100.0,
                    "net_proceeds_gbp": 200.0,
                    "reason": "missing_visible_cost_basis",
                    "broker": "Revolut",
                }
            ],
        }
        with patch.object(MODULE, "_latest_quote", side_effect=lambda symbol: quotes[symbol]):
            rows = MODULE._build_portfolio_rows({"KO": position})

        unmatched = MODULE.json.loads(rows[0]["unmatched_sells_json"])
        self.assertEqual(unmatched[0]["symbol"], "GOOGL")
        self.assertEqual(unmatched[0]["broker"], "Revolut")

    def test_us_equity_rejects_wrong_lse_ticker_when_price_conflicts_with_cost(self) -> None:
        quotes = {
            "GBPUSD=X": (1.35, 1.34, "USD", []),
            "GBPEUR=X": (1.18, 1.17, "EUR", []),
            "MSFT.L": (5.92, 5.90, "GBP", [(date(2026, 6, 12), 5.92)]),
            "MSFT": (405.0, 400.0, "USD", [(date(2026, 6, 12), 405.0)]),
        }
        position = {
            "quantity": 2.5557406,
            "cost_gbp": 746.53,
            "realized_pnl_gbp": 0.0,
            "dividend_income_gbp": 0.0,
            "unmatched_sell_proceeds_gbp": 0.0,
            "unmatched_sells": [],
            "implied_trading_cost_gbp": 0.0,
            "transaction_costs": [],
            "closed_trades": [],
        }
        with patch.object(MODULE, "_resolve_lse_etf_symbol", return_value="MSFT.L"):
            with patch.object(MODULE, "_latest_quote", side_effect=lambda symbol: quotes[symbol]):
                rows = MODULE._build_portfolio_rows({"MSFT": position})

        self.assertEqual(rows[0]["symbol"], "MSFT")
        self.assertEqual(rows[0]["native_currency"], "USD")
        self.assertAlmostEqual(float(rows[0]["current_price_gbp"]), 300.0, places=4)
        self.assertIn("Yahoo", rows[0]["price_source"])

    def test_known_us_equity_is_never_auto_mapped_to_london(self) -> None:
        with patch.object(MODULE, "_fetch_yahoo_price_data") as fetch:
            resolved = MODULE._resolve_lse_etf_symbol("MSFT")

        self.assertIsNone(resolved)
        fetch.assert_not_called()

    def test_uuid_named_iphone_export_is_recognized_by_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            statement = Path(directory) / "9B4221B1-92C0-4957-B42B-320C617C4FE8.csv"
            statement.write_text(
                "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
                "2026-06-01T00:00:00Z,VUAG,BUY - MARKET,1,GBP 100,GBP 100,GBP,1.0000\n",
                encoding="utf-8",
            )

            self.assertTrue(MODULE._is_revolut_statement(statement))

    def test_usd_position_keeps_native_value_and_adds_gbp_reference(self) -> None:
        quotes = {
            "GBPUSD=X": (1.25, 1.24, "USD", []),
            "GBPEUR=X": (1.18, 1.17, "EUR", []),
            "NFLX": (
                100.0,
                90.0,
                "USD",
                [(date(2026, 1, 2), 120.0), (date(2026, 5, 29), 100.0)],
            ),
        }
        with patch.object(MODULE, "_latest_quote", side_effect=lambda symbol: quotes[symbol]):
            rows = MODULE._build_portfolio_rows({"NFLX": {"quantity": 2.0, "cost_gbp": 100.0}})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["native_currency"], "USD")
        self.assertEqual(rows[0]["current_price_native"], "100.0000")
        self.assertEqual(rows[0]["market_value_native"], "200.0000")
        self.assertEqual(rows[0]["estimated_market_value_gbp"], "160.00")
        self.assertEqual(rows[0]["fx_pair"], "GBP/USD")
        self.assertEqual(rows[0]["fx_rate"], "1.2500")
        self.assertEqual(rows[0]["drawdown_from_year_peak_pct"], "-16.6667")
        self.assertIn("红色观察", rows[0]["peak_watch"])

    def test_portfolio_rows_include_account_level_return_attribution(self) -> None:
        quotes = {
            "GBPUSD=X": (1.25, 1.24, "USD", []),
            "GBPEUR=X": (1.18, 1.17, "EUR", []),
            "KO": (10.0, 9.5, "GBP", [(date(2026, 1, 2), 10.0)]),
        }
        position = {
            "quantity": 2.0,
            "cost_gbp": 15.0,
            "realized_pnl_gbp": 3.0,
            "dividend_income_gbp": 1.5,
            "unmatched_sell_proceeds_gbp": 0.0,
        }
        with patch.object(MODULE, "_latest_quote", side_effect=lambda symbol: quotes[symbol]):
            rows = MODULE._build_portfolio_rows({"KO": position})

        self.assertEqual(rows[0]["account_unrealized_pnl_gbp"], "5.0000")
        self.assertEqual(rows[0]["account_realized_pnl_gbp"], "3.0000")
        self.assertEqual(rows[0]["account_dividend_income_gbp"], "1.5000")
        self.assertEqual(rows[0]["account_total_return_gbp"], "9.5000")

    def test_portfolio_rows_include_implied_cost_and_closed_trade_breakdown(self) -> None:
        quotes = {
            "GBPUSD=X": (1.25, 1.24, "USD", []),
            "GBPEUR=X": (1.18, 1.17, "EUR", []),
            "KO": (10.0, 9.5, "GBP", [(date(2026, 1, 2), 10.0)]),
        }
        position = {
            "quantity": 2.0,
            "cost_gbp": 15.0,
            "realized_pnl_gbp": -3.0,
            "dividend_income_gbp": 1.5,
            "unmatched_sell_proceeds_gbp": 0.0,
            "implied_trading_cost_gbp": 2.0,
            "transaction_costs": [
                {
                    "symbol": "KO",
                    "date": "2026-01-01",
                    "side": "BUY",
                    "quantity": 2.0,
                    "price_gbp": 7.0,
                    "gross_value_gbp": 14.0,
                    "cash_amount_gbp": 15.0,
                    "implied_trading_cost_gbp": 1.0,
                    "cost_rate_pct": 7.142857,
                },
                {
                    "symbol": "KO",
                    "date": "2026-01-02",
                    "side": "SELL",
                    "quantity": 1.0,
                    "price_gbp": 6.0,
                    "gross_value_gbp": 6.0,
                    "cash_amount_gbp": 5.0,
                    "implied_trading_cost_gbp": 1.0,
                    "cost_rate_pct": 16.666667,
                },
            ],
            "closed_trades": [
                {
                    "symbol": "KO",
                    "opened_at": "2026-01-01",
                    "closed_at": "2026-01-01",
                    "holding_days": 0,
                    "quantity": 1.0,
                    "cost_basis_gbp": 8.0,
                    "gross_proceeds_gbp": 6.0,
                    "net_proceeds_gbp": 5.0,
                    "implied_trading_cost_gbp": 1.0,
                    "realized_pnl_gbp": -3.0,
                }
            ],
        }
        with patch.object(MODULE, "_latest_quote", side_effect=lambda symbol: quotes[symbol]):
            rows = MODULE._build_portfolio_rows({"KO": position})

        self.assertEqual(rows[0]["implied_trading_cost_gbp"], "2.0000")
        self.assertEqual(rows[0]["account_implied_trading_cost_gbp"], "2.0000")
        self.assertEqual(rows[0]["estimated_exit_cost_rate_pct"], "16.6667")
        self.assertEqual(rows[0]["breakeven_price_gbp"], "9.0000")
        costs = MODULE.json.loads(rows[0]["transaction_costs_json"])
        self.assertEqual(costs[0]["symbol"], "KO")
        self.assertEqual(len(costs), 2)
        closed_trades = MODULE.json.loads(rows[0]["closed_trades_json"])
        self.assertEqual(closed_trades[0]["symbol"], "KO")
        self.assertEqual(closed_trades[0]["holding_days"], 0)
        self.assertEqual(closed_trades[0]["realized_pnl_gbp"], -3.0)

    def test_peak_watch_uses_current_calendar_year(self) -> None:
        peak, peak_date, drawdown = MODULE._year_peak_snapshot(
            [
                (date(2025, 12, 31), 200.0),
                (date(2026, 1, 2), 100.0),
                (date(2026, 5, 29), 96.0),
            ]
        )

        self.assertEqual(peak, 100.0)
        self.assertEqual(peak_date, date(2026, 1, 2))
        self.assertAlmostEqual(drawdown or 0, -4.0)
        self.assertIn("常态", MODULE._peak_watch_label(drawdown))


    def test_drawdown_regime_distinguishes_normal_pullback_from_trend_break(self) -> None:
        normal = MODULE._drawdown_regime_label(-8.0, 4.0, 1.2)
        broken = MODULE._drawdown_regime_label(-12.0, -4.0, 2.4)

        self.assertIn("正常回调观察", normal)
        self.assertIn("趋势破坏风险", broken)

    def test_portfolio_drawdown_snapshot_uses_sma200_and_robust_volatility(self) -> None:
        history = [
            (date(2025, 1, 1), 100 + index * 0.2 + (index % 5 - 2))
            for index in range(220)
        ]
        snapshot = MODULE._portfolio_drawdown_snapshot(history, -6.0)

        self.assertIsNotNone(snapshot[0])
        self.assertIsNotNone(snapshot[1])
        self.assertIsNotNone(snapshot[2])
        self.assertIsNotNone(snapshot[3])

    def test_cash_like_distribution_fields_use_latest_dividend_event(self) -> None:
        with patch.object(MODULE, "CASH_LIKE_DISTRIBUTION_SYMBOLS", {"CASH.L"}):
            fields = MODULE._cash_like_distribution_fields(
                "CASH.L",
                {"_dividend_events": [{"ex_date": "2026-06-18", "amount": 1.02}]},
            )

        self.assertEqual(fields["distribution_ex_date"], "2026-06-18")
        self.assertEqual(fields["distribution_amount_native"], 1.02)
        self.assertIn("最近除息日 2026-06-18", fields["distribution_cycle_note"])

    def test_erns_distribution_override_includes_pay_date(self) -> None:
        fields = MODULE._cash_like_distribution_fields("ERNS.L", {})

        self.assertEqual(fields["distribution_ex_date"], "2026-06-18")
        self.assertEqual(fields["distribution_amount_native"], 1.0211)
        self.assertIn("Pay date 2026-06-30", fields["distribution_cycle_note"])
        self.assertIn("Revolut可能", fields["distribution_cycle_note"])

    def test_cash_like_distribution_fields_fall_back_without_event(self) -> None:
        with patch.object(MODULE, "CASH_LIKE_DISTRIBUTION_OVERRIDES", {}):
            fields = MODULE._cash_like_distribution_fields("ERNS.L", {})

        self.assertEqual(fields["distribution_ex_date"], "")
        self.assertIn("Revolut入账", fields["distribution_cycle_note"])

    def test_adaptive_drawdown_thresholds_scale_with_robust_monthly_volatility(self) -> None:
        low_volatility = MODULE._adaptive_drawdown_thresholds(0.5)
        high_volatility = MODULE._adaptive_drawdown_thresholds(3.0)

        self.assertEqual(low_volatility, (5.0, 10.0))
        self.assertGreater(high_volatility[0], 5)
        self.assertGreater(high_volatility[1], 10)

    def test_latest_quote_uses_recent_persistent_cache_after_live_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "portfolio_quote_cache.json"
            history = [(date(2026, 5, 28), 98.0), (date(2026, 5, 29), 100.0)]
            price_data = SimpleNamespace(history=history, meta={"currency": "USD"})
            with patch.object(MODULE, "PORTFOLIO_QUOTE_CACHE_PATH", cache_path), patch.object(
                MODULE, "_fetch_yahoo_price_data", return_value=price_data
            ), patch.object(
                MODULE, "_fetch_yahoo_quote_snapshot", return_value={}
            ):
                MODULE._PORTFOLIO_QUOTE_CACHE = None
                MODULE._PORTFOLIO_QUOTE_CACHE_DIRTY = False
                first = MODULE._latest_quote("NFLX")
                MODULE._save_portfolio_quote_cache()

            with patch.object(MODULE, "PORTFOLIO_QUOTE_CACHE_PATH", cache_path), patch.object(
                MODULE, "_fetch_yahoo_price_data", side_effect=RuntimeError("temporary outage")
            ):
                MODULE._PORTFOLIO_QUOTE_CACHE = None
                MODULE._PORTFOLIO_QUOTE_CACHE_DIRTY = False
                second = MODULE._latest_quote("NFLX")

        self.assertEqual(first, second)
        self.assertEqual(MODULE._QUOTE_SOURCES["NFLX"], "Yahoo cache:NFLX")

    def test_latest_quote_labels_yahoo_quote_price(self) -> None:
        price_data = SimpleNamespace(
            history=[(date(2026, 6, 2), 138.64), (date(2026, 6, 4), 138.91)],
            meta={"currency": "GBP", "_price_source": "regularMarketPrice"},
        )
        with patch.object(MODULE, "_fetch_yahoo_price_data", return_value=price_data), patch.object(
            MODULE, "_fetch_yahoo_quote_snapshot", return_value={}
        ):
            MODULE._QUOTE_SOURCES.clear()
            price, previous, currency, history = MODULE._latest_quote("VWRL.L")

        self.assertEqual(price, 138.91)
        self.assertEqual(previous, 138.64)
        self.assertEqual(currency, "GBP")
        self.assertEqual(history[-1], (date(2026, 6, 4), 138.91))
        self.assertEqual(MODULE._QUOTE_SOURCES["VWRL.L"], "Yahoo quote:VWRL.L")

    def test_latest_quote_prefers_quote_endpoint_for_us_stock(self) -> None:
        price_data = SimpleNamespace(
            history=[(date(2026, 6, 3), 112.0)],
            meta={"currency": "USD"},
        )
        quote = {
            "currency": "USD",
            "regularMarketPrice": 114.7,
            "regularMarketPreviousClose": 112.0,
            "regularMarketTime": 1780531200,
        }
        with patch.object(MODULE, "_fetch_yahoo_price_data", return_value=price_data), patch.object(
            MODULE, "_fetch_yahoo_quote_snapshot", return_value=quote
        ):
            MODULE._QUOTE_SOURCES.clear()
            price, previous, currency, history = MODULE._latest_quote("RKLB")

        self.assertEqual(price, 114.7)
        self.assertEqual(previous, 112.0)
        self.assertEqual(currency, "USD")
        self.assertEqual(history[-1], (date(2026, 6, 4), 114.7))
        self.assertEqual(MODULE._QUOTE_SOURCES["RKLB"], "Yahoo quote:RKLB")

    def test_latest_quote_scales_lse_gbp_quote_from_pence(self) -> None:
        price_data = SimpleNamespace(
            history=[(date(2026, 6, 3), 138.64)],
            meta={"currency": "GBp"},
        )
        quote = {
            "currency": "GBp",
            "regularMarketPrice": 13805.0,
            "regularMarketPreviousClose": 13864.0,
            "regularMarketTime": 1780531200,
        }
        with patch.object(MODULE, "_fetch_yahoo_price_data", return_value=price_data), patch.object(
            MODULE, "_fetch_yahoo_quote_snapshot", return_value=quote
        ):
            price, previous, currency, _history = MODULE._latest_quote("VWRL.L")

        self.assertAlmostEqual(price, 138.05)
        self.assertAlmostEqual(previous, 138.64)
        self.assertEqual(currency, "GBP")


if __name__ == "__main__":
    unittest.main()
