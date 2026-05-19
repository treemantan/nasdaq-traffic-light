from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from .config import load_config
from .data_sources import fetch_market_snapshot
from .emailer import send_report_email
from .memory import load_previous_regime, save_current_regime
from .render import render_html_report
from .scoring import score_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and optionally email the Nasdaq Traffic Light report.")
    parser.add_argument("--config", default="config.json", help="Path to JSON config file.")
    parser.add_argument("--dry-run", action="store_true", help="Generate the report without sending email.")
    parser.add_argument("--output", help="Optional explicit output HTML path.")
    args = parser.parse_args()

    config = load_config(args.config)
    snapshot = fetch_market_snapshot()
    previous_regime = load_previous_regime(config.output_dir)
    scored = score_snapshot(snapshot, config.weights, previous_regime=previous_regime, report_timezone=config.report_timezone)

    output_path = Path(args.output) if args.output else config.output_dir / f"market-report-{scored.report_date}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html_report(scored, config.report_title)
    output_path.write_text(html, encoding="utf-8")
    _write_report_payload(output_path.with_suffix(".json"), scored)
    save_current_regime(config.output_dir, scored.report_date, scored.regime.name, scored.summary)

    print(f"Report written to {output_path.resolve()}")
    terminal_light = {"绿灯": "green", "黄灯": "yellow", "红灯": "red"}.get(scored.light_label, scored.light_label)
    print(f"Score: {scored.overall_score}/100, light: {terminal_light}")
    terminal_data_quality = {"正常": "normal", "部分延迟": "partial-delay", "需核验": "needs-review"}.get(
        scored.data_quality,
        scored.data_quality,
    )
    print(f"Regime: {scored.regime.name}, confidence: {scored.regime.confidence_score}/100, data: {terminal_data_quality}")

    if args.dry_run or not config.email.enabled:
        print("Email skipped.")
        return 0

    send_report_email(config.email, scored, html, output_path)
    print("Email sent.")
    return 0


def _write_report_payload(path: Path, scored) -> None:
    path.write_text(json.dumps(asdict(scored), ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)
