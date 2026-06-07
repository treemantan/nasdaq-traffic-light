from __future__ import annotations

import tempfile
import unittest
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

    def test_revolut_and_ibkr_positions_merge_by_symbol(self) -> None:
        revolut = {"VWRL": {"quantity": 1.0, "cost_gbp": 100.0, "realized_pnl_gbp": 0.0, "dividend_income_gbp": 0.0}}
        ibkr = {"VWRL": {"quantity": 2.0, "cost_gbp": 210.0, "realized_pnl_gbp": 0.0, "dividend_income_gbp": 1.5}}

        merged = MODULE._merge_positions(revolut, ibkr)

        self.assertEqual(merged["VWRL"]["quantity"], 3.0)
        self.assertEqual(merged["VWRL"]["cost_gbp"], 310.0)
        self.assertEqual(merged["VWRL"]["dividend_income_gbp"], 1.5)


if __name__ == "__main__":
    unittest.main()
