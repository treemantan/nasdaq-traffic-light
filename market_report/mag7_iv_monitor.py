from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Callable

from .options_gamma import OptionContract, OptionsGammaConfig, fetch_yahoo_option_chain_near_dte


MAG7_CORE_TICKERS = (
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
)
FOCUS_IV_TICKERS = (
    "INTC",
    "AVGO",
    "MRVL",
    "NBIS",
    "BE",
)
DEFAULT_IV_TICKERS = MAG7_CORE_TICKERS + FOCUS_IV_TICKERS


@dataclass(frozen=True)
class Mag7IVConfig:
    enabled: bool = True
    tickers: tuple[str, ...] = DEFAULT_IV_TICKERS
    target_dte: int = 30
    max_days_to_expiry: int = 75
    lookback_days: int = 365
    rank_threshold: float = 10.0
    percentile_threshold: float = 20.0
    minimum_history_points: int = 20
    minimum_history_span_days: int = 20


@dataclass(frozen=True)
class Mag7IVAssessment:
    symbol: str
    spot_price: float | None
    expiry: str
    days_to_expiry: int | None
    atm_iv_pct: float | None
    iv_rank: float | None
    iv_percentile: float | None
    history_points: int
    history_span_days: int
    status: str
    interpretation: str
    source: str = "Yahoo/yfinance option chain"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Mag7IVMonitor:
    generated_at: str
    summary: str
    assessments: tuple[Mag7IVAssessment, ...] = ()
    warnings: tuple[str, ...] = ()


OptionChainFetcher = Callable[[str, OptionsGammaConfig], tuple[float | None, list[OptionContract], list[str]]]


def build_mag7_iv_monitor(
    config: Mag7IVConfig,
    history_path: Path,
    *,
    fetcher: OptionChainFetcher | None = None,
    as_of: date | None = None,
) -> Mag7IVMonitor:
    generated_at = datetime.now(timezone.utc).astimezone().isoformat()
    if not config.enabled:
        return Mag7IVMonitor(generated_at, "MAG7及关注标的 IV monitor disabled.")

    snapshot_date = as_of or datetime.now(timezone.utc).date()
    history = _load_history(history_path)
    fetch = fetcher or (
        lambda symbol, runtime: fetch_yahoo_option_chain_near_dte(
            symbol,
            runtime,
            target_dte=config.target_dte,
        )
    )
    assessments: list[Mag7IVAssessment] = []
    warnings: list[str] = []
    runtime_config = OptionsGammaConfig(
        benchmark_tickers=(),
        extra_tickers=(),
        data_source_priority=("yahoo",),
        expirations_to_include=1,
        max_days_to_expiry=max(config.target_dte + 15, config.max_days_to_expiry),
        include_single_names=True,
    )

    for raw_symbol in config.tickers:
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            continue
        try:
            spot, contracts, fetch_warnings = fetch(symbol, runtime_config)
            expiry, dte, atm_iv = _atm_target_iv(spot, contracts, snapshot_date, config.target_dte)
            if atm_iv is not None:
                _upsert_snapshot(history, symbol, snapshot_date, atm_iv, spot, expiry)
            assessments.append(
                _assess_symbol(
                    symbol,
                    spot,
                    expiry,
                    dte,
                    atm_iv,
                    history.get(symbol, []),
                    snapshot_date,
                    config,
                    tuple(fetch_warnings),
                )
            )
        except Exception as exc:  # pragma: no cover - live data degradation
            message = f"{symbol}: IV chain fetch failed: {exc}"
            warnings.append(message)
            assessments.append(
                Mag7IVAssessment(
                    symbol=symbol,
                    spot_price=None,
                    expiry="N/A",
                    days_to_expiry=None,
                    atm_iv_pct=None,
                    iv_rank=None,
                    iv_percentile=None,
                    history_points=len(history.get(symbol, [])),
                    history_span_days=_history_span(history.get(symbol, [])),
                    status="unavailable",
                    interpretation="当前期权链不可用，今日不生成低 IV 信号。",
                    warnings=(str(exc),),
                )
            )

    try:
        _save_history(history_path, history, snapshot_date, config.lookback_days)
    except Exception as exc:  # pragma: no cover - filesystem degradation
        warnings.append(f"MAG7及关注标的 IV history save failed: {exc}")

    low_count = sum(item.status == "low_iv_window" for item in assessments)
    building_count = sum(item.status == "building_history" for item in assessments)
    summary = (
        f"MAG7及关注标的约30D ATM IV：{low_count} 个同时满足 IV Rank < {config.rank_threshold:g} "
        f"和 IV Percentile <= {config.percentile_threshold:g}；{building_count} 个仍在积累历史。"
        "低 IV 只表示期权相对自身历史可能便宜，不自动决定买 Call 或 Put。"
    )
    return Mag7IVMonitor(generated_at, summary, tuple(assessments), tuple(warnings))


def _atm_target_iv(
    spot: float | None,
    contracts: list[OptionContract],
    as_of: date,
    target_dte: int,
) -> tuple[str, int | None, float | None]:
    if spot is None or spot <= 0:
        return "N/A", None, None
    usable = [
        item
        for item in contracts
        if item.expiry >= as_of
        and item.implied_volatility is not None
        and math.isfinite(item.implied_volatility)
        and item.implied_volatility > 0
        and item.strike > 0
    ]
    if not usable:
        return "N/A", None, None
    expiry = min({item.expiry for item in usable}, key=lambda value: abs((value - as_of).days - target_dte))
    at_expiry = [item for item in usable if item.expiry == expiry]
    leg_ivs: list[float] = []
    for option_type in ("call", "put"):
        legs = [item for item in at_expiry if item.option_type.lower() == option_type]
        if legs:
            nearest = min(legs, key=lambda item: abs(item.strike - spot))
            if nearest.implied_volatility is not None:
                leg_ivs.append(nearest.implied_volatility)
    if not leg_ivs:
        nearest = min(at_expiry, key=lambda item: abs(item.strike - spot))
        leg_ivs.append(float(nearest.implied_volatility))
    return expiry.isoformat(), (expiry - as_of).days, median(leg_ivs)


