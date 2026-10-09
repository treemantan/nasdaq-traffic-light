from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .technical_indicators import PriceBar


PRICE_HISTORY_CACHE = Path("output") / "cache" / "price_history.json"
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
}


@dataclass(frozen=True)
class InstrumentIdentity:
    requested_symbol: str
    resolved_symbol: str
    name: str
    exchange: str
    currency: str
    instrument_type: str


@dataclass(frozen=True)
class PriceHistory:
    identity: InstrumentIdentity
    bars: tuple[PriceBar, ...]
    interval: str
    source: str
    observation_at: datetime | None
    fetched_at: datetime
    quality: str
    market_state: str = ""
    warnings: tuple[str, ...] = ()
    volume_progress: float | None = None


def fetch_price_history(
    symbol: str,
    *,
    period: str = "2y",
    interval: str = "1d",
    timeout: int = 15,
    attempts: int = 3,
    cache_path: Path = PRICE_HISTORY_CACHE,
    opener: Callable[..., Any] | None = None,
) -> PriceHistory:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("Ticker cannot be empty.")
    encoded = urllib.parse.quote(normalized, safe="")
    errors: list[str] = []
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{encoded}?range={period}&interval={interval}&events=div%2Csplits"
        for attempt in range(attempts):
            try:
                payload = _read_json(url, timeout, opener)
                history = parse_yahoo_chart(normalized, payload, interval)
                _save_cached_history(cache_path, normalized, period, interval, history)
                return history
            except Exception as exc:
                errors.append(f"{host} attempt {attempt + 1}: {type(exc).__name__}: {exc}")
                if attempt + 1 < attempts:
                    time.sleep(min(2 ** attempt, 4))
    if "." not in normalized:
        for fallback in (_fetch_alpha_vantage_history, _fetch_finnhub_history):
            try:
                history = fallback(normalized, timeout=timeout, opener=opener)
                if history is not None:
                    _save_cached_history(cache_path, normalized, period, interval, history)
                    return history
            except Exception as exc:
                errors.append(f"{fallback.__name__}: {type(exc).__name__}: {exc}")
    cached = _load_cached_history(cache_path, normalized, period, interval)
    if cached is not None:
        return PriceHistory(
            identity=cached.identity,
            bars=cached.bars,
            interval=cached.interval,
            source=cached.source,
            observation_at=cached.observation_at,
            fetched_at=cached.fetched_at,
            quality="cache",
            market_state=cached.market_state,
            warnings=(f"{normalized} 实时行情获取失败，使用本地缓存。",),
        )
    raise RuntimeError("; ".join(errors))


def _fetch_alpha_vantage_history(
    symbol: str,
    *,
    timeout: int,
    opener: Callable[..., Any] | None,
) -> PriceHistory | None:
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        return None
    query = urllib.parse.urlencode(
        {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "full",
            "apikey": api_key,
        }
    )
    payload = _read_json(f"https://www.alphavantage.co/query?{query}", timeout, opener)
    series = payload.get("Time Series (Daily)") or {}
    if not series:
        raise ValueError(str(payload.get("Note") or payload.get("Information") or "No daily series"))
    bars = tuple(
        PriceBar(
            timestamp=datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
            open=float(values["1. open"]),
            high=float(values["2. high"]),
            low=float(values["3. low"]),
            close=float(values["4. close"]),
            volume=float(values["5. volume"]),
        )
        for day, values in sorted(series.items())
    )
    meta = payload.get("Meta Data") or {}
    resolved = str(meta.get("2. Symbol") or symbol).upper()
    if resolved != symbol:
        raise ValueError(f"Alpha Vantage resolved {resolved}, expected {symbol}")
    return PriceHistory(
        identity=InstrumentIdentity(symbol, resolved, symbol, "", "USD", "EQUITY"),
        bars=bars,
        interval="1d",
        source="Alpha Vantage fallback",
        observation_at=bars[-1].timestamp,
        fetched_at=datetime.now(timezone.utc),
        quality="fallback/daily",
        warnings=("Yahoo daily OHLCV unavailable; using Alpha Vantage fallback.",),
    )


