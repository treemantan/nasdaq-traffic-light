from __future__ import annotations

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
from market_report.privacy import without_portfolio


def main() -> int:
    requested_mode = os.environ.get("EMAIL_MODE", "full").strip().lower()
    mode = emailer._infer_email_mode() if requested_mode == "auto" else requested_mode
    if mode == "serenity":
        return _send_serenity_report()
    if mode == "technical":
        return emailer.main()
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

    public_payload = without_portfolio(payload)
    public_subject, public_html, public_text = emailer._render_message(
        "full", report_path, html, public_payload
    )
    if public_recipients:
        public_result = _send(
            provider,
            public_subject,
            public_html,
            public_text,
            public_recipients,
            report_path,
        )
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

    print(
        "Full report contains imported portfolio data; sending the private report "
        "as an HTML attachment only."
    )
    attachment = _html_attachment(report_path, html, "private-portfolio-report")
    return _send(
        provider,
        f"{public_subject} - Private Portfolio Attachment",
        public_html,
        public_text
        + "\n\nThe complete private portfolio report is attached as an HTML file. "
        + "Private holdings are not embedded in this email body.",
        private_recipients,
        report_path,
        attachments=[attachment],
    )


def _send_serenity_report() -> int:
    prepared = _prepare_serenity_report()
    if isinstance(prepared, int):
        return prepared
    provider, report_path, payload, recipients = prepared
    subject, html, text, serenity_path, serenity_html = _build_serenity_email(
        report_path, payload
    )
    attachment = _html_attachment(
        serenity_path, serenity_html, "serenity-portfolio-report"
    )
    print("Sending the Serenity weekly portfolio report to private recipients only.")
    return _send(
        provider,
        subject,
        html,
        text + "\n\n完整的 Serenity 私人持仓周报已作为 HTML 附件提供。",
        recipients,
        report_path,
        attachments=[attachment],
        mode="serenity",
    )


def _prepare_serenity_report() -> tuple[str, Path, dict, list[str]] | int:
    provider = (os.environ.get("EMAIL_PROVIDER") or "resend").strip().lower()
    if provider not in emailer.VALID_PROVIDERS:
        print(f"Invalid EMAIL_PROVIDER '{provider}'.", file=sys.stderr)
        return 2
    required = (
        ("SMTP_USERNAME", "SMTP_PASSWORD", "PORTFOLIO_EMAIL_TO")
        if provider == "smtp"
        else ("RESEND_API_KEY", "REPORT_EMAIL_FROM", "PORTFOLIO_EMAIL_TO")
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        return 4
    report_path = _latest_market_report(
        Path(os.environ.get("REPORT_OUTPUT_DIR", "output"))
    )
    if report_path is None:
        print("No HTML market report found in output directory.", file=sys.stderr)
        return 5
    payload = emailer._load_payload(report_path)
    if payload is None:
        print(f"Structured report payload not found: {report_path.with_suffix('.json')}", file=sys.stderr)
        return 7
    positions = ((payload.get("etf_monitor") or {}).get("portfolio_positions") or [])
    if not positions:
        print("Serenity mode requires imported private portfolio positions.", file=sys.stderr)
        return 11
    recipients = emailer._parse_recipients(os.environ["PORTFOLIO_EMAIL_TO"])
    if not recipients:
        print("PORTFOLIO_EMAIL_TO does not contain any valid recipient address.", file=sys.stderr)
        return 8
    return provider, report_path, payload, recipients


def _build_serenity_email(
    report_path: Path, payload: dict
) -> tuple[str, str, str, Path, str]:
    from market_report.serenity_report import (
        build_serenity_report,
        render_serenity_email,
        render_serenity_html,
        write_serenity_report,
    )

    report = build_serenity_report(payload)
    output_dir = Path(os.environ.get("REPORT_OUTPUT_DIR", "output"))
    serenity_path, _ = write_serenity_report(report, output_dir)
    serenity_html = render_serenity_html(report)
    subject, html, text = render_serenity_email(report)
    return subject, html, text, serenity_path, serenity_html


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

    report_path = _latest_market_report(
        Path(os.environ.get("REPORT_OUTPUT_DIR", "output"))
    )
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
    return without_portfolio(payload)


def _latest_market_report(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None
    reports = sorted(
        output_dir.glob("market-report-*.html"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


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
    mode: str = "full",
) -> int:
    if provider == "smtp":
        return emailer._send_smtp(subject, html, text, recipients, mode, report_path, attachments=attachments)
    return emailer._send_resend(subject, html, text, recipients, mode, report_path, attachments=attachments)


def _html_attachment(report_path: Path, html: str, stem: str) -> dict[str, str | bytes]:
    report_date = report_path.stem
    for prefix in ("market-report-", "serenity-report-"):
        if report_date.startswith(prefix):
            report_date = report_date[len(prefix) :]
            break
    filename = f"{stem}-{report_date}.html"
    return {
        "filename": filename,
        "content": html.encode("utf-8"),
        "mime_type": "text/html",
    }


if __name__ == "__main__":
    raise SystemExit(main())
