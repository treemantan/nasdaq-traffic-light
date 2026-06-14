from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from market_report.technical_swing import (
    technical_swing_from_payload,
    write_technical_swing_report,
)


def main() -> int:
    output_dir = Path("output")
    payload_path = _latest_market_payload(output_dir)
    if payload_path is None:
        print("No structured market report found for Technical Swing output.", file=sys.stderr)
        return 2
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    report = technical_swing_from_payload(payload.get("technical_swing") or {})
    html_path, json_path = write_technical_swing_report(report, output_dir)
    print(f"Technical Swing report written to {html_path}")
    print(f"Technical Swing structured report written to {json_path}")
    return 0


def _latest_market_payload(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None
    reports = sorted(
        output_dir.glob("market-report-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


if __name__ == "__main__":
    raise SystemExit(main())
