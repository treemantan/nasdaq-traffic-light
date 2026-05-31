from __future__ import annotations

import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_revolut_statement.py"
SPEC = spec_from_file_location("import_revolut_statement", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_reconstruct_positions = MODULE._reconstruct_positions


class RevolutImportTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
