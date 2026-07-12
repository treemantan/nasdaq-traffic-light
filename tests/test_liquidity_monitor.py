from __future__ import annotations

from types import SimpleNamespace

from market_report.liquidity_monitor import calculate_net_liquidity, format_net_liquidity


def _current(fed: float, tga: float, rrp: float) -> dict:
    return {
        "fed_balance_sheet": SimpleNamespace(metric=SimpleNamespace(value=fed)),
        "tga": SimpleNamespace(metric=SimpleNamespace(value=tga)),
        "rrp": SimpleNamespace(metric=SimpleNamespace(value=rrp)),
    }


def _history_row(report_date: str, fed: float, tga: float, rrp: float) -> dict:
    return {
        "report_date": report_date,
        "metrics": {
            "fed_balance_sheet": {"value": fed},
            "tga": {"value": tga},
            "rrp": {"value": rrp},
        },
    }


def test_net_liquidity_reports_level_and_weekly_changes() -> None:
    history = [
        _history_row("2026-06-12", 7000, 700, 20),
        _history_row("2026-07-03", 7020, 720, 10),
        _history_row("2026-07-06", 7010, 710, 8),
    ]

    result = calculate_net_liquidity(_current(7040, 700, 5), history, "2026-07-13")

    assert result.level_bn == 6335
    assert result.one_week_change_bn == 43
    assert result.four_week_change_bn == 55
    assert result.status == "ok"
    assert "$6.33tn" in format_net_liquidity(result)
    assert "1周 +43bn（注入）" in format_net_liquidity(result)


def test_net_liquidity_marks_cold_start_without_inventing_changes() -> None:
    result = calculate_net_liquidity(_current(7040, 700, 5), [], "2026-07-13")

    assert result.level_bn == 6335
    assert result.one_week_change_bn is None
    assert result.four_week_change_bn is None
    assert result.status == "building_history"
    assert "历史积累中" in format_net_liquidity(result)
