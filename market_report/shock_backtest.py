from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from typing import Any

from .data_sources import MarketMetric
from .etf_monitor import _fetch_yahoo_history
from .shock_alert import assess_market_shock


SHOCK_HISTORY_SYMBOLS = {
    "nasdaq": "^NDX",
    "sp500": "^GSPC",
    "russell2000": "^RUT",
    "vix": "^VIX",
    "vvix": "^VVIX",
    "dxy": "DX-Y.NYB",
}

FEATURE_SCALES = {
    "nasdaq": 1.6,
    "sp500": 1.1,
    "russell2000": 1.6,
    "vix": 10.0,
    "vvix": 8.0,
    "dxy": 0.35,
}


@dataclass(frozen=True)
class MarketShockSample:
    as_of: str
    distance: float
    nasdaq_change_pct: float | None
    sp500_change_pct: float | None
    vix_change_pct: float | None
    vvix_change_pct: float | None
    dxy_change_pct: float | None
    forward_1d: float | None
    forward_5d: float | None
    forward_20d: float | None
    drawdown_5d: float | None
    drawdown_20d: float | None
    phase_id: str
    phase_representative: bool


@dataclass(frozen=True)
class MarketShockBacktest:
    triggered: bool
    shock_type: str
    reliability: str
    sample_count: int
    independent_phase_count: int
    avg_distance: float | None
    forward_1d_avg: float | None
    forward_5d_avg: float | None
    forward_20d_avg: float | None
    hit_rate_5d: float | None
    drawdown_5d_avg: float | None
    drawdown_20d_avg: float | None
    tail_phase_count: int
    tail_phase_rate: float | None
    samples: tuple[MarketShockSample, ...]
    notes: tuple[str, ...]


def analyze_market_shock_history(
    metrics: dict[str, MarketMetric],
    *,
    histories: dict[str, list[tuple[date, float]]] | None = None,
    max_samples: int = 12,
    horizons: tuple[int, ...] = (1, 5, 20),
) -> MarketShockBacktest:
    payload = _payload_from_metrics(metrics)
    assessment = assess_market_shock(payload)
    if not assessment.triggered:
        return _empty_result(False, "未触发市场冲击", "未触发市场冲击")

    current = _feature_vector_from_metrics(metrics)
    if len(current) < 2:
        return _empty_result(True, _shock_type(current), "当前特征不足")

    histories = histories if histories is not None else _fetch_histories()
    rows = _candidate_rows(histories, current, horizons)
    if not rows:
        return _empty_result(True, _shock_type(current), "历史样本不足")

    rows = sorted(rows, key=lambda item: item["distance"])[:max_samples]
    phases = _cluster_samples(rows)
    phase_lookup = {id(row): (phase_id, representative) for phase_id, phase_rows in phases for row, representative in phase_rows}
    samples = tuple(_sample_from_row(row, phase_lookup.get(id(row), ("", False))) for row in rows)

    phase_representatives = [row for _, phase_rows in phases for row, representative in phase_rows if representative]
    tail_reps = [row for row in phase_representatives if _is_tail_case(row)]
    reliability = _reliability(len(phase_representatives), _avg([row["distance"] for row in rows]))
    return MarketShockBacktest(
        triggered=True,
        shock_type=_shock_type(current),
        reliability=reliability,
        sample_count=len(rows),
        independent_phase_count=len(phase_representatives),
        avg_distance=_avg([row["distance"] for row in rows]),
        forward_1d_avg=_avg([row.get("forward_1d") for row in rows]),
        forward_5d_avg=_avg([row.get("forward_5d") for row in rows]),
        forward_20d_avg=_avg([row.get("forward_20d") for row in rows]),
        hit_rate_5d=_hit_rate([row.get("forward_5d") for row in rows]),
        drawdown_5d_avg=_avg([row.get("drawdown_5d") for row in rows]),
        drawdown_20d_avg=_avg([row.get("drawdown_20d") for row in rows]),
        tail_phase_count=len(tail_reps),
        tail_phase_rate=len(tail_reps) / len(phase_representatives) * 100 if phase_representatives else None,
        samples=samples,
        notes=(
            "历史类比只使用候选日期当时已经可见的当日变化，不使用未来收益参与匹配。",
            "样本用于复核冲击后的路径分布，不构成反弹或继续下跌预测。",
        ),
    )


