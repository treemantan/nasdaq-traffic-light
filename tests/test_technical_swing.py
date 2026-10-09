from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from market_report.etf_monitor import PortfolioPosition
from market_report.price_history import InstrumentIdentity, PriceHistory
from market_report.technical_indicators import PriceBar
from market_report.technical_swing import (
    SwingZone,
    TechnicalSwingReport,
    _classify_status,
    _zones_for_report,
    assess_swing,
    build_technical_swing_report,
    detect_pivots,
    technical_swing_from_payload,
    resolve_swing_universe,
)
from market_report.render import _render_technical_swing
from market_report.render_email import _render_technical_swing_email


def _history(symbol: str = "MSFT", closes: list[float] | None = None) -> PriceHistory:
    values = closes or [100 + index * 0.2 for index in range(220)]
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars = tuple(
        PriceBar(
            timestamp=start + timedelta(days=index),
            open=value - 0.3,
            high=value + 1,
            low=value - 1,
            close=value,
            volume=1_000_000 + index * 1000,
        )
        for index, value in enumerate(values)
    )
    return PriceHistory(
        identity=InstrumentIdentity(symbol, symbol, symbol, "NMS", "USD", "EQUITY"),
        bars=bars,
        interval="1d",
        source="Yahoo",
        observation_at=bars[-1].timestamp,
        fetched_at=datetime.now(timezone.utc),
        quality="live",
    )


def test_resolve_universe_keeps_exchange_suffix_and_holding_precedence() -> None:
    result = resolve_swing_universe(["MSFT"], ["MSFT", "MSFT.L"], "")
    assert [(item.symbol, item.origin) for item in result] == [
        ("MSFT", "holding"),
        ("MSFT.L", "watchlist"),
    ]


def test_resolve_universe_accepts_missing_temporary_tickers() -> None:
    result = resolve_swing_universe([], ["AMD"], None)
    assert [item.symbol for item in result] == ["AMD"]


def test_last_two_bars_are_not_confirmed_pivots() -> None:
    closes = [10, 9, 8, 9, 10, 11, 12, 11, 10]
    pivots = detect_pivots(_history(closes=closes).bars)
    assert all(pivot.index <= len(closes) - 3 for pivot in pivots)
    assert any(pivot.kind == "support" and pivot.index == 2 for pivot in pivots)


def test_report_zones_keep_nearest_support_even_when_deeper_support_is_stronger() -> None:
    deep_support = SwingZone("support", 8.96, 9.46, 87, 4, ("deep",))
    second_support = SwingZone("support", 12.0, 12.5, 82, 3, ("second",))
    third_support = SwingZone("support", 14.0, 14.5, 78, 2, ("third",))
    nearest_support = SwingZone("support", 16.29, 16.68, 30, 1, ("nearest",))

    visible = _zones_for_report(
        (deep_support, second_support, third_support, nearest_support),
        16.6,
        support=True,
    )

    assert nearest_support in visible
    assert visible[0] == nearest_support


def test_cash_like_asset_uses_rate_sensitive_wording() -> None:
    assessment = assess_swing(_history("ERNS.L"), origin="holding", asset_class="cash_like")
    assert assessment.trend == "现金与短债结构"
    assert "趋势破坏" not in assessment.technical_status
    assert "久期" in assessment.note or "收益率" in assessment.note


def test_pipeline_keeps_other_tickers_when_one_fetch_fails() -> None:
    position = PortfolioPosition(
        symbol="MSFT",
        weight_pct=10,
        quantity=1,
        average_cost_gbp=100,
        current_price_gbp=110,
        market_value_gbp=110,
        unrealized_pnl_gbp=10,
        unrealized_pnl_pct=10,
        day_change_pct=1,
        monitor_status="outside-monitor-pool",
    )

    def fetcher(symbol: str) -> PriceHistory:
        if symbol == "BAD":
            raise RuntimeError("missing")
        return _history(symbol)

    report = build_technical_swing_report([position], ["BAD"], None, fetcher=fetcher)
    assert [item.symbol for item in report.assessments] == ["MSFT"]
    assert "BAD" in " ".join(report.warnings)


def test_pipeline_shows_stale_history_only_as_reference() -> None:
    def fetcher(symbol: str) -> PriceHistory:
        history = _history(symbol)
        return replace(history, quality="daily/stale") if symbol == "MSFT" else history

    report = build_technical_swing_report([], ["MSFT", "GOOD"], None, fetcher=fetcher)

    assert [item.symbol for item in report.assessments] == ["MSFT", "GOOD"]
    assert "MSFT 当日动态K线不可用" in " ".join(report.warnings)
    assert "旧日线/盘中行情缺失 1 个" in report.summary


def test_intraday_volume_projection_is_estimate_not_breakout_confirmation() -> None:
    history = _history("MSFT")
    raw_bars = history.bars[:-1] + (replace(history.bars[-1], volume=1_500_000),)
    provisional = replace(
        history, bars=raw_bars, quality="daily/intraday", volume_progress=0.5
    )
    without_volume = replace(history, bars=raw_bars[:-1] + (replace(raw_bars[-1], volume=None),))

    assessment = assess_swing(provisional, origin="watchlist")
    baseline = assess_swing(without_volume, origin="watchlist")

    assert assessment.volume_ratio is not None and assessment.volume_ratio > 2
    assert assessment.volume_label == "预估日量（线性）"
    assert "等待收盘确认" in assessment.volume_confirmation
    assert assessment.scorecard is not None and baseline.scorecard is not None
    assert assessment.scorecard.breakout_score == baseline.scorecard.breakout_score


