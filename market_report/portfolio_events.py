from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .time_utils import _timezone_for


EVENTS_PATH = Path("data") / "portfolio_events.json"


@dataclass(frozen=True)
class PortfolioEvent:
    event_id: str
    symbols: tuple[str, ...]
    title: str
    event_type: str
    scope: str
    status: str
    source_label: str
    source_url: str
    progress_source_label: str
    progress_source_url: str
    note: str
    watch_items: tuple[str, ...]
    event_at: str = ""
    event_date: str = ""
    reminder_rule: str = "premarket"
    reminder_hours_before: float = 6.0


@dataclass(frozen=True)
class PortfolioEventObservation:
    event_id: str
    symbols: tuple[str, ...]
    title: str
    event_type: str
    scope: str
    status: str
    source_label: str
    source_url: str
    progress_source_label: str
    progress_source_url: str
    note: str
    watch_items: tuple[str, ...]
    event_at: datetime
    reminder_at: datetime
    reminder_rule: str
    event_time_label: str
    days_until: int
    alert_level: str


@dataclass(frozen=True)
class PortfolioEventMonitor:
    generated_at: str
    summary: str
    events: tuple[PortfolioEventObservation, ...]
    review_required_symbols: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def build_portfolio_event_monitor(
    positions: Iterable[object],
    *,
    now: datetime | None = None,
    events_path: Path = EVENTS_PATH,
    horizon_days: int = 150,
) -> PortfolioEventMonitor:
    current_time = _aware_now(now)
    held_symbols, alert_levels = _held_symbols_and_alerts(positions)
    if not held_symbols:
        return PortfolioEventMonitor(
            generated_at=current_time.isoformat(),
            summary="当前没有可用于事件复核的持仓。",
            events=(),
        )

    try:
        definitions = _load_events(events_path)
    except (OSError, ValueError, TypeError) as exc:
        return PortfolioEventMonitor(
            generated_at=current_time.isoformat(),
            summary="持仓事件日历暂不可用。",
            events=(),
            warnings=(f"持仓事件配置读取失败：{exc}",),
        )

    observations: list[PortfolioEventObservation] = []
    for event in definitions:
        matched_symbols = tuple(symbol for symbol in event.symbols if symbol in held_symbols)
        if not matched_symbols:
            continue
        event_at, reminder_at, time_label = _resolve_event_times(event)
        if event_at < current_time - timedelta(days=1):
            continue
        if event_at > current_time + timedelta(days=horizon_days):
            continue
        observations.append(
            PortfolioEventObservation(
                event_id=event.event_id,
                symbols=matched_symbols,
                title=event.title,
                event_type=event.event_type,
                scope=event.scope,
                status=event.status,
                source_label=event.source_label,
                source_url=event.source_url,
                progress_source_label=event.progress_source_label,
                progress_source_url=event.progress_source_url,
                note=event.note,
                watch_items=event.watch_items,
                event_at=event_at,
                reminder_at=reminder_at,
                reminder_rule=event.reminder_rule,
                event_time_label=time_label,
                days_until=max(0, (event_at.date() - current_time.date()).days),
                alert_level=_event_alert_level(matched_symbols, alert_levels),
            )
        )

    observations.sort(key=lambda item: item.event_at)
    covered_symbols = {symbol for item in observations for symbol in item.symbols}
    review_required = tuple(
        sorted(
            symbol
            for symbol, alert_level in alert_levels.items()
            if alert_level == "红色回撤复核" and symbol not in covered_symbols
        )
    )
    summary = (
        f"未来{horizon_days}日内识别到{len(observations)}个持仓相关观察窗口。"
        if observations
        else f"未来{horizon_days}日内暂无已登记的持仓相关事件。"
    )
    if review_required:
        summary += f" 仍有{len(review_required)}个红色预警ticker需要补充人工复核来源。"
    return PortfolioEventMonitor(
        generated_at=current_time.isoformat(),
        summary=summary,
        events=tuple(observations),
        review_required_symbols=review_required,
    )


def due_portfolio_event_reminders(
    monitor: PortfolioEventMonitor,
    *,
    now: datetime | None = None,
    lookahead_hours: float = 7.0,
    sent_event_ids: Iterable[str] = (),
) -> tuple[PortfolioEventObservation, ...]:
    current_time = _aware_now(now)
    sent = set(sent_event_ids)
    due: list[PortfolioEventObservation] = []
    for event in monitor.events:
        if event.event_id in sent:
            continue
        if event.reminder_rule == "premarket":
            current_ny = current_time.astimezone(_new_york_timezone(current_time))
            if current_ny.date() == event.event_at.astimezone(_new_york_timezone(event.event_at)).date() and current_ny.time() < time(9, 30):
                due.append(event)
            continue
        remaining = event.event_at - current_time
        if timedelta(0) <= remaining <= timedelta(hours=lookahead_hours):
            due.append(event)
    return tuple(due)


