from pathlib import Path
import unittest


class SerenityWorkflowTests(unittest.TestCase):
    def test_weekly_serenity_schedule_and_deduplication_are_configured(self) -> None:
        workflow = Path(".github/workflows/daily-market-report.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("none, pulse, volatility, full, serenity, technical, auto", workflow)
        self.assertIn('cron: "0 8 * * 6"', workflow)
        self.assertIn('cron: "0 9 * * 6"', workflow)
        self.assertIn('cron: "0 10 * * 6"', workflow)
        self.assertIn('("09:00", "serenity")', workflow)
        self.assertIn('("10:00", "serenity")', workflow)
        self.assertIn("serenity-email-marker", workflow)
        self.assertIn("Generate Serenity weekly report", workflow)

    def test_serenity_uses_full_ibkr_activity_data(self) -> None:
        workflow = Path(".github/workflows/daily-market-report.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'if [ "$EMAIL_MODE" != "full" ] && [ "$EMAIL_MODE" != "serenity" ] && [ "$EMAIL_MODE" != "technical" ]; then',
            workflow,
        )


    def test_manual_technical_mode_supports_optional_tickers(self) -> None:
        workflow = Path(".github/workflows/daily-market-report.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("technical_tickers:", workflow)
        self.assertIn("TECHNICAL_TICKERS: ${{ inputs.technical_tickers }}", workflow)
        self.assertIn("Generate Technical Swing report", workflow)
        self.assertIn("python scripts/generate_technical_swing_report.py", workflow)


if __name__ == "__main__":
    unittest.main()
