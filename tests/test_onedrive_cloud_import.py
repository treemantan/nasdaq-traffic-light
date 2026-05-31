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