def _load_events(path: Path) -> tuple[PortfolioEvent, ...]:
    raw_events = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_events, list):
        raise ValueError("event configuration must be a JSON list")
    return tuple(
        PortfolioEvent(
            event_id=str(item["event_id"]),
            symbols=tuple(_normalize_symbol(symbol) for symbol in item["symbols"]),
            title=str(item["title"]),
            event_type=str(item["event_type"]),
            scope=str(item["scope"]),
            status=str(item["status"]),
            source_label=str(item["source_label"]),
            source_url=str(item["source_url"]),
            progress_source_label=str(item["progress_source_label"]),
            progress_source_url=str(item["progress_source_url"]),
            note=str(item.get("note", "")),
            watch_items=tuple(str(value) for value in item.get("watch_items", ())),
            event_at=str(item.get("event_at", "")),
            event_date=str(item.get("event_date", "")),
            reminder_rule=str(item.get("reminder_rule", "premarket")),
            reminder_hours_before=float(item.get("reminder_hours_before", 6.0)),
        )
        for item in raw_events
    )


def _resolve_event_times(event: PortfolioEvent) -> tuple[datetime, datetime, str]:
    if event.event_at:
        event_at = datetime.fromisoformat(event.event_at)
        if event_at.tzinfo is None:
            raise ValueError(f"{event.event_id}: event_at must include a timezone")
        reminder_at = event_at - timedelta(hours=event.reminder_hours_before)
        label = _format_uk_event_time_label(event_at)
        return event_at, reminder_at, label
    if not event.event_date:
        raise ValueError(f"{event.event_id}: event_at or event_date is required")
    event_day = date.fromisoformat(event.event_date)
    event_timezone = _new_york_timezone(datetime.combine(event_day, time(12), tzinfo=timezone.utc))
    event_at = datetime.combine(event_day, time(9, 30), tzinfo=event_timezone)
    reminder_at = datetime.combine(event_day, time(8, 0), tzinfo=event_timezone)
    return event_at, reminder_at, f"{_format_uk_event_time(event_at)}（美股开盘前观察，默认 09:30 ET）"


def _held_symbols_and_alerts(positions: Iterable[object]) -> tuple[set[str], dict[str, str]]:
    symbols: set[str] = set()
    alerts: dict[str, str] = {}
    for position in positions:
        raw_symbol = position if isinstance(position, str) else getattr(position, "symbol", "")
        symbol = _normalize_symbol(str(raw_symbol))
        if not symbol:
            continue
        symbols.add(symbol)
        peak_watch = "" if isinstance(position, str) else str(getattr(position, "peak_watch", ""))
        drawdown_regime = "" if isinstance(position, str) else str(getattr(position, "drawdown_regime", ""))
        if "红色" in peak_watch or "趋势破坏" in drawdown_regime:
            alerts[symbol] = "红色回撤复核"
        elif "黄色" in peak_watch:
            alerts[symbol] = "黄色回撤复核"
    return symbols, alerts


def _event_alert_level(symbols: Iterable[str], alert_levels: dict[str, str]) -> str:
    levels = {alert_levels.get(symbol, "") for symbol in symbols}
    if "红色回撤复核" in levels:
        return "红色回撤复核"
    if "黄色回撤复核" in levels:
        return "黄色回撤复核"
    return "持仓事件观察"


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    return normalized[:-2] if normalized.endswith(".L") else normalized


def _aware_now(now: datetime | None) -> datetime:
    value = now or datetime.now().astimezone()
    if value.tzinfo is None:
        return value.replace(tzinfo=_new_york_timezone(value.replace(tzinfo=timezone.utc)))
    return value


def _new_york_timezone(reference: datetime):
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return _timezone_for(reference, "America/New_York")


def _london_timezone(reference: datetime):
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return _timezone_for(reference, "Europe/London")


def _format_uk_event_time_label(event_at: datetime) -> str:
    uk_label = _format_uk_event_time(event_at)
    original_label = _format_original_event_time(event_at)
    return uk_label if original_label == uk_label else f"{uk_label}（原始 {original_label}）"


def _format_uk_event_time(event_at: datetime) -> str:
    return event_at.astimezone(_london_timezone(event_at)).strftime("%Y-%m-%d %H:%M UK")


def _format_original_event_time(event_at: datetime) -> str:
    offset = event_at.utcoffset()
    if offset is None:
        return event_at.strftime("%Y-%m-%d %H:%M")
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return event_at.strftime("%Y-%m-%d %H:%M") + f" UTC{sign}{hours:02d}:{minutes:02d}"