def test_email_labels_intraday_and_prior_close_with_data_timestamps() -> None:
    intraday_history = replace(
        _history("MSFT"), quality="daily/intraday", volume_progress=0.5,
        observation_at=datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc),
    )
    prior_history = replace(
        _history("AMD"), quality="daily/prior-close",
        observation_at=datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc),
    )
    report = TechnicalSwingReport(
        generated_at="2026-10-08T17:10:00+00:00",
        assessments=(
            assess_swing(intraday_history, origin="watchlist"),
            assess_swing(prior_history, origin="watchlist"),
        ),
        summary="盘中动态K线 1 个；旧日线 1 个。",
    )

    rendered = _render_technical_swing_email(report)

    assert "盘中动态K线（未确认）" in rendered
    assert "上一根完整日线（仅参考）" in rendered
    assert "2026-10-07T20:00:00+00:00" in rendered


def test_breakout_uses_resistance_zone_below_current_close() -> None:
    resistance = SwingZone(
        kind="resistance",
        lower=99,
        upper=100,
        score=80,
        touches=3,
        components=("pivot",),
    )
    status = _classify_status(
        101,
        2,
        None,
        None,
        (),
        (resistance,),
        1.3,
        "强势上行",
        "equity",
    )
    assert status == "突破候选"


def test_swing_scorecard_uses_multi_timeframe_momentum_and_benchmark() -> None:
    values = [100 + index * 0.4 for index in range(220)]
    assessment = assess_swing(_history("MSFT", closes=values), origin="holding", benchmark_return_20d=1.0)
    assert assessment.scorecard is not None
    assert assessment.scorecard.trend_score == 5
    assert assessment.scorecard.momentum_score == 5
    assert assessment.scorecard.total_score >= 16
    assert assessment.scorecard.above_ema5 is True
    assert "高动量" in assessment.scorecard.interpretation


def test_high_score_summary_prioritizes_entry_research_candidates() -> None:
    values = [100 + index * 0.4 for index in range(220)]
    assessment = assess_swing(_history("MSFT", closes=values), origin="watchlist", benchmark_return_20d=1.0)
    report = TechnicalSwingReport(
        generated_at="2026-08-22T00:00:00+00:00",
        assessments=(assessment,),
        summary="test",
    )

    for rendered in (_render_technical_swing(report), _render_technical_swing_email(report)):
        assert "高分进场研究候选" in rendered
        assert "MSFT" in rendered
        assert f"{assessment.scorecard.total_score}/20" in rendered
        assert "不是买入建议" in rendered or "不代表已完成" in rendered


def test_structure_diagnostic_builds_regression_channel_and_cycle_states() -> None:
    values = [100 + index * 0.3 for index in range(220)]
    assessment = assess_swing(_history("MSFT", closes=values), origin="watchlist", benchmark_return_20d=1.0)

    assert assessment.structure is not None
    structure = assessment.structure
    assert structure.channel_window == 90
    assert structure.channel_lower < structure.channel_mid < structure.channel_upper
    assert structure.short_term_state == "短线多头"
    assert structure.medium_term_state == "中期上升"
    assert structure.long_term_state == "长期多头"
    assert "确认" not in structure.summary
    assert structure.confirmation
    assert structure.invalidation


def test_structure_diagnostic_detects_inside_nr7_and_survives_payload_render() -> None:
    history = _history("CRWD")
    bars = list(history.bars)
    previous = bars[-2]
    bars[-1] = PriceBar(
        timestamp=bars[-1].timestamp,
        open=previous.close,
        high=previous.close + 0.20,
        low=previous.close - 0.20,
        close=previous.close + 0.05,
        volume=bars[-1].volume,
    )
    assessment = assess_swing(replace(history, bars=tuple(bars)), origin="watchlist", benchmark_return_20d=1.0)
    report = TechnicalSwingReport("2026-08-22T00:00:00+00:00", (assessment,), (), "test")
    restored = technical_swing_from_payload(asdict(report))

    assert assessment.structure is not None
    assert "Inside Bar" in assessment.structure.bar_patterns
    assert "NR7" in assessment.structure.bar_patterns
    assert restored.assessments[0].structure == assessment.structure
    rendered = _render_technical_swing(restored)
    assert "透明结构诊断" in rendered
    assert "回归通道" in rendered
    assert "延续倾向 / 反转风险" in rendered


def test_breakdown_uses_support_zone_above_current_close() -> None:
    support = SwingZone(
        kind="support",
        lower=100,
        upper=101,
        score=80,
        touches=3,
        components=("pivot",),
    )
    status = _classify_status(
        99,
        -2,
        None,
        None,
        (support,),
        (),
        1.3,
        "中期动能转弱",
        "equity",
    )
    assert status == "支撑失效"
