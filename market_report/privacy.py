from __future__ import annotations

from copy import deepcopy


def without_portfolio(payload: dict) -> dict:
    """Return a report payload with imported private-portfolio data removed."""
    sanitized = deepcopy(payload)
    sanitized["portfolio_event_monitor"] = None

    monitor = sanitized.get("etf_monitor")
    if not isinstance(monitor, dict):
        _remove_portfolio_context_from_iron_condor(sanitized)
        return sanitized

    removed_symbols = {
        str(item.get("symbol") or "").upper()
        for item in (monitor.get("assets") or [])
        if isinstance(item, dict) and _is_portfolio_supplement(item)
    }
    monitor["assets"] = [
        item
        for item in (monitor.get("assets") or [])
        if not (isinstance(item, dict) and _is_portfolio_supplement(item))
    ]
    monitor["portfolio_positions"] = []
    monitor["portfolio_summary"] = []
    monitor["portfolio_warnings"] = []
    monitor["portfolio_total_value_gbp"] = None
    monitor["portfolio_performance"] = None
    monitor["portfolio_exposures"] = []
    monitor["portfolio_exposure_notes"] = []
    monitor["portfolio_mag7_exposures"] = []
    monitor["portfolio_mag7_notes"] = []

    if removed_symbols:
        for field in ("summary", "warnings", "change_summary"):
            monitor[field] = [
                item
                for item in (monitor.get(field) or [])
                if not _mentions_any_symbol(item, removed_symbols)
            ]

    _remove_portfolio_context_from_iron_condor(sanitized)
    return sanitized


def _is_portfolio_supplement(asset: dict) -> bool:
    key = str(asset.get("key") or "").lower()
    provider = str(asset.get("provider") or "").lower()
    theme = str(asset.get("theme") or "").lower()
    return (
        key.startswith("portfolio-")
        or provider == "portfolio"
        or theme == "portfolio supplement"
    )


def _mentions_any_symbol(value: object, symbols: set[str]) -> bool:
    text = str(value).upper()
    return any(symbol and symbol in text for symbol in symbols)


def _remove_portfolio_context_from_iron_condor(payload: dict) -> None:
    assessment = payload.get("iron_condor")
    if not isinstance(assessment, dict):
        return
    for field in ("positives", "warnings", "blockers"):
        assessment[field] = [
            item
            for item in (assessment.get(field) or [])
            if not _contains_portfolio_context(item)
        ]


def _contains_portfolio_context(value: object) -> bool:
    text = str(value).lower()
    return any(
        marker in text
        for marker in (
            "组合持仓",
            "组合层面",
            "私人持仓",
            "private portfolio",
            "portfolio holding",
        )
    )
