from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_rate_limit_error_is_detected(self) -> None:
        self.assertTrue(MODULE._looks_like_rate_limit_error("Too many requests have been made from this token."))
        self.assertTrue(MODULE._looks_like_rate_limit_error("IBKR rate limit exceeded."))
        self.assertFalse(MODULE._looks_like_rate_limit_error("IBKR Flex request did not return a ReferenceCode."))

    def test_main_continues_when_one_query_is_rate_limited_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            def fake_request(_token: str, query_id: str) -> str:
                if query_id == "activity-id":
                    return "activity-reference"
                raise RuntimeError("IBKR Flex request failed: Fail Too many requests have been made from this token.")

            argv = [
                "download_ibkr_flex.py",
                "--token",
                "secret-token",
                "--activity-query-id",
                "activity-id",
                "--trade-confirm-query-id",
                "trade-confirm-id",
                "--output-dir",
                str(output_dir),
                "--query-delay-seconds",
                "0",
                "--rate-limit-retries",
                "0",
            ]

            with patch.object(sys, "argv", argv), patch.object(MODULE, "request_flex_statement", fake_request), patch.object(
                MODULE, "download_flex_statement", return_value=b"<FlexQueryResponse />"
            ):
                self.assertEqual(MODULE.main(), 0)

            self.assertTrue((output_dir / "ibkr-activity-activity-id.xml").exists())
            self.assertFalse((output_dir / "ibkr-trade-confirm-trade-confirm-id.xml").exists())

    def test_main_fails_when_all_queries_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            argv = [
                "download_ibkr_flex.py",
                "--token",
                "secret-token",
                "--activity-query-id",
                "activity-id",
                "--output-dir",
                tmpdir,
                "--rate-limit-retries",
                "0",
            ]

            with patch.object(sys, "argv", argv), patch.object(
                MODULE, "request_flex_statement", side_effect=RuntimeError("IBKR Flex request failed")
            ), self.assertRaises(SystemExit):
                MODULE.main()


if __name__ == "__main__":
    unittest.main()
