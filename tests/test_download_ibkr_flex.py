from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "download_ibkr_flex.py"
SPEC = importlib.util.spec_from_file_location("download_ibkr_flex", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DownloadIbkrFlexTests(unittest.TestCase):
    def test_reference_code_is_extracted_from_success_response(self) -> None:
        xml = b"""<FlexStatementResponse>
  <Status>Success</Status>
  <ReferenceCode>abc123</ReferenceCode>
</FlexStatementResponse>"""

        calls: list[str] = []

        def fake_request(url: str) -> bytes:
            calls.append(url)
            return xml

        original = MODULE._request_bytes
        MODULE._request_bytes = fake_request
        try:
            reference = MODULE.request_flex_statement("secret-token", "1531778")
        finally:
            MODULE._request_bytes = original

        self.assertEqual(reference, "abc123")
        self.assertIn("q=1531778", calls[0])
        self.assertIn("v=3", calls[0])

    def test_pending_statement_response_is_detected(self) -> None:
        xml = b"""<FlexStatementResponse>
  <Status>Warn</Status>
  <ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage>
</FlexStatementResponse>"""

        self.assertTrue(MODULE._looks_like_pending_response(xml))


if __name__ == "__main__":
    unittest.main()