def _fetch_histories() -> dict[str, list[tuple[date, float]]]:
    histories: dict[str, list[tuple[date, float]]] = {}
    for key, symbol in SHOCK_HISTORY_SYMBOLS.items():
        try:
            history = sorted(_fetch_yahoo_history(symbol), key=lambda item: item[0])
            if len(history) >= 260:
                histories[key] = history
        except Exception:
            continue
    return histories


def _candidate_rows(
    histories: dict[str, list[tuple[date, float]]],
    current: dict[str, float],
    horizons: tuple[int, ...],
) -> list[dict[str, Any]]:
    if "nasdaq" not in histories and "sp500" not in histories:
        return []
    all_dates = sorted({day for history in histories.values() for day, _ in history})
    rows = []
    for day in all_dates:
        features = _feature_vector_at(histories, day)
        if not _historical_shock(features):
            continue
        distance, coverage = _distance(current, features)
        if coverage < 0.55:
            continue
        row = {
            "as_of": day,
            "distance": distance,
            "features": features,
            "feature_coverage": coverage,
        }
        row.update(_forward_outcomes(histories, day, horizons))
        rows.append(row)
    return rows


def _feature_vector_from_metrics(metrics: dict[str, MarketMetric]) -> dict[str, float]:
    features = {}
    for key in SHOCK_HISTORY_SYMBOLS:
        metric = metrics.get(key)
        pct = metric.change_pct if metric is not None else None
        if pct is not None and math.isfinite(pct):
            features[key] = float(pct)
    return features


def _feature_vector_at(histories: dict[str, list[tuple[date, float]]], day: date) -> dict[str, float]:
    features = {}
    for key, history in histories.items():
        index = _index_at(history, day)
        if index is None or index <= 0:
            continue
        previous = history[index - 1][1]
        current = history[index][1]
        if previous:
            features[key] = (current / previous - 1) * 100
    return features


def _historical_shock(features: dict[str, float]) -> bool:
    severity = 0
    hard = False
    for key, warning, critical, warning_sev, critical_sev in (
        ("nasdaq", -2.5, -4.0, 25, 35),
        ("sp500", -2.0, -3.0, 24, 32),
        ("russell2000", -3.0, -4.0, 14, 20),
    ):
        value = features.get(key)
        if value is None:
            continue
        if value <= critical:
            severity += critical_sev
            hard = hard or critical_sev >= 20
        elif value <= warning:
            severity += warning_sev
            hard = hard or warning_sev >= 20
    for key, warning, critical, warning_sev, critical_sev in (
        ("vix", 15.0, 25.0, 20, 28),
        ("vvix", 10.0, 15.0, 14, 20),
    ):
        value = features.get(key)
        if value is None:
            continue
        if value >= critical:
            severity += critical_sev
            hard = hard or critical_sev >= 20
        elif value >= warning:
            severity += warning_sev
            hard = hard or warning_sev >= 20
    dxy = features.get("dxy")
    ndx = features.get("nasdaq")
    if dxy is not None and ndx is not None and dxy >= 0.4 and ndx < 0:
        severity += 10
    return bool(features) and (hard or severity >= 30)


def _distance(current: dict[str, float], past: dict[str, float]) -> tuple[float, float]:
    common = [key for key in current if key in past and key in FEATURE_SCALES]
    if not common:
        return 999.0, 0.0
    squared = [((current[key] - past[key]) / FEATURE_SCALES[key]) ** 2 for key in common]
    return math.sqrt(sum(squared) / len(squared)), len(common) / max(len(current), 1)


def _forward_outcomes(
    histories: dict[str, list[tuple[date, float]]],
    day: date,
    horizons: tuple[int, ...],
) -> dict[str, float | None]:
    base = histories.get("nasdaq") or histories.get("sp500") or []
    index = _index_at(base, day)
    if index is None:
        return {}
    current = base[index][1]
    result: dict[str, float | None] = {}
    for horizon in horizons:
        if index + horizon >= len(base):
            continue
        future = base[index + horizon][1]
        result[f"forward_{horizon}d"] = (future / current - 1) * 100
        path = [value for _, value in base[index : index + horizon + 1]]
        trough = min(path)
        result[f"drawdown_{horizon}d"] = (trough / current - 1) * 100
    return result


