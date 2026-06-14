from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_portfolio_statements.py"
SPEC = spec_from_file_location("import_portfolio_statements", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ImportPortfolioStatementsTests(unittest.TestCase):
    def test_ibkr_trade_confirmation_counts_execution_rows_only(self) -> None:
        header = (
            "ClientAccountID,Symbol,ListingExchange,TradeID,OrderID,ExecID,TradeDate,"
            "Buy/Sell,Quantity,Price,Amount,Proceeds,NetCash,Commission,CommissionCurrency,LevelOfDetail\n"
        )
        content = (
            header
            + "U1,VWRL,LSEETF,,, ,20260603,BUY,28.857,138.579,3998.994,-3998.994,-4001.994,-3,GBP,SYMBOL_SUMMARY\n"
            + "U1,VWRL,LSEETF,,5262200313,,20260603,BUY,28.857,138.579,3998.994,-3998.994,-4001.994,-3,GBP,ORDER\n"
            + "U1,VWRL,LSEETF,9624857160,5262200313,exec-a,20260603,BUY,0.857,138.57,118.754,-118.754,-119.754,-1,GBP,EXECUTION\n"
            + "U1,VWRL,LSEETF,9624857179,5262200313,exec-b,20260603,BUY,28,138.58,3880.24,-3880.24,-3882.24,-2,GBP,EXECUTION\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CustTrade_info.csv"
            path.write_text(content, encoding="utf-8")
            positions = MODULE._reconstruct_ibkr_positions([path])

        self.assertAlmostEqual(positions["VWRL"]["quantity"], 28.857)
        self.assertAlmostEqual(positions["VWRL"]["cost_gbp"], 4001.994)

    def test_ibkr_flex_xml_activity_and_trade_confirmation_are_supported(self) -> None:
        content = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U1" fromDate="20260603" toDate="20260603">
      <Trades>
        <Trade accountId="U1" symbol="VWRL" tradeID="t-summary" tradeDate="20260603" buySell="BUY" quantity="28.857" tradePrice="138.579" netCash="-4001.994" ibCommission="-3" levelOfDetail="SYMBOL_SUMMARY" />
        <Trade accountId="U1" symbol="VWRL" tradeID="t1" ibExecID="exec-a" tradeDate="20260603" buySell="BUY" quantity="0.857" tradePrice="138.57" netCash="-119.754" ibCommission="-1" levelOfDetail="EXECUTION" />
        <Trade accountId="U1" symbol="VWRL" tradeID="t2" ibExecID="exec-b" tradeDate="20260603" buySell="BUY" quantity="28" tradePrice="138.58" netCash="-3882.24" ibCommission="-2" levelOfDetail="EXECUTION" />
      </Trades>
      <CashTransactions>
        <CashTransaction symbol="VWRL" type="Dividends" reportDate="20260604" amount="1.50" levelOfDetail="DETAIL" />
      </CashTransactions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ibkr-flex.xml"
            path.write_text(content, encoding="utf-8")
            self.assertTrue(MODULE._is_ibkr_statement(path))
            positions = MODULE._reconstruct_ibkr_positions([path])

        self.assertAlmostEqual(positions["VWRL"]["quantity"], 28.857)
        self.assertAlmostEqual(positions["VWRL"]["cost_gbp"], 4001.994)
        self.assertAlmostEqual(positions["VWRL"]["dividend_income_gbp"], 1.5)

    def test_ibkr_trade_confirm_xml_rows_are_supported(self) -> None:
        content = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <TradeConfirms>
    <TradeConfirm accountId="U1" symbol="JEDG" tradeID="t1" ibExecID="exec-jedg"
      tradeDate="20260612" buySell="BUY" quantity="10" tradePrice="12.34"
      netCash="-123.40" levelOfDetail="EXECUTION" />
  </TradeConfirms>
</FlexQueryResponse>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ibkr-trade-confirm.xml"
            path.write_text(content, encoding="utf-8")
            positions = MODULE._reconstruct_ibkr_positions([path])

        self.assertAlmostEqual(positions["JEDG"]["quantity"], 10)
        self.assertAlmostEqual(positions["JEDG"]["cost_gbp"], 123.40)

    def test_revolut_and_ibkr_positions_merge_by_symbol(self) -> None:
        revolut = {"VWRL": {"quantity": 1.0, "cost_gbp": 100.0, "realized_pnl_gbp": 0.0, "dividend_income_gbp": 0.0}}
        ibkr = {"VWRL": {"quantity": 2.0, "cost_gbp": 210.0, "realized_pnl_gbp": 0.0, "dividend_income_gbp": 1.5}}

        merged = MODULE._merge_positions(revolut, ibkr)

        self.assertEqual(merged["VWRL"]["quantity"], 3.0)
        self.assertEqual(merged["VWRL"]["cost_gbp"], 310.0)
        self.assertEqual(merged["VWRL"]["dividend_income_gbp"], 1.5)

    def test_ibkr_sale_without_visible_purchase_keeps_auditable_source_detail(self) -> None:
        header = (
            "ClientAccountID,Symbol,TradeID,ExecID,TradeDate,Buy/Sell,Quantity,Price,"
            "NetCash,Commission,CommissionCurrency,CurrencyPrimary,LevelOfDetail\n"
        )
        content = (
            header
            + "U1,TESTX,t1,exec-1,20260612,SELL,5,465,2325.46,-1,USD,GBP,EXECUTION\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ibkr-trade-confirm.csv"
            path.write_text(content, encoding="utf-8")
            positions = MODULE._reconstruct_ibkr_positions([path])

        self.assertEqual(positions["TESTX"]["unmatched_sell_proceeds_gbp"], 0)
        self.assertEqual(positions["TESTX"]["unmatched_sells"][0]["broker"], "IBKR")
        self.assertEqual(positions["TESTX"]["unmatched_sells"][0]["account_id"], "U1")
        self.assertEqual(positions["TESTX"]["unmatched_sells"][0]["currency"], "USD")
        self.assertEqual(positions["TESTX"]["unmatched_sells"][0]["net_proceeds_native"], 2325.46)

    def test_ibkr_data_health_prefers_latest_manual_activity_revision(self) -> None:
        content = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U1" fromDate="20260601" toDate="20260613">
      <Trades>
        <Trade accountId="U1" symbol="VWRL" tradeID="t1" tradeDate="20260613"
          buySell="BUY" quantity="1" tradePrice="100" netCash="-100"
          levelOfDetail="EXECUTION" />
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = root / "PastTradesFullReport.xml"
            latest = root / "PastTradesFullReport 1.xml"
            trade = root / "CustTrade_info.csv"
            older.write_text(content.replace("20260613", "20260612"), encoding="utf-8")
            latest.write_text(content, encoding="utf-8")
            trade.write_text(
                "ClientAccountID,Symbol,TradeID,TradeDate,Buy/Sell,Quantity,"
                "TradePrice,NetCash,LevelOfDetail\n"
                "U1,JEDG,t2,20260612,BUY,10,12.34,-123.40,EXECUTION\n",
                encoding="utf-8",
            )
            older_time = datetime(2026, 6, 14, 0, 46, tzinfo=timezone.utc).timestamp()
            latest_time = datetime(2026, 6, 14, 0, 51, tzinfo=timezone.utc).timestamp()
            os.utime(older, (older_time, older_time))
            os.utime(latest, (latest_time, latest_time))

            health = MODULE._ibkr_data_health([older, latest, trade], None)

        self.assertEqual(health["ibkr_data_status"], "manual-fallback")
        self.assertEqual(health["ibkr_activity_source"], "OneDrive manual")
        self.assertEqual(health["ibkr_activity_as_of"], "2026-06-13")
        self.assertIn("手动", health["ibkr_data_warning"])

    def test_ibkr_data_health_reports_partial_live_coverage(self) -> None:
        content = (
            "ClientAccountID,Symbol,TradeID,TradeDate,Buy/Sell,Quantity,"
            "TradePrice,NetCash,LevelOfDetail\n"
            "U1,JEDG,t1,20260614,BUY,10,12.34,-123.40,EXECUTION\n"
        )
        diagnostics = {
            "events": [
                {"event": "query_final_failure", "label": "activity", "message": "not generated"},
                {"event": "query_downloaded", "label": "trade-confirm", "file": "ibkr-trade-confirm-1.csv"},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trade = root / "ibkr-trade-confirm-1.csv"
            trade.write_text(content, encoding="utf-8")
            diagnostics_path = root / "ibkr-flex-diagnostics.json"
            diagnostics_path.write_text(json.dumps(diagnostics), encoding="utf-8")

            health = MODULE._ibkr_data_health([trade], diagnostics_path)

        self.assertEqual(health["ibkr_data_status"], "partial")
        self.assertEqual(health["ibkr_trade_source"], "IBKR Flex live")
        self.assertEqual(health["ibkr_trade_as_of"], "2026-06-14")
        self.assertIn("Activity", health["ibkr_data_warning"])

    def test_ibkr_data_health_is_blank_when_ibkr_is_not_configured(self) -> None:
        health = MODULE._ibkr_data_health([], None)

        self.assertEqual(health["ibkr_data_status"], "")
        self.assertEqual(health["ibkr_data_warning"], "")


if __name__ == "__main__":
    unittest.main()