def _assess_symbol(
    symbol: str,
    spot: float | None,
    expiry: str,
    dte: int | None,
    atm_iv: float | None,
    raw_history: list[dict],
    as_of: date,
    config: Mag7IVConfig,
    fetch_warnings: tuple[str, ...],
) -> Mag7IVAssessment:
    cutoff = as_of - timedelta(days=config.lookback_days)
    observations = [
        (parsed, float(item["atm_iv"]))
        for item in raw_history
        for parsed in [_parse_date(item.get("date"))]
        if parsed is not None and cutoff <= parsed <= as_of and _valid_number(item.get("atm_iv"))
    ]
    observations.sort(key=lambda item: item[0])
    values = [value for _, value in observations]
    points = len(values)
    span = (observations[-1][0] - observations[0][0]).days if len(observations) >= 2 else 0

    rank = _iv_rank(atm_iv, values)
    percentile = _iv_percentile(atm_iv, values)
    sufficient = points >= config.minimum_history_points and span >= config.minimum_history_span_days
    if atm_iv is None:
        status = "unavailable"
        interpretation = "未取得可用的约30D ATM IV，今日不生成信号。"
    elif not sufficient:
        status = "building_history"
        interpretation = (
            f"历史积累中（{points} 个观测、跨度 {span} 天）；达到至少 "
            f"{config.minimum_history_points} 个观测且跨度 {config.minimum_history_span_days} 天后才启用信号。"
        )
        rank = None
        percentile = None
    elif rank is not None and percentile is not None and rank < config.rank_threshold and percentile <= config.percentile_threshold:
        status = "low_iv_window"
        interpretation = (
            "低 IV 买方研究窗口：先检查财报/产品发布等事件，再由价格趋势和投资观点决定 Call、Put 或暂不交易。"
        )
    else:
        status = "normal"
        interpretation = "当前未同时进入低 IV Rank 与低 IV Percentile 区间，保持观察。"

    return Mag7IVAssessment(
        symbol=symbol,
        spot_price=spot,
        expiry=expiry,
        days_to_expiry=dte,
        atm_iv_pct=atm_iv * 100 if atm_iv is not None else None,
        iv_rank=rank,
        iv_percentile=percentile,
        history_points=points,
        history_span_days=span,
        status=status,
        interpretation=interpretation,
        warnings=fetch_warnings,
    )


def _iv_rank(current: float | None, values: list[float]) -> float | None:
    if current is None or not values:
        return None
    low, high = min(values), max(values)
    if high <= low:
        return 0.0
    if math.isclose(current, low, rel_tol=0.0, abs_tol=1e-10):
        return 0.0
    if math.isclose(current, high, rel_tol=0.0, abs_tol=1e-10):
        return 100.0
    return round(max(0.0, min(100.0, (current - low) / (high - low) * 100.0)), 4)


def _iv_percentile(current: float | None, values: list[float]) -> float | None:
    if current is None or not values:
        return None
    prior = [value for value in values[:-1]] if len(values) > 1 else values
    if not prior:
        prior = values
    return sum(value < current for value in prior) / len(prior) * 100.0


def _load_history(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshots = payload.get("snapshots", {}) if isinstance(payload, dict) else {}
        return {
            str(symbol).upper(): [item for item in items if isinstance(item, dict)]
            for symbol, items in snapshots.items()
            if isinstance(items, list)
        }
    except (OSError, ValueError, TypeError):
        return {}


def _upsert_snapshot(
    history: dict[str, list[dict]],
    symbol: str,
    snapshot_date: date,
    atm_iv: float,
    spot: float | None,
    expiry: str,
) -> None:
    rows = [item for item in history.get(symbol, []) if str(item.get("date")) != snapshot_date.isoformat()]
    rows.append(
        {
            "date": snapshot_date.isoformat(),
            "atm_iv": round(atm_iv, 8),
            "spot": spot,
            "expiry": expiry,
            "source": "Yahoo/yfinance option chain",
        }
    )
    history[symbol] = rows


def _save_history(path: Path, history: dict[str, list[dict]], as_of: date, lookback_days: int) -> None:
    cutoff = as_of - timedelta(days=max(lookback_days + 30, 395))
    trimmed: dict[str, list[dict]] = {}
    for symbol, rows in history.items():
        kept = [item for item in rows if (_parse_date(item.get("date")) or date.min) >= cutoff]
        kept.sort(key=lambda item: str(item.get("date") or ""))
        trimmed[symbol] = kept
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"version": 1, "snapshots": trimmed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _history_span(rows: list[dict]) -> int:
    dates = sorted(parsed for item in rows for parsed in [_parse_date(item.get("date"))] if parsed is not None)
    return (dates[-1] - dates[0]).days if len(dates) >= 2 else 0


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _valid_number(value: object) -> bool:
    try:
        parsed = float(value)
        return math.isfinite(parsed) and parsed > 0
    except (TypeError, ValueError):
        return False
