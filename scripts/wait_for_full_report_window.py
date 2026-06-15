from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from datetime import date, datetime, time as datetime_time, timezone

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from market_report.time_utils import _timezone_for


POST_CLOSE_UK_TIME = datetime_time(21, 7)
DEFAULT_MAX_WAIT_SECONDS = 2 * 60 * 60


def full_report_wait_seconds(
    now_utc: datetime | None = None,
    *,
    target_uk_date: str | None = None,
    post_close_time: datetime_time = POST_CLOSE_UK_TIME,
    max_wait_seconds: int = DEFAULT_MAX_WAIT_SECONDS,
) -> int:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_london = now.astimezone(_timezone_for(now, "Europe/London"))
    target_date = date.fromisoformat(target_uk_date) if target_uk_date else now_london.date()
    target_probe_utc = datetime.combine(target_date, post_close_time, timezone.utc)
    london_tz = _timezone_for(target_probe_utc, "Europe/London")
    post_close_london = datetime.combine(target_date, post_close_time, london_tz)
    wait_seconds = int((post_close_london - now_london).total_seconds())
    if wait_seconds <= 0:
        return 0
    return min(wait_seconds, max_wait_seconds)


def main() -> int:
    mode = os.environ.get("EMAIL_MODE", "")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if mode != "full" or event_name != "schedule":
        print(f"Post-close guard skipped: event={event_name}, EMAIL_MODE={mode}.")
        return 0

    target_uk_date = os.environ.get("REPORT_LOCAL_DATE") or os.environ.get("TARGET_UK_DATE")
    max_wait_seconds = int(os.environ.get("MAX_FULL_REPORT_WAIT_SECONDS", str(DEFAULT_MAX_WAIT_SECONDS)))
    wait_seconds = full_report_wait_seconds(target_uk_date=target_uk_date, max_wait_seconds=max_wait_seconds)
    if wait_seconds <= 0:
        print("Full report post-close guard: already inside the post-close window.")
        return 0

    print(
        "Full report post-close guard: waiting "
        f"{wait_seconds} seconds before generating the full report."
    )
    time.sleep(wait_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
