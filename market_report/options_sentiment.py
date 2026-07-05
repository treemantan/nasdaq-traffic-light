from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .data_sources import DEFAULT_HTTP_HEADERS


@dataclass(frozen=True)
class OptionsSentimentConfig:
    enabled: bool = True
    benchmark_tickers: tuple[str, ...] = ("SPY", "QQQ")
    tickers: tuple[str, ...] = ()
    alpha_vantage_api_key_env: str = "ALPHA_VANTAGE_API_KEY"
    include_holdings: bool = True
    max_tickers: int = 12


@dataclass(frozen=True)
class ExpirationRatio:
    expiration: str
    put_call_ratio: float | None


@dataclass(frozen=True)
class TickerShortPremiumContext:
    symbol: str
    origin: str
    put_call_ratio: float | None
    nearest_expiry: str
    nearest_expiry_put_call_ratio: float | None
    bias: str
    interpretation: str
    expiration_ratios: list[ExpirationRatio] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OptionsSentimentMonitor:
    generated_at: str
    summary: str
    contexts: list[TickerShortPremiumContext] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


OptionsSentimentFetcher = Callable[[str, str, OptionsSentimentConfig], Optional[TickerShortPremiumContext]]


def build_options_sentiment_monitor(
    config: OptionsSentimentConfig,
    etf_monitor: Any,
    fetcher: OptionsSentimentFetcher | None = None,
) -> OptionsSentimentMonitor:
    generated_at = datetime.now(timezone.utc).astimezone().isoformat()
    if not config.enabled:
        return OptionsSentimentMonitor(generated_at=generated_at, summary="Options sentiment monitor disabled.")

    universe = _resolve_sentiment_universe(config, etf_monitor)
    fetch = fetcher or fetch_alpha_vantage_sentiment
    contexts: list[TickerShortPremiumContext] = []
    warnings: list[str] = []

    if fetcher is None and not _alpha_vantage_api_key(config):
        return OptionsSentimentMonitor(
            generated_at=generated_at,
            summary=(
                f"Short premium context targets {len(universe)} tickers, but Alpha Vantage ratio data is unavailable "
                f"because {config.alpha_vantage_api_key_env} is not configured."
            ),
            contexts=[],
            warnings=[f"{config.alpha_vantage_api_key_env} is not configured; skipping Alpha Vantage ratio endpoints."],
        )

    for symbol, origin in universe:
        try:
            context = fetch(symbol, origin, config)
            if context is not None:
                contexts.append(context)
        except Exception as exc:  # pragma: no cover - live data degradation
            warnings.append(f"{symbol}: options sentiment fetch failed: {exc}")

    available = sum(1 for item in contexts if item.put_call_ratio is not None)
    summary = (
        f"Short premium context checked {len(universe)} tickers; {available} returned Alpha Vantage put-call ratios. "
        "Use this as ticker-level context for cash-secured puts, vertical spreads, and iron condors, not as trade advice."
    )
    return OptionsSentimentMonitor(generated_at=generated_at, summary=summary, contexts=contexts, warnings=warnings)


def fetch_alpha_vantage_sentiment(
    symbol: str,
    origin: str,
    config: OptionsSentimentConfig,
) -> TickerShortPremiumContext:
    api_key = _alpha_vantage_api_key(config)
    if not api_key:
        raise RuntimeError(f"{config.alpha_vantage_api_key_env} is not configured")

    query = urllib.parse.urlencode(
        {
            "function": "REALTIME_PUT_CALL_RATIO",
            "symbol": symbol,
            "apikey": api_key,
        }
    )
    payload = _read_json(f"https://www.alphavantage.co/query?{query}")
    _raise_alpha_vantage_error(payload)

    full_ratio = _to_float(
        payload.get("put_call_ratio_full_chain")
        or payload.get("putCallRatioFullChain")
        or payload.get("full_chain")
    )
    expiration_ratios = _expiration_ratios(payload.get("put_call_ratio_by_expiration") or [])
    nearest = expiration_ratios[0] if expiration_ratios else None
    nearest_expiry = nearest.expiration if nearest else "N/A"
    nearest_ratio = nearest.put_call_ratio if nearest else None
    bias, interpretation = _classify_short_premium_bias(full_ratio, nearest_ratio)

    return TickerShortPremiumContext(
        symbol=symbol.upper(),
        origin=origin,
        put_call_ratio=full_ratio,
        nearest_expiry=nearest_expiry,
        nearest_expiry_put_call_ratio=nearest_ratio,
        bias=bias,
        interpretation=interpretation,
        expiration_ratios=expiration_ratios,
        warnings=[],
    )


