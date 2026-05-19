from __future__ import annotations

from datetime import datetime, timedelta, timezone


def format_timestamp(timestamp: datetime, timezone_name: str) -> str:
    local_time = timestamp.astimezone(_timezone_for(timestamp, timezone_name))
    return local_time.isoformat(timespec="seconds")


def timezone_label(timezone_name: str) -> str:
    if timezone_name == "America/New_York":
        return "America/New_York"
    if timezone_name == "Europe/London":
        return "Europe/London"
    return "UTC"


def _timezone_for(timestamp: datetime, timezone_name: str) -> timezone:
    utc_time = timestamp.astimezone(timezone.utc)
    if timezone_name == "America/New_York":
        return timezone(timedelta(hours=-4 if _is_us_dst(utc_time) else -5))
    if timezone_name == "Europe/London":
        return timezone(timedelta(hours=1 if _is_uk_dst(utc_time) else 0))
    return timezone.utc


def _is_us_dst(utc_time: datetime) -> bool:
    year = utc_time.year
    start = _nth_weekday(year, 3, 6, 2).replace(hour=7, tzinfo=timezone.utc)
    end = _nth_weekday(year, 11, 6, 1).replace(hour=6, tzinfo=timezone.utc)
    return start <= utc_time < end


def _is_uk_dst(utc_time: datetime) -> bool:
    year = utc_time.year
    start = _last_weekday(year, 3, 6).replace(hour=1, tzinfo=timezone.utc)
    end = _last_weekday(year, 10, 6).replace(hour=1, tzinfo=timezone.utc)
    return start <= utc_time < end


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> datetime:
    day = datetime(year, month, 1)
    offset = (weekday - day.weekday()) % 7
    return day + timedelta(days=offset + 7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> datetime:
    if month == 12:
        day = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        day = datetime(year, month + 1, 1) - timedelta(days=1)
    return day - timedelta(days=(day.weekday() - weekday) % 7)
