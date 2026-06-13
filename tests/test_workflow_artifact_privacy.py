from __future__ import annotations

from pathlib import Path
import unittest


class WorkflowArtifactPrivacyTests(unittest.TestCase):
    def test_artifact_upload_uses_public_staging_directory_only(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "daily-market-report.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("Build public portfolio-redacted artifact", workflow)
        self.assertIn(".public-artifact/*.html", workflow)
        self.assertIn(".public-artifact/*.json", workflow)
        self.assertNotIn("            output/*.html", workflow)
        self.assertNotIn("            output/*.json", workflow)
        self.assertNotIn("            output/cache/*.json", workflow)


if __name__ == "__main__":
    unittest.main()
