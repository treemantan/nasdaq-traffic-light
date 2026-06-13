from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_public_report_artifact.py"
    spec = importlib.util.spec_from_file_location("build_public_report_artifact", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BuildPublicReportArtifactTests(unittest.TestCase):
    def test_main_writes_only_sanitized_payload_to_artifact_directory(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            artifact_dir = root / "public"
            output_dir.mkdir()
            report_path = output_dir / "market-report-2026-06-13.html"
            report_path.write_text("<html>private</html>", encoding="utf-8")
            (output_dir / "serenity-report-2026-06-13.html").write_text(
                "<html>newer but unrelated</html>",
                encoding="utf-8",
            )
            report_path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "portfolio_event_monitor": {"events": [{"symbol": "SECRET"}]},
                        "etf_monitor": {
                            "assets": [],
                            "portfolio_positions": [{"symbol": "SECRET"}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            argv = [
                "build_public_report_artifact.py",
                "--output-dir",
                str(output_dir),
                "--artifact-dir",
                str(artifact_dir),
            ]
            with patch.object(module.sys, "argv", argv), patch.object(
                module.emailer, "_report_from_payload", return_value=object()
            ), patch.object(
                module, "render_html_report", return_value="<html>public</html>"
            ), patch.object(
                module, "load_config"
            ) as load_config:
                load_config.return_value.report_title = "Macro Regime Radar"
                self.assertEqual(module.main(), 0)

            public_payload = json.loads(
                (artifact_dir / "market-report-2026-06-13.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIsNone(public_payload["portfolio_event_monitor"])
            self.assertEqual(
                public_payload["etf_monitor"]["portfolio_positions"],
                [],
            )
            self.assertEqual(
                (artifact_dir / "market-report-2026-06-13.html").read_text(
                    encoding="utf-8"
                ),
                "<html>public</html>",
            )


if __name__ == "__main__":
    unittest.main()
