from market_report.render import _fmt_swing_zone, _render_swing_zone_details
from market_report.render_email import _fmt_swing_email_zone
from market_report.technical_swing import SwingZone, _render_zone_details, _zone_text


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