def _fetch_finnhub_history(
    symbol: str,
    *,
    timeout: int,
    opener: Callable[..., Any] | None,
) -> PriceHistory | None:
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        return None
    now = int(datetime.now(timezone.utc).timestamp())
    start = now - 3 * 366 * 24 * 60 * 60
    query = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "resolution": "D",
            "from": start,
            "to": now,
            "token": api_key,
        }
    )
    payload = _read_json(f"https://finnhub.io/api/v1/stock/candle?{query}", timeout, opener)
    if payload.get("s") != "ok":
        raise ValueError(str(payload.get("error") or payload.get("s") or "No daily candles"))
    bars = tuple(
        PriceBar(
            timestamp=datetime.fromtimestamp(int(timestamp), timezone.utc),
            open=float(open_value),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=float(volume),
        )
        for timestamp, open_value, high, low, close, volume in zip(
            payload.get("t") or [],
            payload.get("o") or [],
            payload.get("h") or [],
            payload.get("l") or [],
            payload.get("c") or [],
            payload.get("v") or [],
        )
    )
    if not bars:
        raise ValueError("Finnhub returned no daily candles.")
    return PriceHistory(
        identity=InstrumentIdentity(symbol, symbol, symbol, "", "USD", "EQUITY"),
        bars=bars,
        interval="1d",
        source="Finnhub fallback",
        observation_at=bars[-1].timestamp,
        fetched_at=datetime.now(timezone.utc),
        quality="fallback/daily",
        warnings=("Yahoo and Alpha Vantage daily OHLCV unavailable; using Finnhub fallback.",),
    )


