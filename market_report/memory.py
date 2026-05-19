from __future__ import annotations

import json
from pathlib import Path


def load_previous_regime(output_dir: Path) -> str | None:
    path = output_dir / "narrative_state.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    regime = data.get("regime")
    return regime if isinstance(regime, str) else None


def save_current_regime(output_dir: Path, report_date: str, regime: str, summary: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "narrative_state.json"
    payload = {
        "report_date": report_date,
        "regime": regime,
        "summary": summary,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
