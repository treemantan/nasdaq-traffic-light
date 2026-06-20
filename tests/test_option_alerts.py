from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import unittest

from market_report.option_alerts import build_option_risk_alerts
from market_report.option_alerts import OptionRiskAlert

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "send_portfolio_event_reminders.py"
_SPEC = importlib.util.spec_from_file_location("send_portfolio_event_reminders", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_REMINDER_SCRIPT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_REMINDER_SCRIPT)
_render_reminder = _REMINDER_SCRIPT._render_reminder


def _leg(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "symbol": "VIX 260722C00017000",
        "underlying": "VIX",
        "expiry": "2026-07-22",
        "right": "C",
        "strike": 17.0,
        "side": "BUY",
        "signed_contracts": 1.0,
        "mark_price": 2.00,
        "market_value_gbp": 150.0,
        "implied_volatility": 0.80,
        "market_data_source": "Yahoo delayed option chain",
    }
    base.update(overrides)
    return base


class OptionAlertTests(unittest.TestCase):
    def test_first_observation_builds_baseline_without_alerting(self) -> None:
        alerts, state = build_option_risk_alerts(
            [_leg()],
            {},
            now=datetime.fromisoformat("2026-06-20T10:00:00+01:00"),
        )

        self.assertEqual(alerts, ())
        self.assertIn("VIX|2026-07-22|C|17", state["contracts"])

    def test_iv_jump_triggers_private_alert(self) -> None:
        previous = {
            "contracts": {
                "VIX|2026-07-22|C|17": {
                    "iv": 0.80,
                    "mark": 2.00,
                    "market_value_gbp": 150.0,
                    "observed_at": "2026-06-20T10:00:00+01:00",
                }
            },
            "sent_alerts": {},
        }

        alerts, state = build_option_risk_alerts(
            [_leg(implied_volatility=0.93, mark_price=2.10, market_value_gbp=157.5)],
            previous,
            now=datetime.fromisoformat("2026-06-20T14:00:00+01:00"),
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, "red")
        self.assertIn("IV", alerts[0].summary)
        self.assertIn("VIX", alerts[0].details[-1])
        self.assertIn(alerts[0].alert_id, state["sent_alerts"])

    def test_mark_jump_triggers_alert_even_without_iv(self) -> None:
        previous = {
            "contracts": {
                "NFLX|2026-07-24|P|70": {
                    "iv": None,
                    "mark": 1.00,
                    "market_value_gbp": -75.0,
                    "observed_at": "2026-06-20T10:00:00+01:00",
                }
            },
            "sent_alerts": {},
        }

        alerts, _ = build_option_risk_alerts(
            [
                _leg(
                    symbol="NFLX 260724P00070000",
                    underlying="NFLX",
                    expiry="2026-07-24",
                    right="P",
                    strike=70.0,
                    signed_contracts=-1,
                    mark_price=1.65,
                    market_value_gbp=-123.75,
                    implied_volatility=None,
                )
            ],
            previous,
            now=datetime.fromisoformat("2026-06-20T14:00:00+01:00"),
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, "red")
        self.assertIn("mark", alerts[0].summary)

    def test_cooldown_suppresses_repeated_alert(self) -> None:
        previous = {
            "contracts": {
                "VIX|2026-07-22|C|17": {
                    "iv": 0.80,
                    "mark": 2.00,
                    "market_value_gbp": 150.0,
                    "observed_at": "2026-06-20T10:00:00+01:00",
                }
            },
            "sent_alerts": {"VIX|2026-07-22|C|17|iv-red": "2026-06-20T13:00:00+01:00"},
        }

        alerts, _ = build_option_risk_alerts(
            [_leg(implied_volatility=0.93)],
            previous,
            now=datetime.fromisoformat("2026-06-20T14:00:00+01:00"),
        )

        self.assertEqual(alerts, ())

    def test_missing_mark_and_iv_do_not_alert(self) -> None:
        alerts, state = build_option_risk_alerts(
            [_leg(mark_price=None, implied_volatility=None, market_value_gbp=None)],
            {"contracts": {}, "sent_alerts": {}},
            now=datetime.fromisoformat("2026-06-20T10:00:00+01:00"),
        )

        self.assertEqual(alerts, ())
        self.assertEqual(state["contracts"], {})

    def test_private_reminder_can_render_option_alerts_without_events(self) -> None:
        option_alert = OptionRiskAlert(
            alert_id="VIX|2026-07-22|C|17|iv-red",
            contract_key="VIX|2026-07-22|C|17",
            severity="red",
            underlying="VIX",
            symbol="VIX 260722C00017000",
            expiry="2026-07-22",
            right="C",
            strike=17.0,
            summary="VIX 期权红色波动提醒：IV 80.0% → 93.0%",
            details=("合约：VIX 260722C00017000", "VIX 期权对波动率曲线非常敏感。"),
            source="Yahoo delayed option chain",
        )

        html, text = _render_reminder((), (option_alert,))

        self.assertIn("期权波动提醒", html)
        self.assertIn("VIX 期权红色波动提醒", text)


if __name__ == "__main__":
    unittest.main()