def _resolve_sentiment_universe(config: OptionsSentimentConfig, etf_monitor: Any) -> list[tuple[str, str]]:
    ordered: list[tuple[str, str]] = []

    def add(symbol: object, origin: str) -> None:
        text = str(symbol or "").strip().upper()
        if not text or text.endswith(".L"):
            return
        if any(existing == text for existing, _ in ordered):
            return
        if len(ordered) >= max(1, int(config.max_tickers)):
            return
        ordered.append((text, origin))

    for symbol in config.benchmark_tickers:
        add(symbol, "benchmark")
    if config.include_holdings:
        for position in getattr(etf_monitor, "portfolio_positions", []) or []:
            add(getattr(position, "symbol", ""), "holding")
    for symbol in config.tickers:
        add(symbol, "watchlist")
    return ordered


def _expiration_ratios(raw_items: object) -> list[ExpirationRatio]:
    if not isinstance(raw_items, list):
        return []
    ratios: list[ExpirationRatio] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        expiration = str(item.get("date") or item.get("expiration") or "").strip()
        if not expiration:
            continue
        ratios.append(ExpirationRatio(expiration=expiration, put_call_ratio=_to_float(item.get("value"))))
    return ratios


def _classify_short_premium_bias(
    full_ratio: float | None,
    nearest_ratio: float | None,
) -> tuple[str, str]:
    ratio = nearest_ratio if nearest_ratio is not None else full_ratio
    if ratio is None:
        return "Data unavailable", "Alpha Vantage did not return a usable put-call ratio for this ticker."
    if ratio >= 1.35:
        return (
            "Put-side premium rich / downside stress",
            "Put demand is elevated. Cash-secured puts or bull put spreads may offer richer premium, but require wider margin of safety and assignment-risk discipline.",
        )
    if ratio <= 0.65:
        return (
            "Call-side pressure / upside squeeze risk",
            "Call demand dominates. Bear call spreads may carry richer call-side premium, but upside squeeze risk should be controlled before selling calls.",
        )
    if 0.85 <= ratio <= 1.15:
        return (
            "Two-sided neutral premium possible",
            "Put-call demand is balanced enough to treat iron condors or other range-premium structures as candidates, subject to price trend and event risk.",
        )
    if ratio > 1.15:
        return (
            "Mild put-side premium bias",
            "Put demand is above neutral but not extreme. Put-side premium can be considered with defined downside levels.",
        )
    return (
        "Mild call-side premium bias",
        "Call demand is above neutral but not extreme. Call-side spreads need confirmation that price momentum is not accelerating upward.",
    )


def _alpha_vantage_api_key(config: OptionsSentimentConfig) -> str | None:
    preferred = str(config.alpha_vantage_api_key_env or "ALPHA_VANTAGE_API_KEY").strip()
    candidates = [preferred, "ALPHA_VANTAGE_API_KEY", "ALPHAVANTAGE_API_KEY"]
    for name in dict.fromkeys(candidates):
        value = os.environ.get(name)
        if value:
            return value.strip()
    return None


def _read_json(url: str, timeout: int = 15) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=DEFAULT_HTTP_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _raise_alpha_vantage_error(payload: dict[str, Any]) -> None:
    for key in ("Error Message", "Note", "Information"):
        message = payload.get(key)
        if message:
            raise RuntimeError(str(message))


def _to_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(str(value).replace(",", "").strip())
        return parsed
    except (TypeError, ValueError):
        return None
