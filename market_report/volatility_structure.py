from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VolatilityStructure:
    vix9d: float | None
    vix: float | None
    vix3m: float | None
    vixeq: float | None
    cor1m: float | None
    vixeq_vix_ratio: float | None
    term_state: str
    dispersion_state: str
    futures_state: str


def assess_volatility_structure(metrics: dict[str, Any]) -> VolatilityStructure:
    vix9d = _value(metrics, "vix9d")
    vix = _value(metrics, "vix")
    vix3m = _value(metrics, "vix3m")
    vixeq = _value(metrics, "vixeq")
    cor1m = _value(metrics, "cor1m")
    ratio = vixeq / vix if vixeq is not None and vix not in (None, 0) else None
    futures = [_value(metrics, f"vix_future_{month}") for month in range(1, 4)]

    if vix9d is None or vix is None or vix3m is None:
        term_state = "期限结构数据不足"
    elif vix9d > vix * 1.05:
        term_state = "短端倒挂：近期事件风险显著前置"
    elif vix > vix3m * 1.02:
        term_state = "30日/3个月倒挂：系统压力正在前移"
    elif vix9d < vix < vix3m:
        term_state = "正常升水：远期波动高于短期"
    else:
        term_state = "期限结构偏平：关注事件窗口变化"

    vixeq_change = _change_pct(metrics, "vixeq")
    cor1m_change = _change_pct(metrics, "cor1m")
    if vixeq is None or cor1m is None:
        dispersion_state = "离散度数据不足"
    elif (vixeq_change or 0) > 0 and (cor1m_change or 0) < 0:
        dispersion_state = "个股波动上升、相关性下降：分化风险上升，指数对冲Basis Risk扩大"
    elif (vixeq_change or 0) > 0 and (cor1m_change or 0) > 0:
        dispersion_state = "个股波动与相关性同步上升：系统性风险确认增强"
    elif (vixeq_change or 0) < 0 and (cor1m_change or 0) > 0:
        dispersion_state = "波动暂缓但相关性抬升：警惕共同冲击"
    else:
        dispersion_state = "个股波动与相关性未同步恶化"

    if any(value is None for value in futures):
        futures_state = "VIX期货曲线不可用"
    elif futures[0] < futures[1] < futures[2]:
        futures_state = f"VIX期货 M1 {futures[0]:.2f} / M2 {futures[1]:.2f} / M3 {futures[2]:.2f}：升水"
    elif futures[0] > futures[1]:
        futures_state = f"VIX期货 M1 {futures[0]:.2f} / M2 {futures[1]:.2f} / M3 {futures[2]:.2f}：前端倒挂"
    else:
        futures_state = f"VIX期货 M1 {futures[0]:.2f} / M2 {futures[1]:.2f} / M3 {futures[2]:.2f}：偏平"

    return VolatilityStructure(
        vix9d=vix9d,
        vix=vix,
        vix3m=vix3m,
        vixeq=vixeq,
        cor1m=cor1m,
        vixeq_vix_ratio=ratio,
        term_state=term_state,
        dispersion_state=dispersion_state,
        futures_state=futures_state,
    )


def format_volatility_structure(structure: VolatilityStructure) -> str:
    levels = " / ".join(
        value
        for value in (
            _format_level("9D", structure.vix9d),
            _format_level("30D", structure.vix),
            _format_level("3M", structure.vix3m),
        )
        if value
    )
    ratio = (
        f"VIXEQ/VIX {structure.vixeq_vix_ratio:.2f}x"
        if structure.vixeq_vix_ratio is not None
        else "VIXEQ/VIX不可用"
    )
    correlation = f"COR1M {structure.cor1m:.2f}" if structure.cor1m is not None else "COR1M不可用"
    return (
        f"波动期限 {levels or '不可用'}：{structure.term_state}；{structure.futures_state}；"
        f"{ratio}，{correlation}：{structure.dispersion_state}。"
    )


def _value(metrics: dict[str, Any], key: str) -> float | None:
    value = getattr(getattr(metrics.get(key), "metric", None), "value", None)
    return float(value) if isinstance(value, (int, float)) else None


def _change_pct(metrics: dict[str, Any], key: str) -> float | None:
    value = getattr(getattr(metrics.get(key), "metric", None), "change_pct", None)
    return float(value) if isinstance(value, (int, float)) else None


def _format_level(label: str, value: float | None) -> str:
    return f"{label} {value:.2f}" if value is not None else ""
