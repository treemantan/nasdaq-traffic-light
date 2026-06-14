from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "download_onedrive_statements.py"
SPEC = importlib.util.spec_from_file_location("download_onedrive_statements", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OneDriveCloudImportTests(unittest.TestCase):
    def test_default_pattern_accepts_uuid_named_iphone_csv_exports(self) -> None:
        self.assertEqual(MODULE.DEFAULT_PATTERN, "*.csv")

    def test_delegated_mode_uses_me_drive(self) -> None:
        config = MODULE.GraphConfig(
            client_id="client",
            refresh_token="refresh",
            folder_path="Trading/Revolut Transaction Statement",
            pattern="*.csv",
        )
        self.assertEqual(config.auth_mode, "refresh_token")
        self.assertIn("/me/drive/root:/Trading/Revolut%20Transaction%20Statement:/children", MODULE._children_url(config, config.folder_path))

    def test_app_mode_uses_named_user_drive(self) -> None:
        config = MODULE.GraphConfig(
            client_id="client",
            tenant_id="tenant",
            client_secret="secret",
            user_id="user@example.com",
            folder_path="Trading",
            pattern="*.csv",
        )
        self.assertEqual(config.auth_mode, "client_credentials")
        self.assertIn("/users/user%40example.com/drive/root:/Trading:/children", MODULE._children_url(config, config.folder_path))

    def test_latest_file_is_selected_per_account_folder(self) -> None:
        files = [
            {"name": "old.csv", "lastModifiedDateTime": "2026-05-01T00:00:00Z"},
            {"name": "new.csv", "lastModifiedDateTime": "2026-05-31T00:00:00Z"},
        ]
        self.assertEqual(MODULE._latest(files)["name"], "new.csv")

    def test_ibkr_patterns_accept_csv_and_xml(self) -> None:
        items = [
            {"name": "PastTradesFullReport.xml", "file": {}},
            {"name": "CustTrade_info.csv", "file": {}},
            {"name": "notes.txt", "file": {}},
        ]

        matches = MODULE._matching_files(items, MODULE.DEFAULT_IBKR_PATTERNS)

        self.assertEqual([item["name"] for item in matches], ["PastTradesFullReport.xml", "CustTrade_info.csv"])

    def test_latest_ibkr_revision_is_selected_per_logical_query_name(self) -> None:
        files = [
            {
                "name": "PastTradesFullReport.xml",
                "file": {},
                "lastModifiedDateTime": "2026-06-14T00:46:00Z",
            },
            {
                "name": "PastTradesFullReport 1.xml",
                "file": {},
                "lastModifiedDateTime": "2026-06-14T00:51:00Z",
            },
            {
                "name": "CustTrade_info.csv",
                "file": {},
                "lastModifiedDateTime": "2026-06-03T23:16:00Z",
            },
        ]

        selected = MODULE._latest_per_logical_name(files)

        self.assertEqual(
            [item["name"] for item in selected],
            ["CustTrade_info.csv", "PastTradesFullReport 1.xml"],
        )

    def test_graph_modified_time_can_be_preserved_on_downloaded_file(self) -> None:
        timestamp = MODULE._graph_modified_timestamp(
            {"lastModifiedDateTime": "2026-06-13T19:25:42Z"}
        )

        self.assertEqual(timestamp, 1781378742.0)

    def test_duplicate_download_names_get_unique_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "statement.csv").write_text("first", encoding="utf-8")
            self.assertEqual(MODULE._unique_destination(output, "statement.csv").name, "statement-2.csv")

    def test_download_redirect_drops_graph_bearer_token(self) -> None:
        request = MODULE.Request(
            "https://graph.microsoft.com/v1.0/me/drive/items/file/content",
            headers={"Authorization": "Bearer sensitive-token"},
        )
        redirected = MODULE._PreauthenticatedDownloadRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://storage.example.test/preauthenticated-download",
        )
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))


if __name__ == "__main__":
    unittest.main()