def parse_yahoo_chart(
    requested_symbol: str, payload: dict[str, Any], interval: str, *, fetched_at: datetime | None = None
) -> PriceHistory:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ValueError(str(chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise ValueError("Yahoo chart returned no result.")
    result = results[0]
    meta = result.get("meta") or {}
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    timestamps = result.get("timestamp") or []
    fetched_at = fetched_at or datetime.now(timezone.utc)
    scale = 0.01 if meta.get("currency") == "GBp" else 1.0
    currency = "GBP" if str(meta.get("currency") or "") == "GBp" else str(meta.get("currency") or "")
    bars: list[PriceBar] = []
    used_regular_close = False
    used_intraday_quote = False
    latest_close_missing = False
    for index, timestamp in enumerate(timestamps):
        values = {
            key: _at(quote.get(key) or [], index)
            for key in ("open", "high", "low", "close", "volume")
        }
        if index == len(timestamps) - 1 and values["close"] is None:
            session_close = _completed_regular_close(meta, int(timestamp), values, fetched_at, interval)
            intraday_close = _current_regular_quote(meta, int(timestamp), values, fetched_at, interval)
            if session_close is not None:
                values["close"] = session_close
                used_regular_close = True
            elif intraday_close is not None:
                values["close"] = intraday_close
                used_intraday_quote = True
            else:
                latest_close_missing = True
        if any(values[key] is None for key in ("open", "high", "low", "close")):
            continue
        bars.append(
            PriceBar(
                timestamp=datetime.fromtimestamp(int(timestamp), timezone.utc),
                open=float(values["open"]) * scale,
                high=float(values["high"]) * scale,
                low=float(values["low"]) * scale,
                close=float(values["close"]) * scale,
                volume=float(values["volume"]) if values["volume"] is not None else None,
            )
        )
    if not bars:
        raise ValueError("Yahoo chart returned no valid OHLC bars.")
    identity = InstrumentIdentity(
        requested_symbol=requested_symbol,
        resolved_symbol=str(meta.get("symbol") or requested_symbol).upper(),
        name=str(meta.get("longName") or meta.get("shortName") or requested_symbol),
        exchange=str(meta.get("fullExchangeName") or meta.get("exchangeName") or ""),
        currency=currency,
        instrument_type=str(meta.get("instrumentType") or meta.get("quoteType") or ""),
    )
    stale_after_close = _completed_session_newer_than_last_bar(meta, bars[-1].timestamp, fetched_at)
    intraday_bar = interval == "1d" and _regular_session_active(meta, int(bars[-1].timestamp.timestamp()), fetched_at)
    current_session_missing = interval == "1d" and _active_session_newer_than_last_bar(
        meta, bars[-1].timestamp, fetched_at
    )
    prior_close = interval == "1d" and not used_regular_close and (
        stale_after_close or current_session_missing
        or (latest_close_missing and _session_started_or_unknown(meta, fetched_at))
    )
    quote_time = _regular_quote_time(meta, int(bars[-1].timestamp.timestamp())) if intraday_bar else None
    fresh_intraday = (
        quote_time is not None and 0 <= fetched_at.timestamp() - quote_time <= 30 * 60
    )
    quality = (
        "daily/regular-close-fallback" if used_regular_close
        else "daily/intraday" if used_intraday_quote or (intraday_bar and fresh_intraday)
        else "daily/intraday-stale" if intraday_bar
        else "daily/prior-close" if prior_close
        else "daily/delayed"
    )
    observation_at = bars[-1].timestamp
    if intraday_bar and quote_time is not None:
        observation_at = datetime.fromtimestamp(quote_time, timezone.utc)
    elif used_regular_close:
        closing_quote_time = _regular_quote_time(meta, int(bars[-1].timestamp.timestamp()))
        if closing_quote_time is not None:
            observation_at = datetime.fromtimestamp(closing_quote_time, timezone.utc)
    elif quality == "daily/delayed" and _regular_session_closed(
        meta, int(bars[-1].timestamp.timestamp()), fetched_at
    ):
        regular_end = int(meta["currentTradingPeriod"]["regular"]["end"])
        observation_at = datetime.fromtimestamp(regular_end, timezone.utc)
    volume_progress = _regular_session_progress(meta, quote_time) if quality == "daily/intraday" else None
    return PriceHistory(
        identity=identity,
        bars=tuple(bars),
        interval=interval,
        source="Yahoo",
        observation_at=observation_at,
        fetched_at=fetched_at,
        quality=quality,
        market_state=str(meta.get("marketState") or ""),
        volume_progress=volume_progress,
        warnings=(
            ("Yahoo 当日日线 close 缺失；已用同一交易日的常规时段收盘报价补齐，待正式日线核对。",)
            if used_regular_close else
            ("盘中动态 K 线：当日收盘价尚未确认；成交量仅按时间线性投影，未校正开盘/尾盘U型分布，不用于放量突破确认。",)
            if quality == "daily/intraday" else
            ("盘中 K 线报价时间缺失或超过30分钟未更新；仅作参考，不生成当日加仓信号。",)
            if quality == "daily/intraday-stale" else
            (f"当日动态 K 线缺失或尚未完成；仅用 {bars[-1].timestamp.date()} 的历史日线作参考，不生成当日加仓信号。",)
            if prior_close else ()
        ),
    )


def _regular_session_closed(meta: dict[str, Any], timestamp: int, fetched_at: datetime) -> bool:
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    try:
        start = int(regular["start"])
        end = int(regular["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return start <= timestamp <= end <= fetched_at.timestamp() - 5 * 60


def _regular_session_active(meta: dict[str, Any], timestamp: int, fetched_at: datetime) -> bool:
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    try:
        start = int(regular["start"])
        end = int(regular["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return start <= timestamp <= end and start <= fetched_at.timestamp() < end + 5 * 60


def _session_started_or_unknown(meta: dict[str, Any], fetched_at: datetime) -> bool:
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    try:
        return fetched_at.timestamp() >= int(regular["start"])
    except (KeyError, TypeError, ValueError):
        return True


def _active_session_newer_than_last_bar(
    meta: dict[str, Any], last_bar_at: datetime, fetched_at: datetime
) -> bool:
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    try:
        start = int(regular["start"])
        end = int(regular["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return last_bar_at.timestamp() < start <= fetched_at.timestamp() < end + 5 * 60


def _regular_quote_time(meta: dict[str, Any], timestamp: int) -> int | None:
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    try:
        start = int(regular["start"])
        end = int(regular["end"])
        quote_time = int(meta["regularMarketTime"])
    except (KeyError, TypeError, ValueError):
        return None
    return quote_time if start <= timestamp <= end and start <= quote_time <= end + 10 * 60 else None


def _regular_session_progress(meta: dict[str, Any], quote_time: int | None) -> float | None:
    if quote_time is None:
        return None
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    try:
        start = int(regular["start"])
        end = int(regular["end"])
    except (KeyError, TypeError, ValueError):
        return None
    return min(1.0, max(0.0, (quote_time - start) / (end - start))) if end > start else None


def _current_regular_quote(
    meta: dict[str, Any], timestamp: int, values: dict[str, Any], fetched_at: datetime, interval: str
) -> float | None:
    """Use a fresh same-session quote as the still-changing daily candle close."""
    if interval != "1d" or not _regular_session_active(meta, timestamp, fetched_at):
        return None
    if any(values[key] is None for key in ("open", "high", "low")):
        return None
    quote_time = _regular_quote_time(meta, timestamp)
    if quote_time is None or not 0 <= fetched_at.timestamp() - quote_time <= 30 * 60:
        return None
    try:
        quote_price = float(meta["regularMarketPrice"])
        low = float(values["low"])
        high = float(values["high"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (quote_price, low, high)):
        return None
    return quote_price if 0 < low <= quote_price <= high else None


def _completed_session_newer_than_last_bar(
    meta: dict[str, Any], last_bar_at: datetime, fetched_at: datetime
) -> bool:
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    try:
        start = int(regular["start"])
        end = int(regular["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return last_bar_at.timestamp() < start and end <= fetched_at.timestamp() - 5 * 60


def _completed_regular_close(
    meta: dict[str, Any], timestamp: int, values: dict[str, Any], fetched_at: datetime, interval: str
) -> float | None:
    """Fill a null daily close only from the same completed regular session."""
    if interval != "1d" or any(values[key] is None for key in ("open", "high", "low")):
        return None
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    try:
        end = int(regular["end"])
        quote_time = int(meta["regularMarketTime"])
        quote_price = float(meta["regularMarketPrice"])
        low = float(values["low"])
        high = float(values["high"])
    except (KeyError, TypeError, ValueError):
        return None
    if not _regular_session_closed(meta, timestamp, fetched_at):
        return None
    if not (end - 2 * 60 <= quote_time <= end + 10 * 60):
        return None
    if not all(math.isfinite(value) for value in (quote_price, low, high)):
        return None
    if not (low - 1e-6 <= quote_price <= high + 1e-6):
        return None
    return quote_price


def _read_json(url: str, timeout: int, opener: Callable[..., Any] | None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=YAHOO_HEADERS)
    open_fn = opener or urllib.request.urlopen
    with open_fn(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _at(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def _cache_key(symbol: str, period: str, interval: str) -> str:
    return f"{symbol}|{period}|{interval}"


def _save_cached_history(path: Path, symbol: str, period: str, interval: str, history: PriceHistory) -> None:
    payload = _load_cache_payload(path)
    payload[_cache_key(symbol, period, interval)] = {
        "identity": asdict(history.identity),
        "bars": [
            {
                **asdict(bar),
                "timestamp": bar.timestamp.isoformat(),
            }
            for bar in history.bars
        ],
        "interval": history.interval,
        "source": history.source,
        "observation_at": history.observation_at.isoformat() if history.observation_at else None,
        "fetched_at": history.fetched_at.isoformat(),
        "market_state": history.market_state,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _load_cached_history(path: Path, symbol: str, period: str, interval: str) -> PriceHistory | None:
    item = _load_cache_payload(path).get(_cache_key(symbol, period, interval))
    if not isinstance(item, dict):
        return None
    try:
        return PriceHistory(
            identity=InstrumentIdentity(**item["identity"]),
            bars=tuple(
                PriceBar(
                    timestamp=datetime.fromisoformat(bar["timestamp"]),
                    open=float(bar["open"]),
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    volume=float(bar["volume"]) if bar.get("volume") is not None else None,
                )
                for bar in item["bars"]
            ),
            interval=str(item["interval"]),
            source=str(item["source"]),
            observation_at=datetime.fromisoformat(item["observation_at"]) if item.get("observation_at") else None,
            fetched_at=datetime.fromisoformat(item["fetched_at"]),
            quality="cache",
            market_state=str(item.get("market_state") or ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _load_cache_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
