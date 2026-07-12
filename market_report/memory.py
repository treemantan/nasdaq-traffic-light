from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATE_FILENAME = "narrative_state.json"
CACHE_DIRECTORY = "cache"


def _state_path(output_dir: Path) -> Path:
    return output_dir / CACHE_DIRECTORY / STATE_FILENAME


def load_previous_state(output_dir: Path, before_date: str | None = None) -> dict[str, Any]:
    # GitHub Actions persists output/cache between otherwise stateless runners.
    # Keep the old output-root location readable for existing local installs.
    for path in (_state_path(output_dir), output_dir / STATE_FILENAME):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            if before_date:
                candidates = [
                    item
                    for item in (data.get("history") or [])
                    if isinstance(item, dict)
                    and isinstance(item.get("report_date"), str)
                    and item["report_date"] < before_date
                ]
                if candidates:
                    return max(candidates, key=lambda item: item["report_date"])
                if isinstance(data.get("report_date"), str) and data["report_date"] >= before_date:
                    return {}
            return data
    return {}


def load_previous_regime(output_dir: Path) -> str | None:
    data = load_previous_state(output_dir)
    regime = data.get("regime")
    return regime if isinstance(regime, str) else None


def load_metric_history(output_dir: Path, before_date: str | None = None) -> list[dict[str, Any]]:
    data = load_previous_state(output_dir)
    rows = data.get("history") or []
    return [
        {"report_date": item.get("report_date"), "metrics": item.get("metrics") or {}}
        for item in rows
        if isinstance(item, dict)
        and isinstance(item.get("report_date"), str)
        and (before_date is None or item["report_date"] < before_date)
    ]


def save_current_regime(output_dir: Path, report_date: str, regime: str, summary: str) -> None:
    path = _state_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_date": report_date,
        "regime": regime,
        "summary": summary,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_current_state(output_dir: Path, report: object) -> None:
    path = _state_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    metrics = getattr(report, "metrics", {}) or {}
    metric_values = {
        key: {
            "value": getattr(item.metric, "value", None),
            "change": getattr(item.metric, "change", None),
            "change_pct": getattr(item.metric, "change_pct", None),
            "as_of": item.metric.as_of.isoformat() if getattr(item.metric, "as_of", None) else None,
        }
        for key, item in metrics.items()
    }
    event_ledger = getattr(report, "event_risk_ledger", None)
    event_exposures = [
        {
            "label": entry.label,
            "direction": entry.direction,
            "risk_score": entry.risk_score,
            "portfolio_symbols": list(entry.portfolio_symbols),
            "portfolio_weight_pct": entry.portfolio_weight_pct,
            "market_confirmation": entry.market_confirmation,
        }
        for entry in (getattr(event_ledger, "entries", ()) or ())
        if entry.portfolio_symbols
    ]
    etf_monitor = getattr(report, "etf_monitor", None)
    portfolio = [
        {"symbol": item.symbol, "weight_pct": item.weight_pct}
        for item in (getattr(etf_monitor, "portfolio_positions", ()) or ())
    ]
    regime = getattr(report, "regime", None)
    payload = {
        "version": 2,
        "report_date": getattr(report, "report_date", ""),
        "regime": getattr(regime, "name", ""),
        "summary": getattr(report, "summary", ""),
        "overall_score": getattr(report, "overall_score", None),
        "metrics": metric_values,
        "portfolio": portfolio,
        "event_exposures": event_exposures,
    }
    existing = load_previous_state(output_dir)
    history = [
        item
        for item in (existing.get("history") or [])
        if isinstance(item, dict) and item.get("report_date") != payload["report_date"]
    ]
    if existing.get("report_date") and existing.get("report_date") != payload["report_date"]:
        history.append({key: value for key, value in existing.items() if key != "history"})
    history.append(dict(payload))
    payload["history"] = sorted(history, key=lambda item: str(item.get("report_date", "")))[-260:]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
