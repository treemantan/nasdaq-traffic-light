from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from market_report.serenity_report import build_serenity_report, write_serenity_report


def main() -> int:
    output_dir = Path(os.environ.get("REPORT_OUTPUT_DIR", "output"))
    payload_path = _latest_market_payload(output_dir)
    if payload_path is None:
        print("No structured market report found for Serenity weekly report.", file=sys.stderr)
        return 2
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    positions = ((payload.get("etf_monitor") or {}).get("portfolio_positions") or [])
    if not positions:
        print("Serenity mode requires imported private portfolio positions.", file=sys.stderr)
        return 3
    report = build_serenity_report(payload)
    html_path, json_path = write_serenity_report(report, output_dir)
    print(f"Serenity weekly report written to {html_path}")
    print(f"Serenity structured report written to {json_path}")
    return 0


def _latest_market_payload(output_dir: Path) -> Path | None:
    candidates = sorted(
        output_dir.glob("market-report-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


if __name__ == "__main__":
    raise SystemExit(main())
