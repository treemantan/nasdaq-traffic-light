from datetime import date, datetime, timezone

from market_report.data_sources import MarketMetric, MarketSnapshot
from market_report.macro_brief import build_macro_daily_brief
from market_report.render import render_html_report
from market_report.scoring import score_snapshot


def _metric(key: str, value: float, previous: float, unit: str = "") -> MarketMetric:
    return MarketMetric(
        key=key,
        label=key.upper(),
        description=key,
        symbol=key,
        source="test",
        value=value,
        previous_value=previous,
        as_of=date(2026, 7, 10),
        fetched_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        unit=unit,
        category="macro",
        status="ok",
    )


def test_macro_brief_prioritizes_normalized_market_moves() -> None:
    snapshot = MarketSnapshot(
        as_of=date(2026, 7, 10),
        fetched_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        metrics={
            "nasdaq": _metric("nasdaq", 9800, 10000),
            "vix": _metric("vix", 18, 15),
            "treasury_10y": _metric("treasury_10y", 4.55, 4.50, "%"),
            "dxy": _metric("dxy", 100.2, 100.0),
        },
        warnings=(),
    )
    brief = build_macro_daily_brief(score_snapshot(snapshot, previous_regime="Goldilocks"))

    assert len(brief.signals) == 3
    assert {item.label for item in brief.signals[:2]} == {"NASDAQ", "VIX"}
    signal_values = {item.label: item.value for item in brief.signals}
    assert signal_values["VIX"] == "Level 18.00 | 日变 +20.00%"
    assert "Level 4.55% | 日变 +5bp" in signal_values.values()
    assert brief.transition
    assert len(brief.actions) == 3


def test_macro_brief_maps_score_to_a_risk_posture() -> None:
    snapshot = MarketSnapshot(
        as_of=date(2026, 7, 10),
        fetched_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        metrics={
            "nasdaq": _metric("nasdaq", 10010, 10000),
            "vix": _metric("vix", 16, 16),
            "treasury_10y": _metric("treasury_10y", 4.2, 4.2, "%"),
            "dxy": _metric("dxy", 99.8, 99.8),
        },
        warnings=(),
    )
    brief = build_macro_daily_brief(score_snapshot(snapshot))

    assert brief.posture
    assert brief.posture_note
    assert brief.verify


def test_macro_brief_reports_score_delta_from_structured_memory() -> None:
    snapshot = MarketSnapshot(
        as_of=date(2026, 7, 10),
        fetched_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        metrics={
            "nasdaq": _metric("nasdaq", 9800, 10000),
            "vix": _metric("vix", 20, 17),
            "treasury_10y": _metric("treasury_10y", 4.6, 4.5, "%"),
            "dxy": _metric("dxy", 101, 100),
        },
        warnings=(),
    )
    report = score_snapshot(snapshot, previous_regime="Goldilocks", previous_state={"overall_score": 40})
    brief = build_macro_daily_brief(report)

    assert report.score_delta == report.overall_score - 40
    assert "40→" in brief.score_change


def test_html_report_uses_three_reading_layers_without_removing_deep_evidence() -> None:
    snapshot = MarketSnapshot(
        as_of=date(2026, 7, 10),
        fetched_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        metrics={
            "nasdaq": _metric("nasdaq", 10010, 10000),
            "vix": _metric("vix", 16, 16),
            "treasury_10y": _metric("treasury_10y", 4.2, 4.2, "%"),
            "dxy": _metric("dxy", 99.8, 99.8),
        },
        warnings=(),
    )
    html = render_html_report(score_snapshot(snapshot), "Test report")

    assert "Layer 1 · Daily Decision Brief" in html
    assert '<details class="report-layer" open>' in html
    assert "Layer 2 · Macro Workbench" in html
    assert "Layer 3 · Evidence & Deep Dive" in html
    assert html.index("Layer 1 · Daily Decision Brief") < html.index("Layer 2 · Macro Workbench")
    assert html.index("Layer 2 · Macro Workbench") < html.index("Layer 3 · Evidence & Deep Dive")
    assert "数据源、最近有效值与新鲜度" in html
