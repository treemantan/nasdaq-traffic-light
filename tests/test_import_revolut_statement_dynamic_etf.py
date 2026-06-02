from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "import_revolut_statement.py"
SPEC = importlib.util.spec_from_file_location("import_revolut_statement", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ImportRevolutDynamicEtfTests(unittest.TestCase):
    def test_resolves_unknown_lse_etf_from_yahoo_metadata(self) -> None:
        price_data = SimpleNamespace(
            meta={"exchangeName": "LSE", "instrumentType": "ETF", "longName": "Example UCITS ETF"},
        )
        with patch.object(MODULE, "_fetch_yahoo_price_data", return_value=price_data):
            self.assertEqual(MODULE._resolve_lse_etf_symbol("TEST"), "TEST.L")

    def test_does_not_resolve_unknown_single_stock(self) -> None:
        price_data = SimpleNamespace(
            meta={"exchangeName": "NASDAQ", "instrumentType": "EQUITY", "longName": "Meta Platforms Inc"},
        )
        with patch.object(MODULE, "_fetch_yahoo_price_data", return_value=price_data):
            self.assertIsNone(MODULE._resolve_lse_etf_symbol("META"))


if __name__ == "__main__":
    unittest.main()
