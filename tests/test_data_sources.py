from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from market_report import data_sources as ds


def _metric(spec: ds.MetricSpec, as_of: date) -> ds.MarketMetric:
    if spec.min_value is not None and spec.max_value is not None:
        value = (spec.min_value + spec.max_value) / 2
    else:
        value = 100.0
    return ds.MarketMetric(
        key=spec.key,
        label=spec.label,
        description=spec.description,
        symbol=spec.symbol,
        source=spec.source,
        value=value,
        previous_value=value * 0.99,
        as_of=as_of,
        fetched_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        unit=spec.unit,
        category=spec.category,
        status="ok",
        warnings=(),
        delayed=True,
        importance=spec.importance,
        freshness="live",
        live_source=spec.source,
    )


@pytest.mark.parametrize("spec", ds.YAHOO_SPECS, ids=lambda spec: spec.key)
def test_yahoo_live_quote_two_days_old_is_marked_stale_for_all_yahoo_specs(monkeypatch, spec):
    monkeypatch.setattr(ds, "_safe_today", lambda: date(2026, 6, 19))

    validated = ds._validate_metric(_metric(spec, date(2026, 6, 17)), spec)

    assert validated.status == "stale"
    assert validated.freshness == "stale"
    assert any("2026-06-17" in warning for warning in validated.warnings)


@pytest.mark.parametrize("spec", ds.YAHOO_SPECS, ids=lambda spec: spec.key)
def test_yahoo_live_quote_one_day_old_is_recent_valid_for_all_yahoo_specs(monkeypatch, spec):
    monkeypatch.setattr(ds, "_safe_today", lambda: date(2026, 6, 19))

    validated = ds._validate_metric(_metric(spec, date(2026, 6, 18)), spec)

    assert validated.status == "ok"
    assert validated.freshness == "recent-valid"


@pytest.mark.parametrize("spec", ds.YAHOO_SPECS, ids=lambda spec: spec.key)
def test_yahoo_live_quote_friday_close_is_recent_valid_on_monday_for_all_yahoo_specs(monkeypatch, spec):
    monkeypatch.setattr(ds, "_safe_today", lambda: date(2026, 6, 22))

    validated = ds._validate_metric(_metric(spec, date(2026, 6, 19)), spec)

    assert validated.status == "ok"
    assert validated.freshness == "recent-valid"
