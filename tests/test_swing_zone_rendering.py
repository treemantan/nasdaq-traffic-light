from market_report.price_history import InstrumentIdentity
from market_report.render import _fmt_swing_zone, _render_swing_card, _render_swing_zone_details
from market_report.render_email import _fmt_swing_email_zone
from market_report.technical_indicators import IndicatorSnapshot
from market_report.technical_swing import (
    SwingAssessment,
    SwingZone,
    TechnicalScorecard,
    _render_zone_details,
    _standalone_card,
    _zone_text,
)


def test_zone_scores_are_labelled_as_strength() -> None:
    zone = SwingZone(
        kind="support",
        lower=98.5,
        upper=100.0,
        score=72,
        touches=3,
        components=("3次触及",),
    )

    assert "强度 72/100" in _fmt_swing_zone(zone)
    assert "强度 72/100" in _fmt_swing_email_zone(zone)
    assert "强度 72/100" in _zone_text(zone)


def test_zone_detail_discloses_score_components_and_distance() -> None:
    zone = SwingZone(
        kind="support",
        lower=98.5,
        upper=100.0,
        score=72,
        touches=3,
        components=("3次触及", "新近度+17", "成交量+10"),
    )

    html = _render_swing_zone_details("支撑", zone, 125.0)

    assert "<details" in html
    assert "支撑强度拆解" in html
    assert "距现价 -20.00%" in html
    assert "3次触及" in html
    assert "新近度+17" in html
    assert "不是上涨概率" in html


def test_standalone_zone_detail_uses_same_disclosure_language() -> None:
    zone = SwingZone(
        kind="resistance",
        lower=118.0,
        upper=121.0,
        score=60,
        touches=2,
        components=("2次触及", "新近度+10", "成交量+0"),
    )

    html = _render_zone_details("阻力", zone, 109.2)

    assert "阻力强度拆解" in html
    assert "距现价 +8.06%" in html
    assert "不是上涨概率" in html


def test_full_report_swing_card_exposes_raw_technical_data_for_review() -> None:
    html = _render_swing_card(_assessment())

    assert "Raw Technical Data" in html
    assert "EMA5 / EMA10 / EMA21" in html
    assert "101.25 / 100.50 / 99.75" in html
    assert "SMA50 / SMA200" in html
    assert "96.50 / 88.25" in html
    assert "ATR14 / RSI14 / MACD Hist" in html
    assert "3.25 / 61.40 / 1.23" in html
    assert "20D / 60D / vs QQQ 20D" in html
    assert "+6.50% / +14.20% / +2.40%" in html
    assert "成交量比 / 20日均量" in html
    assert "1.35x / 1,250,000" in html


def test_standalone_technical_card_exposes_raw_technical_data_for_review() -> None:
    html = _standalone_card(_assessment())

    assert "Raw Technical Data" in html
    assert "EMA5 / EMA10 / EMA21" in html
    assert "101.25 / 100.50 / 99.75" in html
    assert "ATR14 / RSI14 / MACD Hist" in html
    assert "3.25 / 61.40 / 1.23" in html
    assert "20D / 60D / vs QQQ 20D" in html
    assert "+6.50% / +14.20% / +2.40%" in html
    assert "成交量比 / 20日均量" in html
    assert "1.35x / 1,250,000" in html


def _assessment() -> SwingAssessment:
    return SwingAssessment(
        symbol="MSFT",
        origin="holding",
        identity=InstrumentIdentity("MSFT", "MSFT", "Microsoft", "NMS", "USD", "EQUITY"),
        current_price=102.0,
        change_pct=1.2,
        indicators=IndicatorSnapshot(
            ema5=101.25,
            ema10=100.5,
            ema21=99.75,
            sma50=96.5,
            sma200=88.25,
            atr14=3.25,
            rsi14=61.4,
            macd_histogram=1.23,
            return_20d=6.5,
            return_60d=14.2,
            average_volume_20=1_250_000,
        ),
        trend="强势上行",
        technical_status="突破候选",
        supports=(),
        resistances=(),
        invalidation_level=94.25,
        volume_ratio=1.35,
        volume_label="小幅放量",
        volume_confirmation="上涨伴随放量",
        note="观察确认。",
        data_source="Yahoo",
        data_timestamp="2026-07-03T20:00:00+00:00",
        data_quality="live",
        asset_class="equity",
        scorecard=TechnicalScorecard(
            above_ema5=True,
            above_ema10=True,
            above_ema21=True,
            above_sma50=True,
            above_sma200=True,
            trend_score=5,
            momentum_score=4,
            breakout_score=3,
            total_score=16,
            benchmark_return_20d=4.1,
            relative_strength_20d=2.4,
            regime="强势多头 / Strong Bull",
            interpretation="高动量，注意过热",
            components=("均线位置 5/5",),
        ),
    )
