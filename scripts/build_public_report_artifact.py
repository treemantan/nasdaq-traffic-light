from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import send_report_email as emailer

from market_report.config import load_config
from market_report.privacy import without_portfolio
from market_report.render import render_html_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a portfolio-redacted report for public GitHub artifacts."
    )
    parser.add_argument("--config", default="config.example.json")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--artifact-dir", default=".public-artifact")
    args = parser.parse_args()

    report_path = _latest_market_report(Path(args.output_dir))
    if report_path is None:
        print("No generated HTML market report found.", file=sys.stderr)
        return 2
    payload = emailer._load_payload(report_path)
    if payload is None:
        print(f"Structured report payload not found for {report_path}.", file=sys.stderr)
        return 3

    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in (
        *artifact_dir.glob("market-report-*.html"),
        *artifact_dir.glob("market-report-*.json"),
    ):
        stale_path.unlink()
    public_payload = without_portfolio(payload)
    public_report = emailer._report_from_payload(public_payload)
    title = load_config(args.config).report_title

    public_html_path = artifact_dir / report_path.name
    public_json_path = artifact_dir / report_path.with_suffix(".json").name
    public_html_path.write_text(
        render_html_report(public_report, title),
        encoding="utf-8",
    )
    public_json_path.write_text(
        json.dumps(public_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Public portfolio-redacted HTML artifact written to {public_html_path.resolve()}")
    print(f"Public portfolio-redacted JSON artifact written to {public_json_path.resolve()}")
    return 0


def _latest_market_report(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None
    reports = sorted(
        output_dir.glob("market-report-*.html"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


if __name__ == "__main__":
    raise SystemExit(main())
