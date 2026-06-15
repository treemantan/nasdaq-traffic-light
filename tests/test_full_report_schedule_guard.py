from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SPEC = spec_from_file_location(
    "wait_for_full_report_window",
    Path(__file__).resolve().parents[1] / "scripts" / "wait_for_full_report_window.py",
)
assert _SPEC and _SPEC.loader
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
full_report_wait_seconds = _MODULE.full_report_wait_seconds


def test_full_report_waits_until_post_close_window_when_started_early() -> None:
    now = datetime(2026, 6, 15, 18, 45, tzinfo=timezone.utc)

    wait_seconds = full_report_wait_seconds(now, target_uk_date="2026-06-15")

    assert wait_seconds == 82 * 60


def test_full_report_does_not_wait_after_post_close_window() -> None:
    now = datetime(2026, 6, 15, 21, 30, tzinfo=timezone.utc)

    assert full_report_wait_seconds(now, target_uk_date="2026-06-15") == 0


def test_full_report_uses_target_uk_date_for_delayed_runs_after_midnight() -> None:
    now = datetime(2026, 6, 15, 23, 30, tzinfo=timezone.utc)

    assert full_report_wait_seconds(now, target_uk_date="2026-06-15") == 0
