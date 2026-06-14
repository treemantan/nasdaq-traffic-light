from __future__ import annotations

from datetime import datetime, timedelta, timezone

from market_report.etf_monitor import PortfolioPosition
from market_report.price_history import InstrumentIdentity, PriceHistory
from market_report.technical_indicators import PriceBar
from market_report.technical_swing import (
    SwingZone,
    _classify_status,
    assess_swing,
    build_technical_swing_report,
    detect_pivots,
    resolve_swing_universe,
)


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
