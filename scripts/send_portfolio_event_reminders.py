from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from html import escape
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import send_report_email as emailer
from market_report.portfolio_events import (
    PortfolioEventObservation,
    build_portfolio_event_monitor,
    due_portfolio_event_reminders,
)


STATE_PATH = Path("output") / "cache" / "portfolio_event_reminders.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Send private reminders for due portfolio events.")
    parser.add_argument("--portfolio", default="portfolio.csv", help="Imported portfolio CSV path.")
    parser.add_argument("--state", default=str(STATE_PATH), help="Reminder state JSON path.")
    parser.add_argument("--lookahead-hours", type=float, default=7.0)
    parser.add_argument("--now", help="Optional ISO timestamp used for testing.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    recipients = emailer._parse_recipients(os.environ.get("PORTFOLIO_EMAIL_TO", ""))
    if not recipients:
        print("PORTFOLIO_EMAIL_TO is not configured; private portfolio event reminders skipped.")
        return 0
    portfolio_path = Path(args.portfolio)
    if not portfolio_path.exists():
        print(f"Portfolio file not found; event reminders skipped: {portfolio_path}")
        return 0

    symbols = _portfolio_symbols(portfolio_path)
    current_time = datetime.fromisoformat(args.now) if args.now else datetime.now().astimezone()
    monitor = build_portfolio_event_monitor(symbols, now=current_time)
    state_path = Path(args.state)
    sent = _load_sent_ids(state_path)
    due = due_portfolio_event_reminders(
        monitor,
        now=current_time,
        lookahead_hours=args.lookahead_hours,
        sent_event_ids=sent,
    )
    if not due:
        print("No portfolio event reminder is due.")
        return 0

    subject = f"Portfolio Event Reminder - {current_time:%Y-%m-%d %H:%M}"
    message_html, message_text = _render_reminder(due)
    if args.dry_run:
        print(f"Dry run: {len(due)} portfolio event reminder(s) due.")
        print(message_text)
        return 0

    provider = (os.environ.get("EMAIL_PROVIDER") or "resend").strip().lower()
    if provider not in emailer.VALID_PROVIDERS:
        print(f"Invalid EMAIL_PROVIDER '{provider}'.", file=sys.stderr)
        return 2
    required_env = emailer.REQUIRED_SMTP_ENV if provider == "smtp" else emailer.REQUIRED_RESEND_ENV
    missing = [name for name in required_env if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        return 4
    report_path = Path("portfolio-event-reminder")
    if provider == "smtp":
        result = emailer._send_smtp(subject, message_html, message_text, recipients, "portfolio-event", report_path)
    else:
        result = emailer._send_resend(subject, message_html, message_text, recipients, "portfolio-event", report_path)
    if result == 0:
        _save_sent_ids(state_path, sent | {event.event_id for event in due}, current_time)
    return result


def _portfolio_symbols(path: Path) -> list[str]:
    import csv

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            str(row.get("symbol") or row.get("ticker") or "").strip()
            for row in csv.DictReader(handle)
            if str(row.get("symbol") or row.get("ticker") or "").strip()
        ]


def _load_sent_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    return set(payload.get("sent_event_ids", ()))


def _save_sent_ids(path: Path, sent_ids: set[str], now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"updated_at": now.isoformat(), "sent_event_ids": sorted(sent_ids)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _render_reminder(events: tuple[PortfolioEventObservation, ...]) -> tuple[str, str]:
    html_rows = "".join(
        f"""<li style="margin-bottom:14px;"><strong>{escape(event.title)}</strong><br>
        {escape(" / ".join(event.symbols))} · {escape(event.scope)} · {escape(event.status)} · {escape(event.event_time_label)}<br>
        {escape(event.note)}<br>
        关注：{escape("；".join(event.watch_items))}<br>
        <a href="{escape(event.source_url)}">{escape(event.source_label)}</a> ·
        <a href="{escape(event.progress_source_url)}">查看进展：{escape(event.progress_source_label)}</a></li>"""
        for event in events
    )
    text_rows = "\n\n".join(
        "\n".join(
            (
                event.title,
                f"{' / '.join(event.symbols)} | {event.scope} | {event.status} | {event.event_time_label}",
                event.note,
                f"关注：{'；'.join(event.watch_items)}",
                f"来源：{event.source_label} {event.source_url}",
                f"进展：{event.progress_source_label} {event.progress_source_url}",
            )
        )
        for event in events
    )
    html = f"""<!doctype html><html lang="zh-CN"><body>
      <h2>持仓事件提醒</h2>
      <p>以下持仓相关窗口已进入提醒区间。价格回撤预警用于触发复核，不等同于基本面已经恶化。</p>
      <ul>{html_rows}</ul>
      <p style="color:#666;">本邮件仅用于事件跟踪，不构成交易建议。</p>
    </body></html>"""
    text = (
        "持仓事件提醒\n\n"
        "以下持仓相关窗口已进入提醒区间。价格回撤预警用于触发复核，不等同于基本面已经恶化。\n\n"
        f"{text_rows}\n\n本邮件仅用于事件跟踪，不构成交易建议。"
    )
    return html, text


if __name__ == "__main__":
    raise SystemExit(main())
