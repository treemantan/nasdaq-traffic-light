from market_report.render import _fmt_swing_zone
from market_report.render_email import _fmt_swing_email_zone
from market_report.technical_swing import SwingZone, _zone_text


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
