from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnomalyResult:
    z_score: float | None
    robust_z_score: float | None
    sample_size: int
    classification: str


def detect_change_anomaly(
    key: str,
    current_move: float,
    history: list[dict[str, Any]],
    *,
    use_absolute_change: bool,
    window: int = 60,
    minimum_samples: int = 20,
) -> AnomalyResult:
    field = "change" if use_absolute_change else "change_pct"
    values: list[float] = []
    for row in history:
        metric = (row.get("metrics") or {}).get(key) or {}
        value = metric.get(field)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            values.append(float(value))
    values = values[-window:]
    if len(values) < minimum_samples:
        return AnomalyResult(None, None, len(values), "insufficient_history")

    mean = statistics.fmean(values)
    std = statistics.stdev(values)
    z_score = (current_move - mean) / std if std > 0 else None

    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations)
    robust_z = (current_move - median) / (1.4826 * mad) if mad > 0 else None

    standard_hit = z_score is not None and abs(z_score) >= 2.0
    robust_hit = robust_z is not None and abs(robust_z) >= 2.5
    if standard_hit and robust_hit:
        classification = "confirmed"
    elif robust_hit:
        classification = "robust_only"
    elif standard_hit:
        classification = "standard_only"
    else:
        classification = "normal"
    return AnomalyResult(z_score, robust_z, len(values), classification)
