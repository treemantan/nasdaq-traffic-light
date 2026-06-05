from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import send_report_email as emailer
from market_report.shock_alert import (
    MarketShockAssessment,
    assess_market_shock,
    metric_line,
    should_send_shock_alert,
    update_shock_state,
)


STATE_PATH = Path("output") / "cache" / "market_shock_alerts.json"


def main() -> int:
    provider = (os.environ.get("EMAIL_PROVIDER") or "resend").strip().lower()
    if provider not in emailer.VALID_PROVIDERS:
        print(f"Invalid EMAIL_PROVIDER '{provider}'.", file=sys.stderr)
        return 2

    required_env = emailer.REQUIRED_SMTP_ENV if provider == "smtp" else emailer.REQUIRED_RESEND_ENV
    missing = [name for name in required_env if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        return 4

    report_path = emailer._latest_html_report(Path(os.environ.get("REPORT_OUTPUT_DIR", "output")))
    if report_path is None:
        print("No HTML market report found; emergency shock alert skipped.", file=sys.stderr)
        return 5
    payload = emailer._load_payload(report_path)
    if payload is None:
        print(f"Structured report payload not found: {report_path.with_suffix('.json')}", file=sys.stderr)
        return 7

    assessment = assess_market_shock(payload)
    report_date = str(payload.get("report_date") or emailer._report_date(report_path))
    if not assessment.triggered:
        print("No emergency market shock detected.")
        return 0

    state = _load_state()
    if not should_send_shock_alert(assessment, state, report_date):
        previous = (state.get("dates") or {}).get(report_date, {})
        print(
            "Emergency market shock already sent for "
            f"{report_date}; previous max severity {previous.get('max_severity')}, "
            f"current severity {assessment.severity_score}. Skipping duplicate."
        )
        return 0

    recipients = _shock_recipients()
    if not recipients:
        print("No recipients configured for emergency market shock alert.", file=sys.stderr)
        return 8

    subject, html, text = _render_shock_message(payload, assessment)
    if provider == "smtp":
        result = emailer._send_smtp(subject, html, text, recipients, "shock", report_path)
    else:
        result = emailer._send_resend(subject, html, text, recipients, "shock", report_path)
    if result:
        return result

    _save_state(update_shock_state(state, report_date, assessment))
    print(
        "Emergency market shock alert sent. "
        f"Severity: {assessment.severity_score}/100. Recipients: {len(recipients)}."
    )
    return 0


def _shock_recipients() -> list[str]:
    recipients = []
    for env_name in ("REPORT_EMAIL_TO", "PORTFOLIO_EMAIL_TO"):
        for address in emailer._parse_recipients(os.environ.get(env_name, "")):
            key = address.lower()
            if key not in {item.lower() for item in recipients}:
                recipients.append(address)
    return recipients


def _render_shock_message(payload: dict, assessment: MarketShockAssessment) -> tuple[str, str, str]:
    stamp = emailer._uk_stamp()
    subject = f"紧急市场风险警报 - {stamp} - {assessment.subject_suffix}"
    metrics = [
        metric_line(payload, "nasdaq"),
        metric_line(payload, "sp500"),
        metric_line(payload, "russell2000"),
        metric_line(payload, "vix"),
        metric_line(payload, "vvix"),
        metric_line(payload, "dxy"),
        metric_line(payload, "treasury_10y"),
    ]
    trigger_rows = "".join(
        "<tr>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #3b2630;color:#f3f4f6;'>{_esc(item.label)}</td>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #3b2630;color:#fecaca;'>{_esc(item.value_text)}</td>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #3b2630;color:#d1d5db;'>{_esc(item.threshold_text)}</td>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #3b2630;color:#d1d5db;'>{_esc(item.note)}</td>"
        "</tr>"
        for item in assessment.triggers
    )
    metric_items = "".join(f"<li>{_esc(item)}</li>" for item in metrics)
    action_items = "".join(f"<li>{_esc(item)}</li>" for item in assessment.actions)
    body = f"""
      <p style="margin:0 0 12px;color:#fecaca;font-weight:700;">{_esc(assessment.summary)}</p>
      <p style="margin:0 0 14px;color:#d1d5db;">冲击强度：{assessment.severity_score}/100 · 等级：{_esc(assessment.level)}</p>
      <h3 style="font-size:15px;color:#f3f4f6;margin:16px 0 8px;">核心市场指标</h3>
      <ul style="margin-top:0;">{metric_items}</ul>
      <h3 style="font-size:15px;color:#f3f4f6;margin:16px 0 8px;">触发条件</h3>
      <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;background:#1f151b;border:1px solid #7f1d1d;">
        <thead><tr>
          <th align="left" style="padding:8px 10px;color:#fca5a5;">信号</th>
          <th align="left" style="padding:8px 10px;color:#fca5a5;">当前</th>
          <th align="left" style="padding:8px 10px;color:#fca5a5;">阈值</th>
          <th align="left" style="padding:8px 10px;color:#fca5a5;">含义</th>
        </tr></thead>
        <tbody>{trigger_rows}</tbody>
      </table>
      <h3 style="font-size:15px;color:#f3f4f6;margin:16px 0 8px;">操作层提醒</h3>
      <ul>{action_items}</ul>
      <p style="color:#9ca3af;">本邮件是市场冲击监控，不构成买卖建议；它用于阻止在波动率扩张窗口内做未经复核的新增仓位。</p>
    """
    html = emailer._html_shell("紧急市场风险警报", body)
    text = "\n".join(
        [
            subject,
            assessment.summary,
            f"Severity: {assessment.severity_score}/100 ({assessment.level})",
            "Metrics: " + "; ".join(metrics),
            "Triggers: "
            + "; ".join(
                f"{item.label} {item.value_text} ({item.threshold_text}) - {item.note}"
                for item in assessment.triggers
            ),
            "Actions: " + "; ".join(assessment.actions),
            "This is a market shock monitor, not trading advice.",
        ]
    )
    return subject, html, text


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _esc(value: object) -> str:
    return emailer.escape(str(value))


if __name__ == "__main__":
    raise SystemExit(main())
