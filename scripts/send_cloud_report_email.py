from __future__ import annotations

from copy import deepcopy
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


def main() -> int:
    requested_mode = os.environ.get("EMAIL_MODE", "full").strip().lower()
    mode = emailer._infer_email_mode() if requested_mode == "auto" else requested_mode
    if mode != "full" or not Path("portfolio.csv").exists():
        return emailer.main()

    prepared = _prepare_full_report()
    if isinstance(prepared, int):
        return prepared
    provider, report_path, html, payload, group_recipients = prepared

    private_recipients = emailer._parse_recipients(os.environ.get("PORTFOLIO_EMAIL_TO", ""))
    if private_recipients:
        private_keys = {_recipient_key(address) for address in private_recipients}
        public_recipients = [
            address for address in group_recipients if _recipient_key(address) not in private_keys
        ]
    else:
        public_recipients = group_recipients

    if public_recipients:
        subject, public_html, public_text = emailer._render_message(
            "full", report_path, html, _without_portfolio(payload)
        )
        public_result = _send(provider, subject, public_html, public_text, public_recipients, report_path)
        if public_result:
            return public_result
    else:
        print("All full-report recipients are portfolio recipients; skipping the sanitized group edition.")

    if not private_recipients:
        print(
            "Full report contains imported portfolio data, but PORTFOLIO_EMAIL_TO is not configured. "
            "Sent the sanitized group edition only."
        )
        return 0

    private_subject, private_html, private_text = emailer._render_message("full", report_path, html, payload)
    print("Full report contains imported portfolio data; sending a second private portfolio edition.")
    attachment = _html_attachment(report_path, html, "private-portfolio-report")
    return _send(
        provider,
        f"{private_subject} - Private Portfolio",
        private_html,
        private_text
        + "\n\nThis private edition includes imported portfolio data. "
        + "The complete private HTML report is attached for full table/detail review.",
        private_recipients,
        report_path,
        attachments=[attachment],
    )


def _prepare_full_report() -> tuple[str, Path, str, dict, list[str]] | int:
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
        print("No HTML market report found in output directory.", file=sys.stderr)
        return 5
    html = report_path.read_text(encoding="utf-8")
    if not html.strip():
        print(f"HTML report is empty: {report_path}", file=sys.stderr)
        return 6
    payload = emailer._load_payload(report_path)
    if payload is None:
        print(f"Structured report payload not found: {report_path.with_suffix('.json')}", file=sys.stderr)
        return 7
    recipients = emailer._parse_recipients(os.environ["REPORT_EMAIL_TO"])
    if not recipients:
        print("REPORT_EMAIL_TO does not contain any valid recipient address.", file=sys.stderr)
        return 8
    return provider, report_path, html, payload, recipients


def _without_portfolio(payload: dict) -> dict:
    sanitized = deepcopy(payload)
    sanitized["portfolio_event_monitor"] = None
    monitor = sanitized.get("etf_monitor")
    if isinstance(monitor, dict):
        monitor["portfolio_positions"] = []
        monitor["portfolio_summary"] = []
        monitor["portfolio_warnings"] = []
        monitor["portfolio_total_value_gbp"] = None
        monitor["portfolio_performance"] = None
        monitor["portfolio_exposures"] = []
        monitor["portfolio_exposure_notes"] = []
        monitor["portfolio_mag7_exposures"] = []
        monitor["portfolio_mag7_notes"] = []
    return sanitized


def _recipient_key(address: str) -> str:
    return address.strip().lower()


def _send(
    provider: str,
    subject: str,
    html: str,
    text: str,
    recipients: list[str],
    report_path: Path,
    attachments: list[dict[str, str | bytes]] | None = None,
) -> int:
    if provider == "smtp":
        return emailer._send_smtp(subject, html, text, recipients, "full", report_path, attachments=attachments)
    return emailer._send_resend(subject, html, text, recipients, "full", report_path, attachments=attachments)


def _html_attachment(report_path: Path, html: str, stem: str) -> dict[str, str | bytes]:
    report_date = report_path.stem
    if report_date.startswith("market-report-"):
        report_date = report_date[len("market-report-") :]
    filename = f"{stem}-{report_date}.html"
    return {
        "filename": filename,
        "content": html.encode("utf-8"),
        "mime_type": "text/html",
    }


if __name__ == "__main__":
    raise SystemExit(main())
