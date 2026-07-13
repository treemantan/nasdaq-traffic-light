import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

from market_report.data_sources import MarketMetric
from market_report.memory import (
    load_metric_history,
    load_previous_regime,
    load_previous_state,
    save_current_state,
)


def test_legacy_state_remains_readable(tmp_path) -> None:
    (tmp_path / "narrative_state.json").write_text(
        json.dumps({"report_date": "2026-07-10", "regime": "Goldilocks", "summary": "legacy"}),
        encoding="utf-8",
    )

    assert load_previous_regime(tmp_path) == "Goldilocks"
    assert load_previous_state(tmp_path)["summary"] == "legacy"


def test_structured_state_saves_score_metrics_portfolio_and_event_exposure(tmp_path) -> None:
    metric = MarketMetric(
        key="vix",
        label="VIX",
        description="VIX",
        symbol="^VIX",
        source="test",
        value=18.0,
        previous_value=16.0,
        as_of=date(2026, 7, 10),
        fetched_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        status="ok",
    )
    report = SimpleNamespace(
        report_date="2026-07-10",
        overall_score=58,
        summary="test",
        regime=SimpleNamespace(name="Higher for Longer"),
        metrics={"vix": SimpleNamespace(metric=metric)},
        etf_monitor=SimpleNamespace(
            portfolio_positions=[
                SimpleNamespace(
                    symbol="NVDA",
                    weight_pct=7.5,
                    option_legs_json=json.dumps(
                        [
                            {
                                "underlying": "DRAM",
                                "expiry": "2026-07-24",
                                "right": "P",
                                "strike": 60.5,
                                "signed_contracts": -1,
                                "unrealized_pnl_gbp": 39.28,
                            }
                        ]
                    ),
                )
            ]
        ),
        event_risk_ledger=SimpleNamespace(
            entries=[
                SimpleNamespace(
                    label="AI policy",
                    direction="risk_up",
                    risk_score=72,
                    portfolio_symbols=("NVDA",),
                    portfolio_weight_pct=7.5,
                    market_confirmation="partial",
                )
            ]
        ),
    )

    save_current_state(tmp_path, report)
    state = load_previous_state(tmp_path)

    assert (tmp_path / "cache" / "narrative_state.json").exists()
    assert not (tmp_path / "narrative_state.json").exists()
    assert state["version"] == 3
    assert state["overall_score"] == 58
    assert state["metrics"]["vix"]["change_pct"] == 12.5
    assert state["portfolio"] == [{"symbol": "NVDA", "weight_pct": 7.5}]
    assert state["option_closeout"]["total_gbp"] == 39.28
    assert state["option_closeout"]["source"] == "IBKR"
    assert state["event_exposures"][0]["risk_score"] == 72


def test_cached_state_takes_precedence_over_legacy_root_state(tmp_path) -> None:
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "narrative_state.json").write_text(
        json.dumps({"regime": "current"}), encoding="utf-8"
    )
    (tmp_path / "narrative_state.json").write_text(
        json.dumps({"regime": "legacy"}), encoding="utf-8"
    )

    assert load_previous_regime(tmp_path) == "current"


def test_previous_state_uses_prior_day_when_same_day_runs_exist(tmp_path) -> None:
    state = {
        "report_date": "2026-07-12",
        "overall_score": 60,
        "history": [
            {"report_date": "2026-07-10", "overall_score": 55},
            {"report_date": "2026-07-12", "overall_score": 60},
        ],
    }
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "narrative_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    previous = load_previous_state(tmp_path, before_date="2026-07-12")

    assert previous["report_date"] == "2026-07-10"
    assert previous["overall_score"] == 55
    assert load_metric_history(tmp_path, before_date="2026-07-12") == [
        {"report_date": "2026-07-10", "metrics": {}, "option_closeout": {}}
    ]