def _cluster_samples(rows: list[dict[str, Any]], max_gap_days: int = 5) -> list[tuple[str, list[tuple[dict[str, Any], bool]]]]:
    ordered = sorted(rows, key=lambda row: row["as_of"])
    phases: list[list[dict[str, Any]]] = []
    for row in ordered:
        if not phases or (row["as_of"] - phases[-1][-1]["as_of"]).days > max_gap_days:
            phases.append([row])
        else:
            phases[-1].append(row)
    result = []
    for index, phase in enumerate(phases, start=1):
        representative = min(phase, key=lambda row: row["distance"])
        result.append((f"P{index}", [(row, row is representative) for row in phase]))
    return result


def _sample_from_row(row: dict[str, Any], phase: tuple[str, bool]) -> MarketShockSample:
    features = row["features"]
    return MarketShockSample(
        as_of=row["as_of"].isoformat(),
        distance=round(float(row["distance"]), 2),
        nasdaq_change_pct=features.get("nasdaq"),
        sp500_change_pct=features.get("sp500"),
        vix_change_pct=features.get("vix"),
        vvix_change_pct=features.get("vvix"),
        dxy_change_pct=features.get("dxy"),
        forward_1d=row.get("forward_1d"),
        forward_5d=row.get("forward_5d"),
        forward_20d=row.get("forward_20d"),
        drawdown_5d=row.get("drawdown_5d"),
        drawdown_20d=row.get("drawdown_20d"),
        phase_id=phase[0],
        phase_representative=phase[1],
    )


def _is_tail_case(row: dict[str, Any]) -> bool:
    forward_5d = row.get("forward_5d")
    drawdown_5d = row.get("drawdown_5d")
    forward_20d = row.get("forward_20d")
    drawdown_20d = row.get("drawdown_20d")
    return (
        (isinstance(forward_5d, (int, float)) and forward_5d < 0)
        or (isinstance(drawdown_5d, (int, float)) and drawdown_5d <= -5)
        or (isinstance(forward_20d, (int, float)) and forward_20d < -3)
        or (isinstance(drawdown_20d, (int, float)) and drawdown_20d <= -8)
    )


def _shock_type(features: dict[str, float]) -> str:
    parts = []
    if features.get("nasdaq", 0) <= -2.5 or features.get("sp500", 0) <= -2:
        parts.append("权益急跌")
    if features.get("vix", 0) >= 15 or features.get("vvix", 0) >= 10:
        parts.append("波动率扩张")
    if features.get("dxy", 0) >= 0.4 and features.get("nasdaq", 0) < 0:
        parts.append("美元压力共振")
    return " + ".join(parts) if parts else "市场冲击"


def _reliability(phase_count: int, avg_distance: float | None) -> str:
    if phase_count < 3:
        return "历史可比性偏低"
    if avg_distance is not None and avg_distance <= 0.9:
        return "历史可比性较高"
    if avg_distance is not None and avg_distance <= 1.4:
        return "历史可比性中等"
    return "历史可比性偏低"


def _payload_from_metrics(metrics: dict[str, MarketMetric]) -> dict[str, Any]:
    return {
        "metrics": {
            key: {"metric": {"value": metric.value, "previous_value": metric.previous_value, "label": metric.label}}
            for key, metric in metrics.items()
        }
    }


def _index_at(history: list[tuple[date, float]], day: date) -> int | None:
    dates = [item[0] for item in history]
    index = bisect_right(dates, day) - 1
    return index if index >= 0 else None


def _avg(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _hit_rate(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]
    if not clean:
        return None
    return sum(1 for value in clean if value > 0) / len(clean) * 100


def _empty_result(triggered: bool, shock_type: str, reliability: str) -> MarketShockBacktest:
    return MarketShockBacktest(
        triggered=triggered,
        shock_type=shock_type,
        reliability=reliability,
        sample_count=0,
        independent_phase_count=0,
        avg_distance=None,
        forward_1d_avg=None,
        forward_5d_avg=None,
        forward_20d_avg=None,
        hit_rate_5d=None,
        drawdown_5d_avg=None,
        drawdown_20d_avg=None,
        tail_phase_count=0,
        tail_phase_rate=None,
        samples=(),
        notes=(),
    )
