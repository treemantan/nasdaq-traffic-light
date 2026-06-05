from __future__ import annotations

from datetime import datetime, timezone
import unittest

from market_report.shock_alert import assess_market_shock, should_send_shock_alert, update_shock_state


def _payload(**metrics):
    return {
        "report_date": "2026-06-05",
        "metrics": {
            key: {
                "metric": {
                    "key": key,
                    "label": label,
                    "value": value,
                    "previous_value": previous,
                }
            }
            for key, label, value, previous in metrics.values()
        },
    }


class MarketShockAlertTests(unittest.TestCase):
    def test_equity_selloff_and_vol_spike_triggers_emergency_alert(self) -> None:
        payload = _payload(
            nasdaq=("nasdaq", "Nasdaq 100", 29120.98, 30407.81),
            sp500=("sp500", "S&P 500", 7399.42, 7584.31),
            russell=("russell2000", "Russell 2000", 2832.23, 2935.33),
            vix=("vix", "VIX", 19.51, 15.40),
            vvix=("vvix", "VVIX", 97.08, 85.75),
            dxy=("dxy", "DXY", 100.055, 99.41),
            ten_year=("treasury_10y", "10Y", 4.49, 4.46),
        )

        assessment = assess_market_shock(payload)

        self.assertTrue(assessment.triggered)
        self.assertGreaterEqual(assessment.severity_score, 60)
        self.assertEqual(assessment.level, "critical")
        self.assertIn("NDX -4.23%", assessment.subject_suffix)
        self.assertIn("VIX +26.69%", assessment.subject_suffix)
        self.assertTrue(any(item.value_text == "-4.23%" for item in assessment.triggers))
        self.assertGreaterEqual(len(assessment.actions), 3)

    def test_state_allows_first_send_and_material_escalation_only(self) -> None:
        payload = _payload(
            nasdaq=("nasdaq", "Nasdaq 100", 97.0, 100.0),
            vix=("vix", "VIX", 117.0, 100.0),
        )
        first = assess_market_shock(payload)
        self.assertTrue(should_send_shock_alert(first, {}, "2026-06-05"))

        state = update_shock_state(
            {},
            "2026-06-05",
            first,
            sent_at=datetime(2026, 6, 5, 17, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(should_send_shock_alert(first, state, "2026-06-05"))

        worse = assess_market_shock(
            _payload(
                nasdaq=("nasdaq", "Nasdaq 100", 94.0, 100.0),
                sp500=("sp500", "S&P 500", 97.0, 100.0),
                vix=("vix", "VIX", 130.0, 100.0),
            )
        )
        self.assertTrue(should_send_shock_alert(worse, state, "2026-06-05"))


if __name__ == "__main__":
    unittest.main()
