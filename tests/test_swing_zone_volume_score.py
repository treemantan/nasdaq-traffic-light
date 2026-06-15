from datetime import datetime, timezone

from market_report.technical_swing import SwingPivot, cluster_pivots


def _support_pivot(index: int, price: float, volume: float) -> SwingPivot:
    return SwingPivot(
        "support",
        index,
        price,
        datetime(2026, 1, min(index, 28), tzinfo=timezone.utc),
        volume,
    )


def test_zone_volume_score_does_not_reward_below_recent_volume_baseline() -> None:
    zones = cluster_pivots(
        (_support_pivot(10, 100, 700), _support_pivot(20, 101, 900)),
        kind="support",
        atr_value=2,
        current_price=120,
        bars_count=30,
        baseline_volume=1000,
    )

    assert "成交量比0.80x" in zones[0].components
    assert "成交量+0" in zones[0].components


def test_zone_volume_score_gives_partial_reward_near_recent_volume_baseline() -> None:
    zones = cluster_pivots(
        (_support_pivot(10, 100, 900), _support_pivot(20, 101, 1100)),
        kind="support",
        atr_value=2,
        current_price=120,
        bars_count=30,
        baseline_volume=1000,
    )

    assert "成交量比1.00x" in zones[0].components
    assert "成交量+5" in zones[0].components


def test_zone_volume_score_rewards_clear_relative_volume_reaction() -> None:
    zones = cluster_pivots(
        (_support_pivot(10, 100, 1500), _support_pivot(20, 101, 1700)),
        kind="support",
        atr_value=2,
        current_price=120,
        bars_count=30,
        baseline_volume=1000,
    )

    assert "成交量比1.60x" in zones[0].components
    assert "成交量+10" in zones[0].components
