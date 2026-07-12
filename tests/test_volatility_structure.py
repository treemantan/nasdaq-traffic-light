from __future__ import annotations

from types import SimpleNamespace

from market_report.volatility_structure import assess_volatility_structure, format_volatility_structure


def _metric(value: float, previous: float) -> SimpleNamespace:
    change_pct = (value / previous - 1) * 100
    return SimpleNamespace(metric=SimpleNamespace(value=value, change_pct=change_pct))


def test_normal_term_structure_and_rising_dispersion_are_distinguished() -> None:
    metrics = {
        "vix9d": _metric(13, 13.5),
        "vix": _metric(15, 15),
        "vix3m": _metric(18, 18),
        "vixeq": _metric(49, 47),
        "cor1m": _metric(4, 5),
        "vix_future_1": _metric(16, 16),
        "vix_future_2": _metric(18, 18),
        "vix_future_3": _metric(19, 19),
    }

    result = assess_volatility_structure(metrics)

    assert result.term_state.startswith("正常升水")
    assert result.vixeq_vix_ratio == 49 / 15
    assert "Basis Risk扩大" in result.dispersion_state
    assert result.futures_state.endswith("升水")
    assert "VIXEQ/VIX 3.27x" in format_volatility_structure(result)


def test_vix9d_inversion_flags_near_term_event_risk() -> None:
    metrics = {
        "vix9d": _metric(22, 18),
        "vix": _metric(18, 17),
        "vix3m": _metric(20, 20),
    }

    result = assess_volatility_structure(metrics)

    assert result.term_state.startswith("短端倒挂")
    assert result.dispersion_state == "离散度数据不足"


def test_missing_term_components_degrade_explicitly() -> None:
    result = assess_volatility_structure({"vix": _metric(15, 14)})

    assert result.term_state == "期限结构数据不足"
    assert "不可用" in format_volatility_structure(result)
