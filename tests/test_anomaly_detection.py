from __future__ import annotations

from market_report.anomaly_detection import detect_change_anomaly


def _history(values: list[float]) -> list[dict]:
    return [
        {"report_date": f"2026-01-{index + 1:02d}", "metrics": {"vix": {"change_pct": value}}}
        for index, value in enumerate(values)
    ]


def test_dual_z_scores_confirm_clear_outlier() -> None:
    values = [float((index % 5) - 2) for index in range(40)]

    result = detect_change_anomaly("vix", 12.0, _history(values), use_absolute_change=False)

    assert result.classification == "confirmed"
    assert result.z_score is not None and result.z_score > 2
    assert result.robust_z_score is not None and result.robust_z_score > 2.5


def test_insufficient_history_does_not_claim_statistical_anomaly() -> None:
    result = detect_change_anomaly("vix", 12.0, _history([0.0] * 10), use_absolute_change=False)

    assert result.classification == "insufficient_history"
    assert result.sample_size == 10


def test_window_uses_only_most_recent_observations() -> None:
    values = [100.0] * 20 + [float((index % 5) - 2) for index in range(60)]

    result = detect_change_anomaly("vix", 12.0, _history(values), use_absolute_change=False)

    assert result.sample_size == 60
    assert result.classification == "confirmed"
