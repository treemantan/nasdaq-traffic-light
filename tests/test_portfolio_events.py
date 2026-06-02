from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest

from market_report.portfolio_events import (
    build_portfolio_event_monitor,
    due_portfolio_event_reminders,
)


class PortfolioEventMonitorTests(unittest.TestCase):
    def test_nflx_events_include_auditable_sources(self) -> None:
        monitor = build_portfolio_event_monitor(
            ["NFLX"],
            now=datetime.fromisoformat("2026-06-02T12:00:00+01:00"),
        )
        self.assertEqual(len(monitor.events), 3)
        self.assertIn("Netflix IR", monitor.events[0].source_label)
        self.assertTrue(monitor.events[0].source_url.startswith("https://"))
        self.assertTrue(monitor.events[0].progress_source_url.startswith("https://"))

    def test_exact_event_is_due_inside_seven_hour_window(self) -> None:
        monitor = build_portfolio_event_monitor(
            ["NFLX"],
            now=datetime.fromisoformat("2026-06-04T17:30:00+01:00"),
        )
        due = due_portfolio_event_reminders(
            monitor,
            now=datetime.fromisoformat("2026-06-04T17:30:00+01:00"),
            lookahead_hours=7,
        )
        self.assertEqual([event.event_id for event in due], ["nflx-2026-annual-meeting"])

    def test_date_only_event_is_due_before_new_york_open(self) -> None:
        monitor = build_portfolio_event_monitor(
            ["NFLX"],
            now=datetime.fromisoformat("2026-07-07T08:30:00+01:00"),
        )
        due = due_portfolio_event_reminders(
            monitor,
            now=datetime.fromisoformat("2026-07-07T08:30:00+01:00"),
        )
        self.assertEqual(
            [event.event_id for event in due],
            ["nflx-sector-paramount-wbd-eu-review-2026-07-07"],
        )

    def test_sent_event_is_not_repeated(self) -> None:
        monitor = build_portfolio_event_monitor(
            ["NFLX"],
            now=datetime.fromisoformat("2026-06-04T17:30:00+01:00"),
        )
        due = due_portfolio_event_reminders(
            monitor,
            now=datetime.fromisoformat("2026-06-04T17:30:00+01:00"),
            sent_event_ids={"nflx-2026-annual-meeting"},
        )
        self.assertEqual(due, ())

    def test_unknown_symbol_has_no_registered_events(self) -> None:
        monitor = build_portfolio_event_monitor(
            ["VUAG.L"],
            now=datetime.fromisoformat("2026-06-02T12:00:00+01:00"),
        )
        self.assertEqual(monitor.events, ())


if __name__ == "__main__":
    unittest.main()
