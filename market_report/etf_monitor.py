from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ETF_CACHE_PATH = Path("output") / "cache" / "etf_monitor_cache.json"
ETF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
}


@dataclass(frozen=True)
class ETFSpec:
    key: str
    label: str
    symbol: str
    theme: str
    provider: str
    currency: str = "GBP"
    equity_like: bool = True


@dataclass(frozen=True)
class ETFAssetMonitor:
    key: str
    label: str
    symbol: str
    theme: str
    provider: str
    currency: str
    value: float | None
    previous_value: float | None
    as_of: date | None
    fetched_at: datetime
    change_pct: float | None = None
    daily_sigma: float | None = None
    daily_volatility: float | None = None
    trend_volatility: float | None = None
    momentum_5d: float | None = None
    momentum_1m: float | None = None
    momentum_3m: float | None = None
    sma13: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    distance_sma200: float | None = None
    trend_sigma_200d: float | None = None
    rsi14: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    pb: float | None = None
    valuation_source: str = "unavailable"
    pe_percentile: float | None = None
    pb_percentile: float | None = None
    pe_high_1y: float | None = None
    pe_high_1y_ratio: float | None = None
    trend_label: str = "趋势待确认"
    momentum_label: str = "动量待确认"
    valuation_label: str = "估值数据不足"
    crowding_label: str = "拥挤度待确认"
    sigma_label: str = "日波动待确认"
    trend_stretch_label: str = "趋势拉伸待确认"
    crowding_score: int = 50
    entry_score: int = 50
    entry_label: str = "新增仓位环境待确认"
    entry_note: str = "历史样本不足，暂不评估新增仓位环境。"
    risk_management_note: str = "仅作环境评估，不构成买卖建议。"
    source: str = "Yahoo"
    status: str = "ok"
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ETFMonitor:
    summary: str
    assets: list[ETFAssetMonitor]
    warnings: list[str]


DEFAULT_ETF_SPECS = [
    ETFSpec("vwrl", "Vanguard FTSE All-World UCITS ETF", "VWRL.L", "Global Equity", "Vanguard"),
    ETFSpec("vuag", "Vanguard S&P 500 UCITS ETF", "VUAG.L", "S&P 500", "Vanguard"),
    ETFSpec("cnx1", "iShares Nasdaq 100 UCITS ETF", "CNX1.L", "Nasdaq 100", "iShares"),
    ETFSpec("iitu", "iShares S&P 500 Information Technology Sector ETF", "IITU.L", "US Technology", "iShares"),
    ETFSpec("ainf", "iShares AI Infrastructure UCITS ETF", "AINF.L", "AI Infrastructure", "iShares"),
    ETFSpec("wtai", "WisdomTree Artificial Intelligence ETF", "WTAI.L", "Artificial Intelligence", "WisdomTree"),
    ETFSpec("aiai", "L&G Artificial Intelligence UCITS ETF", "AIAI.L", "Artificial Intelligence", "L&G"),
    ETFSpec("semi", "iShares Global Semiconductors ETF", "SEMI.L", "Semiconductor", "iShares"),
    ETFSpec("rbot", "iShares Automation & Robotics UCITS ETF", "RBOT.L", "Robotics & Automation", "iShares"),
    ETFSpec("wcld", "WisdomTree Cloud Computing UCITS ETF", "WCLD.L", "Cloud Software", "WisdomTree"),
    ETFSpec("lock", "iShares Digital Security UCITS ETF", "LOCK.L", "Cybersecurity", "iShares"),
    ETFSpec("qwtm", "WisdomTree Quantum Computing ETF", "QWTM.L", "Quantum Computing", "WisdomTree"),
    ETFSpec("qntm", "VanEck Quantum Computing ETF", "QNTM.L", "Quantum Computing", "VanEck"),
    ETFSpec("qant", "iShares Quantum Computing ETF", "QANT.L", "Quantum Computing", "iShares"),
    ETFSpec("nato", "HANetf Future of Defence UCITS ETF", "NATO.L", "Defence", "HANetf"),
    ETFSpec("sgln", "iShares Physical Gold ETC", "SGLN.L", "Gold", "iShares", equity_like=False),
]


VALUATION_PROXY_SYMBOLS = {
    "VWRL.L": ("VT", "StockAnalysis proxy: VT"),
    "VUAG.L": ("VOO", "StockAnalysis proxy: VOO"),
    "IITU.L": ("XLK", "StockAnalysis proxy: XLK"),
    "QWTM.L": ("QTUM", "StockAnalysis proxy: QTUM"),
    "NATO.L": ("ITA", "StockAnalysis proxy: ITA"),
}


def fetch_etf_monitor(specs: list[ETFSpec] | None = None, macro_metrics: dict[str, Any] | None = None) -> ETFMonitor:
    fetched_at = datetime.now(timezone.utc)
    cache = _load_cache()
    assets: list[ETFAssetMonitor] = []
    warnings: list[str] = []
    for spec in specs or DEFAULT_ETF_SPECS:
        try:
            asset = _fetch_etf_asset(spec, fetched_at, cache, macro_metrics)
        except Exception as exc:
            asset = _cached_or_failed(spec, fetched_at, cache, f"{type(exc).__name__}: {exc}", macro_metrics)
        assets.append(asset)
        warnings.extend(asset.warnings)
    _save_cache(cache)
    return ETFMonitor(summary=_build_summary(assets), assets=assets, warnings=list(dict.fromkeys(warnings)))


def _fetch_etf_asset(
    spec: ETFSpec,
    fetched_at: datetime,
    cache: dict[str, Any],
    macro_metrics: dict[str, Any] | None = None,
) -> ETFAssetMonitor:
    history = _fetch_yahoo_history(spec.symbol)
    if len(history) < 2:
        raise ValueError(f"{spec.symbol} returned insufficient price history")
    history = sorted(history, key=lambda item: item[0])
    closes = [close for _, close in history]
    daily_returns = _daily_returns(closes)
    value = closes[-1]
    previous = closes[-2]
    one_day_change = _pct_change(value, previous)
    daily_volatility = _rolling_std(daily_returns, 252)
    trend_volatility = _robust_trend_volatility(daily_returns)
    daily_sigma = _sigma_move(one_day_change, daily_volatility)
    valuation_fetch_warning: str | None = None
    try:
        valuations = _fetch_yahoo_valuation(spec.symbol) if spec.equity_like else {}
    except Exception as exc:
        valuations = {}
        valuation_fetch_warning = f"Yahoo估值接口暂不可用：{type(exc).__name__}"
    valuation_source = "Yahoo" if _has_any_valuation(valuations) else "unavailable"
    if spec.equity_like and not _has_any_valuation(valuations):
        try:
            valuations = _fetch_stockanalysis_valuation(spec.symbol)
            valuation_source = "StockAnalysis" if _has_any_valuation(valuations) else "unavailable"
        except Exception as exc:
            fallback_warning = f"StockAnalysis PE fallback failed: {type(exc).__name__}"
            valuation_fetch_warning = (
                f"{valuation_fetch_warning}; {fallback_warning}"
                if valuation_fetch_warning
                else fallback_warning
            )
    if spec.equity_like and not _has_any_valuation(valuations) and spec.symbol.upper() in VALUATION_PROXY_SYMBOLS:
        proxy_symbol, proxy_source = VALUATION_PROXY_SYMBOLS[spec.symbol.upper()]
        try:
            valuations = _fetch_stockanalysis_proxy_valuation(proxy_symbol)
            valuation_source = proxy_source if _has_any_valuation(valuations) else "unavailable"
        except Exception as exc:
            fallback_warning = f"{proxy_source} PE fallback failed: {type(exc).__name__}"
            valuation_fetch_warning = (
                f"{valuation_fetch_warning}; {fallback_warning}"
                if valuation_fetch_warning
                else fallback_warning
            )
    pe = _safe_float(valuations.get("trailingPE"))
    forward_pe = _safe_float(valuations.get("forwardPE"))
    pb = _safe_float(valuations.get("priceToBook"))
    if pe is None and forward_pe is None and pb is None:
        valuation_source = "unavailable"
    pe_percentile, pb_percentile, pe_high_1y, pe_high_1y_ratio = _update_valuation_history(
        cache, spec.key, fetched_at.date(), pe, pb
    )
    warnings = _valuation_warnings(spec, pe, forward_pe, pb, pe_percentile, pe_high_1y_ratio)
    if valuation_fetch_warning:
        warnings.append(valuation_fetch_warning)
    asset = ETFAssetMonitor(
        key=spec.key,
        label=spec.label,
        symbol=spec.symbol,
        theme=spec.theme,
        provider=spec.provider,
        currency=spec.currency,
        value=value,
        previous_value=previous,
        as_of=history[-1][0],
        fetched_at=fetched_at,
        change_pct=one_day_change,
        daily_sigma=daily_sigma,
        daily_volatility=daily_volatility,
        trend_volatility=trend_volatility,
        momentum_5d=_momentum(closes, 5),
        momentum_1m=_momentum(closes, 21),
        momentum_3m=_momentum(closes, 63),
        sma13=_sma(closes, 13),
        sma50=_sma(closes, 50),
        sma200=_sma(closes, 200),
        rsi14=_rsi(closes, 14),
        pe=pe,
        forward_pe=forward_pe,
        pb=pb,
        valuation_source=valuation_source,
        pe_percentile=pe_percentile,
        pb_percentile=pb_percentile,
        pe_high_1y=pe_high_1y,
        pe_high_1y_ratio=pe_high_1y_ratio,
        source="Yahoo",
        warnings=tuple(warnings),
    )
    distance = _distance_to_sma(asset.value, asset.sma200)
    trend_sigma = _trend_sigma(distance, asset.trend_volatility or asset.daily_volatility, 200)
    enriched = _replace_asset(
        asset,
        distance_sma200=distance,
        trend_sigma_200d=trend_sigma,
        trend_label=_trend_label(asset.value, asset.sma13, asset.sma50, asset.sma200),
        momentum_label=_momentum_label(asset.rsi14, asset.momentum_1m),
        sigma_label=_sigma_label(asset.daily_sigma, asset.daily_volatility),
        trend_stretch_label=_trend_stretch_label(trend_sigma),
        valuation_label=_valuation_label(spec, pe, forward_pe, pe_percentile),
        crowding_score=_crowding_score(asset.rsi14, distance, pe_percentile, asset.momentum_1m),
    )
    enriched = _replace_asset(enriched, crowding_label=_crowding_label(enriched.crowding_score, enriched.rsi14, enriched.distance_sma200))
    entry_score, entry_label, entry_note, risk_note = _entry_quality(enriched, macro_metrics)
    enriched = _replace_asset(
        enriched,
        entry_score=entry_score,
        entry_label=entry_label,
        entry_note=entry_note,
        risk_management_note=risk_note,
    )
    _write_asset_cache(cache, enriched)
    return enriched


def _cached_or_failed(
    spec: ETFSpec,
    fetched_at: datetime,
    cache: dict[str, Any],
    reason: str,
    macro_metrics: dict[str, Any] | None = None,
) -> ETFAssetMonitor:
    entry = (cache.get("assets") or {}).get(spec.key)
    if entry:
        asset = _asset_from_cache(spec, entry, fetched_at, reason)
        if asset is not None:
            if not spec.equity_like:
                entry_score, entry_label, entry_note, risk_note = _entry_quality(asset, macro_metrics)
                return _replace_asset(
                    asset,
                    entry_score=entry_score,
                    entry_label=entry_label,
                    entry_note=entry_note,
                    risk_management_note=risk_note,
                )
            return asset
    return ETFAssetMonitor(
        key=spec.key,
        label=spec.label,
        symbol=spec.symbol,
        theme=spec.theme,
        provider=spec.provider,
        currency=spec.currency,
        value=None,
        previous_value=None,
        as_of=None,
        fetched_at=fetched_at,
        status="missing",
        warnings=(f"{spec.label}（{spec.symbol}）ETF数据暂不可用：{reason}",),
    )


def _fetch_yahoo_history(symbol: str) -> list[tuple[date, float]]:
    encoded = urllib.parse.quote(symbol, safe="")
    urls = [
        f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded}?range=2y&interval=1d",
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=2y&interval=1d",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            payload = _read_json(url, timeout=15)
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    else:
        raise RuntimeError("; ".join(errors))
    result = payload["chart"]["result"][0]
    scale = 0.01 if result.get("meta", {}).get("currency") == "GBp" else 1.0
    timestamps = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    pairs: list[tuple[date, float]] = []
    for timestamp, close in zip(timestamps, closes):
        value = _safe_float(close)
        if value is None:
            continue
        pairs.append((datetime.fromtimestamp(timestamp, timezone.utc).date(), value * scale))
    return pairs


def _fetch_yahoo_valuation(symbol: str) -> dict[str, float | None]:
    encoded = urllib.parse.quote(symbol, safe="")
    modules = "summaryDetail,defaultKeyStatistics"
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{encoded}?modules={modules}"
    payload = _read_json(url, timeout=12)
    result = payload.get("quoteSummary", {}).get("result") or []
    if not result:
        return {}
    raw = result[0]
    return {
        "trailingPE": _raw_number(raw.get("summaryDetail", {}).get("trailingPE"))
        or _raw_number(raw.get("defaultKeyStatistics", {}).get("trailingPE")),
        "forwardPE": _raw_number(raw.get("summaryDetail", {}).get("forwardPE"))
        or _raw_number(raw.get("defaultKeyStatistics", {}).get("forwardPE")),
        "priceToBook": _raw_number(raw.get("defaultKeyStatistics", {}).get("priceToBook")),
    }


def _fetch_stockanalysis_valuation(symbol: str) -> dict[str, float | None]:
    ticker = symbol.upper()
    if ticker.endswith(".L"):
        ticker = ticker[:-2]
    if not ticker or not re.fullmatch(r"[A-Z0-9]+", ticker):
        return {}
    url = f"https://stockanalysis.com/quote/lon/{ticker}/"
    return _fetch_stockanalysis_valuation_url(url)


def _fetch_stockanalysis_proxy_valuation(symbol: str) -> dict[str, float | None]:
    ticker = symbol.upper()
    if not ticker or not re.fullmatch(r"[A-Z0-9]+", ticker):
        return {}
    return _fetch_stockanalysis_valuation_url(f"https://stockanalysis.com/etf/{ticker.lower()}/")


def _fetch_stockanalysis_valuation_url(url: str) -> dict[str, float | None]:
    text = _read_text(url, timeout=15)
    return {
        "trailingPE": _extract_script_number(text, "peRatio"),
        "forwardPE": _extract_script_number(text, "forwardPE"),
        "priceToBook": _extract_script_number(text, "priceToBook"),
    }


def _has_any_valuation(valuations: dict[str, Any]) -> bool:
    keys = ("trailingPE", "forwardPE", "priceToBook")
    return any(_safe_float(valuations.get(key)) is not None for key in keys)


def _read_json(url: str, timeout: int = 15, attempts: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=ETF_HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(1.4**attempt)
    assert last_error is not None
    raise last_error


def _read_text(url: str, timeout: int = 15, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=ETF_HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(1.4**attempt)
    assert last_error is not None
    raise last_error


def _extract_script_number(text: str, field: str) -> float | None:
    escaped = re.escape(field)
    patterns = [
        rf'{escaped}:"([^"]+)"',
        rf'"{escaped}"\s*:\s*"([^"]+)"',
        rf'"{escaped}"\s*:\s*(-?\d+(?:\.\d+)?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        raw = match.group(1).replace(",", "").strip()
        if raw.lower() in {"n/a", "na", "-", ""}:
            return None
        return _safe_float(raw)
    return None


def _update_valuation_history(
    cache: dict[str, Any],
    key: str,
    day: date,
    pe: float | None,
    pb: float | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    history = cache.setdefault("valuation_history", {}).setdefault(key, [])
    existing = {row.get("date"): row for row in history if isinstance(row, dict)}
    existing[day.isoformat()] = {"date": day.isoformat(), "pe": pe, "pb": pb}
    rows = sorted(existing.values(), key=lambda row: row["date"])[-1300:]
    cache["valuation_history"][key] = rows
    pe_values = [_safe_float(row.get("pe")) for row in rows]
    pb_values = [_safe_float(row.get("pb")) for row in rows]
    one_year_pe_values = [
        _safe_float(row.get("pe"))
        for row in rows
        if _row_within_days(row, day, 365)
    ]
    pe_high_1y = max((item for item in one_year_pe_values if item is not None), default=None)
    pe_high_1y_ratio = pe / pe_high_1y * 100 if pe is not None and pe_high_1y not in (None, 0) else None
    return _percentile(pe, pe_values), _percentile(pb, pb_values), pe_high_1y, pe_high_1y_ratio


def _row_within_days(row: dict[str, Any], day: date, days: int) -> bool:
    try:
        row_day = date.fromisoformat(str(row.get("date")))
    except ValueError:
        return False
    return 0 <= (day - row_day).days <= days


def _write_asset_cache(cache: dict[str, Any], asset: ETFAssetMonitor) -> None:
    cache.setdefault("assets", {})[asset.key] = {
        "label": asset.label,
        "symbol": asset.symbol,
        "theme": asset.theme,
        "provider": asset.provider,
        "currency": asset.currency,
        "value": asset.value,
        "previous_value": asset.previous_value,
        "as_of": asset.as_of.isoformat() if asset.as_of else None,
        "fetched_at": asset.fetched_at.isoformat(),
        "change_pct": asset.change_pct,
        "daily_sigma": asset.daily_sigma,
        "daily_volatility": asset.daily_volatility,
        "trend_volatility": asset.trend_volatility,
        "momentum_5d": asset.momentum_5d,
        "momentum_1m": asset.momentum_1m,
        "momentum_3m": asset.momentum_3m,
        "sma13": asset.sma13,
        "sma50": asset.sma50,
        "sma200": asset.sma200,
        "distance_sma200": asset.distance_sma200,
        "trend_sigma_200d": asset.trend_sigma_200d,
        "rsi14": asset.rsi14,
        "pe": asset.pe,
        "forward_pe": asset.forward_pe,
        "pb": asset.pb,
        "valuation_source": asset.valuation_source,
        "pe_percentile": asset.pe_percentile,
        "pb_percentile": asset.pb_percentile,
        "pe_high_1y": asset.pe_high_1y,
        "pe_high_1y_ratio": asset.pe_high_1y_ratio,
        "trend_label": asset.trend_label,
        "momentum_label": asset.momentum_label,
        "sigma_label": asset.sigma_label,
        "trend_stretch_label": asset.trend_stretch_label,
        "valuation_label": asset.valuation_label,
        "crowding_label": asset.crowding_label,
        "crowding_score": asset.crowding_score,
        "entry_score": asset.entry_score,
        "entry_label": asset.entry_label,
        "entry_note": asset.entry_note,
        "risk_management_note": asset.risk_management_note,
        "source": asset.source,
        "status": asset.status,
        "warnings": list(asset.warnings),
    }


def _asset_from_cache(spec: ETFSpec, entry: dict[str, Any], fetched_at: datetime, reason: str) -> ETFAssetMonitor | None:
    try:
        as_of = date.fromisoformat(entry["as_of"]) if entry.get("as_of") else None
        cached_at = datetime.fromisoformat(entry["fetched_at"]) if entry.get("fetched_at") else fetched_at
    except (TypeError, ValueError):
        return None
    age_days = (fetched_at.date() - as_of).days if as_of else 999
    if age_days > 5:
        return None
    return ETFAssetMonitor(
        key=spec.key,
        label=entry.get("label") or spec.label,
        symbol=entry.get("symbol") or spec.symbol,
        theme=entry.get("theme") or spec.theme,
        provider=entry.get("provider") or spec.provider,
        currency=entry.get("currency") or spec.currency,
        value=_safe_float(entry.get("value")),
        previous_value=_safe_float(entry.get("previous_value")),
        as_of=as_of,
        fetched_at=cached_at,
        change_pct=_safe_float(entry.get("change_pct")),
        daily_sigma=_safe_float(entry.get("daily_sigma")),
        daily_volatility=_safe_float(entry.get("daily_volatility")),
        trend_volatility=_safe_float(entry.get("trend_volatility")),
        momentum_5d=_safe_float(entry.get("momentum_5d")),
        momentum_1m=_safe_float(entry.get("momentum_1m")),
        momentum_3m=_safe_float(entry.get("momentum_3m")),
        sma13=_safe_float(entry.get("sma13")),
        sma50=_safe_float(entry.get("sma50")),
        sma200=_safe_float(entry.get("sma200")),
        distance_sma200=_safe_float(entry.get("distance_sma200")),
        trend_sigma_200d=_safe_float(entry.get("trend_sigma_200d")),
        rsi14=_safe_float(entry.get("rsi14")),
        pe=_safe_float(entry.get("pe")),
        forward_pe=_safe_float(entry.get("forward_pe")),
        pb=_safe_float(entry.get("pb")),
        valuation_source=entry.get("valuation_source") or "unavailable",
        pe_percentile=_safe_float(entry.get("pe_percentile")),
        pb_percentile=_safe_float(entry.get("pb_percentile")),
        pe_high_1y=_safe_float(entry.get("pe_high_1y")),
        pe_high_1y_ratio=_safe_float(entry.get("pe_high_1y_ratio")),
        sigma_label=entry.get("sigma_label") or "日波动待确认",
        trend_stretch_label=entry.get("trend_stretch_label") or "趋势拉伸待确认",
        trend_label=entry.get("trend_label") or "趋势待确认",
        momentum_label=entry.get("momentum_label") or "动量待确认",
        valuation_label=entry.get("valuation_label") or "估值数据不足",
        crowding_label=entry.get("crowding_label") or "拥挤度待确认",
        crowding_score=int(entry.get("crowding_score") or 50),
        entry_score=int(entry.get("entry_score") or 50),
        entry_label=entry.get("entry_label") or "新增仓位环境待确认",
        entry_note=entry.get("entry_note") or "历史样本不足，暂不评估新增仓位环境。",
        risk_management_note=entry.get("risk_management_note") or "仅作环境评估，不构成买卖建议。",
        source="Yahoo cache",
        status="cache",
        warnings=(f"{spec.label}使用本地ETF缓存；实时抓取失败：{reason}",),
    )


def _load_cache() -> dict[str, Any]:
    if not ETF_CACHE_PATH.exists():
        return {"assets": {}, "valuation_history": {}}
    try:
        return json.loads(ETF_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"assets": {}, "valuation_history": {}}


def _save_cache(cache: dict[str, Any]) -> None:
    ETF_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ETF_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_summary(assets: list[ETFAssetMonitor]) -> str:
    live_assets = [asset for asset in assets if asset.value is not None]
    if not live_assets:
        return "ETF资产池暂缺实时数据，当前无法形成趋势与估值判断。"
    hot = [asset for asset in live_assets if asset.crowding_score >= 75]
    weak = [asset for asset in live_assets if asset.distance_sma200 is not None and asset.distance_sma200 < 0]
    strong = [asset for asset in live_assets if asset.distance_sma200 is not None and asset.distance_sma200 > 5]
    parts = [
        f"UK ETF资产池覆盖{len(live_assets)}只主要可交易产品，用于观察趋势、估值重估与短线拥挤度。",
    ]
    if strong:
        parts.append("中长期趋势较强的资产包括：" + "、".join(asset.symbol for asset in strong[:4]) + "。")
    if hot:
        parts.append("短线拥挤度偏高的资产包括：" + "、".join(asset.symbol for asset in hot[:4]) + "，需关注RSI与均线乖离。")
    if weak:
        parts.append("低于200日线的资产包括：" + "、".join(asset.symbol for asset in weak[:4]) + "，趋势确认度较弱。")
    return " ".join(parts)


def _valuation_warnings(
    spec: ETFSpec,
    pe: float | None,
    forward_pe: float | None,
    pb: float | None,
    pe_percentile: float | None,
    pe_high_1y_ratio: float | None,
) -> list[str]:
    if not spec.equity_like:
        return ["黄金ETC不适用PE/PB估值，需结合实际利率、美元和金价趋势观察。"]
    warnings: list[str] = []
    if pe is None and forward_pe is None:
        warnings.append("Yahoo暂未返回可靠PE/Forward PE，估值分位数需要继续积累或使用发行商数据补充。")
    if pb is None:
        warnings.append("PB暂不可用；对科技与主题ETF而言，PB解释力本身弱于PE/Forward PE。")
    if pe_percentile is None and pe_high_1y_ratio is not None:
        warnings.append("PE历史分位数样本不足，当前使用“当前PE/近一年缓存最高PE”作为近似估值位置。")
    elif pe_percentile is None:
        warnings.append("PE历史分位数样本不足，当前只展示现值，不做长期分位判断。")
    return warnings


def _trend_label(value: float | None, sma13: float | None, sma50: float | None, sma200: float | None) -> str:
    if value is None or sma200 is None:
        return "长期趋势待确认"
    short_ok = sma13 is not None and value >= sma13
    mid_ok = sma50 is not None and value >= sma50
    long_ok = value >= sma200
    if long_ok and mid_ok and short_ok:
        return "价格位于13/50/200日线上方，趋势结构偏强"
    if long_ok:
        return "价格仍在200日线上方，但短中期动量需确认"
    return "价格低于200日线，中长期趋势偏弱"


def _momentum_label(rsi14: float | None, momentum_1m: float | None) -> str:
    if rsi14 is None:
        return "RSI不足，动量待确认"
    if rsi14 >= 75:
        return "RSI进入明显超买区，短线追涨风险上升"
    if rsi14 >= 65:
        return "RSI偏热，动量强但拥挤度上升"
    if rsi14 <= 30:
        return "RSI处于超卖区，价格压力已较充分释放"
    if momentum_1m is not None and momentum_1m > 8:
        return "近1个月动量较强，需观察是否演化为拥挤交易"
    if momentum_1m is not None and momentum_1m < -8:
        return "近1个月动量偏弱，风险偏好仍在降温"
    return "RSI位于中性区间，短线动量未显著极端化"


def _valuation_label(spec: ETFSpec, pe: float | None, forward_pe: float | None, pe_percentile: float | None) -> str:
    if not spec.equity_like:
        return "黄金不适用盈利估值，重点观察实际利率与美元"
    active_pe = forward_pe or pe
    if active_pe is None:
        return "估值数据不足，暂不判断重估压力"
    if pe_percentile is not None:
        if pe_percentile >= 80:
            return "PE处于缓存样本高分位，估值重估风险上升"
        if pe_percentile <= 25:
            return "PE处于缓存样本低分位，估值压力相对缓和"
    if active_pe >= 35:
        return "盈利倍数偏高，对利率和盈利预期较敏感"
    if active_pe >= 25:
        return "盈利倍数处于成长资产常见偏高区间"
    return "盈利倍数尚未显示明显极端化"


def _crowding_score(
    rsi14: float | None,
    distance_sma200: float | None,
    pe_percentile: float | None,
    momentum_1m: float | None,
) -> int:
    score = 45
    if rsi14 is not None:
        score += max(0, rsi14 - 55) * 1.1
        score -= max(0, 40 - rsi14) * 0.6
    if distance_sma200 is not None:
        score += max(0, distance_sma200 - 8) * 0.9
        score -= max(0, -distance_sma200) * 0.4
    if pe_percentile is not None:
        score += max(0, pe_percentile - 65) * 0.35
    if momentum_1m is not None:
        score += max(0, momentum_1m - 6) * 0.8
    return _clamp(score)


def _crowding_label(score: int, rsi14: float | None, distance_sma200: float | None) -> str:
    if score >= 80:
        return "拥挤度高：趋势强但短线回撤敏感度上升"
    if score >= 65:
        return "拥挤度偏高：需关注RSI和均线乖离"
    if score <= 35:
        return "拥挤度偏低：价格尚未形成明显过热结构"
    if rsi14 is not None and rsi14 <= 30:
        return "短线超卖：风险释放后可能进入修复观察区"
    if distance_sma200 is not None and distance_sma200 < 0:
        return "趋势偏弱：仍需等待重新站上长期均线"
    return "拥挤度中性：尚未出现极端过热或超卖"


def _entry_quality(asset: ETFAssetMonitor, macro_metrics: dict[str, Any] | None = None) -> tuple[int, str, str, str]:
    if asset.key == "sgln" or not _is_equity_entry_model_asset(asset):
        return _gold_entry_quality(asset, macro_metrics)
    if asset.value is None or asset.sma200 is None:
        return (
            50,
            "历史样本不足，暂不评级",
            "200日趋势样本不足，暂不判断新增仓位环境。",
            "等待更完整的价格历史后再评估趋势框架。",
        )

    score = 50.0
    above_200 = asset.value >= asset.sma200
    above_50 = asset.sma50 is not None and asset.value >= asset.sma50
    pullback_to_50 = asset.sma50 is not None and asset.sma50 > 0 and 0 <= (asset.value / asset.sma50 - 1) * 100 <= 4

    if above_200:
        score += 12
    else:
        score -= 18
    if asset.sma50 is not None and asset.sma50 >= asset.sma200:
        score += 6
    if above_50:
        score += 4
    if pullback_to_50 and above_200:
        score += 10

    if asset.distance_sma200 is not None:
        if 0 <= asset.distance_sma200 <= 15:
            score += 8
        elif asset.distance_sma200 > 30:
            score -= 15
        elif asset.distance_sma200 > 20:
            score -= 8
        elif asset.distance_sma200 < 0:
            score -= 10

    if asset.trend_sigma_200d is not None:
        if asset.trend_sigma_200d >= 3:
            score -= 20
        elif asset.trend_sigma_200d >= 2:
            score -= 12
        elif 0 <= asset.trend_sigma_200d <= 1.5:
            score += 6
        elif asset.trend_sigma_200d <= -1:
            score -= 8

    if asset.rsi14 is not None:
        if 42 <= asset.rsi14 <= 60:
            score += 12
        elif 60 < asset.rsi14 <= 68:
            score += 5
        elif asset.rsi14 >= 75:
            score -= 18
        elif asset.rsi14 >= 70:
            score -= 8
        elif asset.rsi14 < 30:
            score -= 12 if not above_200 else 4

    if asset.momentum_1m is not None:
        if 0 <= asset.momentum_1m <= 8:
            score += 8
        elif asset.momentum_1m > 18:
            score -= 12
        elif asset.momentum_1m > 12:
            score -= 6
        elif asset.momentum_1m < -8:
            score -= 8
    if asset.momentum_3m is not None and asset.momentum_3m > 0:
        score += 4

    if asset.daily_sigma is not None:
        if abs(asset.daily_sigma) <= 1:
            score += 4
        elif abs(asset.daily_sigma) >= 2.5:
            score -= 8

    if asset.pe_percentile is not None and asset.pe_percentile >= 80:
        score -= 5
    elif asset.pe_high_1y_ratio is not None and asset.pe_high_1y_ratio >= 95:
        score -= 3

    final_score = _clamp(score)
    return final_score, _entry_label(final_score), _entry_note(asset, final_score), _risk_management_note(asset, final_score)


def _entry_label(score: int) -> str:
    if score >= 75:
        return "趋势结构完好，等待回调确认"
    if score >= 60:
        return "新增仓位环境中性偏好"
    if score >= 45:
        return "信号分歧，等待确认"
    return "追高风险或趋势压力较高"


def _gold_entry_quality(asset: ETFAssetMonitor, macro_metrics: dict[str, Any] | None = None) -> tuple[int, str, str, str]:
    score = 50.0
    real_yield = _metric_value(macro_metrics, "real_yield_10y")
    real_yield_change = _metric_change(macro_metrics, "real_yield_10y")
    dxy_change_pct = _metric_change_pct(macro_metrics, "dxy")
    ten_year_change = _metric_change(macro_metrics, "treasury_10y")
    nasdaq_change_pct = _metric_change_pct(macro_metrics, "nasdaq")
    vix_change_pct = _metric_change_pct(macro_metrics, "vix")
    gold_change_pct = _metric_change_pct(macro_metrics, "gold")

    if asset.value is not None and asset.sma200 is not None:
        score += 8 if asset.value >= asset.sma200 else -8
    if asset.sma50 is not None and asset.sma200 is not None:
        score += 4 if asset.sma50 >= asset.sma200 else -4
    if asset.trend_sigma_200d is not None:
        if asset.trend_sigma_200d >= 2:
            score -= 8
        elif 0 <= asset.trend_sigma_200d <= 1.5:
            score += 4
    if asset.rsi14 is not None:
        if 45 <= asset.rsi14 <= 65:
            score += 5
        elif asset.rsi14 >= 75:
            score -= 10
        elif asset.rsi14 <= 30:
            score -= 5

    if real_yield is not None:
        if real_yield >= 2.1:
            score -= 10
        elif real_yield <= 1.7:
            score += 6
    if real_yield_change is not None:
        if real_yield_change > 0.03:
            score -= 10
        elif real_yield_change < -0.03:
            score += 10
    if dxy_change_pct is not None:
        if dxy_change_pct > 0.3:
            score -= 8
        elif dxy_change_pct <= 0:
            score += 5
    if ten_year_change is not None and dxy_change_pct is not None and ten_year_change > 0.04 and dxy_change_pct > 0:
        score -= 6
    if nasdaq_change_pct is not None and gold_change_pct is not None and nasdaq_change_pct < -0.5 and gold_change_pct > 0:
        score += 5
    if vix_change_pct is not None:
        if 3 <= vix_change_pct <= 10 and (dxy_change_pct or 0) <= 0.3:
            score += 3
        elif vix_change_pct > 12 and (dxy_change_pct or 0) > 0.3:
            score -= 6
    if gold_change_pct is not None:
        if gold_change_pct > 0:
            score += 3
        elif gold_change_pct < -1:
            score -= 4

    missing = [
        label
        for key, label in (
            ("real_yield_10y", "实际利率"),
            ("dxy", "美元指数"),
            ("treasury_10y", "10年期美债收益率"),
        )
        if _metric_value(macro_metrics, key) is None
    ]
    if missing:
        score -= min(8, len(missing) * 3)

    final_score = _clamp(score)
    return final_score, _gold_entry_label(final_score), _gold_entry_note(final_score, missing), _gold_risk_note(final_score)


def _gold_entry_label(score: int) -> str:
    if score >= 70:
        return "黄金配置环境偏友好"
    if score >= 55:
        return "黄金配置环境中性偏友好"
    if score >= 45:
        return "黄金配置环境中性，等待宏观确认"
    return "实际利率/美元压力偏高"


def _gold_entry_note(score: int, missing: list[str]) -> str:
    limitation = f" 部分输入缺失：{'、'.join(missing)}，结论需降权。" if missing else ""
    if score >= 70:
        return "实际利率、美元或金价趋势组合对黄金相对友好，配置环境优于中性水平。" + limitation
    if score >= 55:
        return "黄金趋势尚可，宏观压力未明显扩散，但仍需观察实际利率和美元是否重新走强。" + limitation
    if score >= 45:
        return "黄金配置环境接近中性，趋势信号与宏观约束尚未形成清晰共振。" + limitation
    return "实际利率或美元压力偏高，黄金配置环境承压，需要等待宏观阻力缓和。" + limitation


def _gold_risk_note(score: int) -> str:
    if score >= 70:
        return "风险管理重点：若实际利率与美元重新同步上行，黄金的配置分数应快速下调。"
    if score >= 55:
        return "风险管理重点：确认金价强势是否由实际利率回落驱动，而非单日避险波动。"
    return "风险管理重点：优先观察实际利率、美元和长端收益率是否停止同步走强。"


def _entry_note(asset: ETFAssetMonitor, score: int) -> str:
    if asset.value is not None and asset.sma200 is not None and asset.value < asset.sma200:
        return "价格低于200日线，趋势框架尚未修复，新增仓位更依赖右侧确认。"
    if asset.trend_sigma_200d is not None and asset.trend_sigma_200d >= 2:
        return "价格相对200日线已明显拉伸，新增仓位性价比下降，更适合等待冷却或均线回归。"
    if asset.rsi14 is not None and asset.rsi14 >= 70:
        return "RSI处于偏热区间，动量仍强但短线追高风险上升。"
    if asset.sma50 is not None and asset.value is not None and asset.sma200 is not None:
        distance_50 = (asset.value / asset.sma50 - 1) * 100 if asset.sma50 else None
        if distance_50 is not None and 0 <= distance_50 <= 4 and asset.value >= asset.sma200:
            return "长期趋势仍在，价格靠近50日线，属于相对有质量的趋势内回调。"
    if score >= 75:
        return "趋势结构、动量和拉伸度相对均衡，但新增仓位仍宜等待有序回调确认。"
    if score >= 60:
        return "趋势尚可，但动量或估值位置需要继续观察，适合分批观察而非一次性追涨。"
    return "趋势、动量或波动条件尚未形成清晰优势，等待更明确的回调质量或突破确认。"


def _risk_management_note(asset: ETFAssetMonitor, score: int) -> str:
    if asset.value is not None and asset.sma200 is not None and asset.value < asset.sma200:
        return "风险管理重点：观察能否重新站上200日线；未修复前避免把反弹视为趋势延续。"
    if asset.trend_sigma_200d is not None and asset.trend_sigma_200d >= 2:
        return "风险管理重点：趋势拥挤，新增仓位应降低节奏，警惕均值回归和高位波动放大。"
    if asset.rsi14 is not None and asset.rsi14 >= 70:
        return "风险管理重点：动量偏热，若跌破13日线或50日线，需警惕获利回吐扩散。"
    if score >= 70:
        return "风险管理重点：以趋势延续框架观察，若跌破50日线且动量转负，入场质量会明显下降。"
    return "风险管理重点：等待价格、RSI和中期均线重新形成一致性，避免在信号分歧时放大敞口。"


def _metric_value(metrics: dict[str, Any] | None, key: str) -> float | None:
    metric = (metrics or {}).get(key)
    return _safe_float(getattr(metric, "value", None))


def _metric_change(metrics: dict[str, Any] | None, key: str) -> float | None:
    metric = (metrics or {}).get(key)
    return _safe_float(getattr(metric, "change", None))


def _metric_change_pct(metrics: dict[str, Any] | None, key: str) -> float | None:
    metric = (metrics or {}).get(key)
    return _safe_float(getattr(metric, "change_pct", None))


def _is_equity_entry_model_asset(asset: ETFAssetMonitor) -> bool:
    return asset.key != "sgln"


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for current, previous in zip(values[-window:], values[-window - 1 : -1]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _momentum(values: list[float], days: int) -> float | None:
    if len(values) <= days or values[-days - 1] == 0:
        return None
    return _pct_change(values[-1], values[-days - 1])


def _daily_returns(values: list[float]) -> list[float]:
    returns: list[float] = []
    for current, previous in zip(values[1:], values[:-1]):
        pct = _pct_change(current, previous)
        if pct is not None:
            returns.append(pct)
    return returns


def _rolling_std(values: list[float], window: int) -> float | None:
    sample = values[-window:]
    if len(sample) < 30:
        return None
    mean = sum(sample) / len(sample)
    variance = sum((item - mean) ** 2 for item in sample) / (len(sample) - 1)
    return math.sqrt(variance)


def _robust_trend_volatility(values: list[float]) -> float | None:
    windows = (63, 126, 252)
    estimates = [
        estimate
        for window in windows
        if (estimate := _winsorized_std(values[-window:])) is not None
    ]
    if not estimates:
        return None
    return _median(estimates)


def _winsorized_std(sample: list[float]) -> float | None:
    clean = [item for item in sample if math.isfinite(item)]
    if len(clean) < 30:
        return None
    lower = _quantile(clean, 0.05)
    upper = _quantile(clean, 0.95)
    clipped = [min(max(item, lower), upper) for item in clean]
    mean = sum(clipped) / len(clipped)
    variance = sum((item - mean) ** 2 for item in clipped) / (len(clipped) - 1)
    return math.sqrt(variance)


def _quantile(values: list[float], q: float) -> float:
    clean = sorted(values)
    if not clean:
        return 0.0
    position = (len(clean) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return clean[int(position)]
    weight = position - lower
    return clean[lower] * (1 - weight) + clean[upper] * weight


def _median(values: list[float]) -> float:
    clean = sorted(values)
    midpoint = len(clean) // 2
    if len(clean) % 2:
        return clean[midpoint]
    return (clean[midpoint - 1] + clean[midpoint]) / 2


def _sigma_move(change_pct: float | None, daily_volatility: float | None) -> float | None:
    if change_pct is None or daily_volatility in (None, 0):
        return None
    return change_pct / daily_volatility


def _sigma_label(daily_sigma: float | None, daily_volatility: float | None) -> str:
    if daily_sigma is None or daily_volatility is None:
        return "历史日波动样本不足，暂不做sigma判断"
    magnitude = abs(daily_sigma)
    direction = "上行" if daily_sigma > 0 else "下行" if daily_sigma < 0 else "持平"
    if magnitude >= 3:
        return f"{direction}超过3σ，属于极端单日波动"
    if magnitude >= 2:
        return f"{direction}达到2σ以上，显著偏离常态日波动"
    if magnitude >= 1:
        return f"{direction}约1-2σ，属于偏强但仍可解释的日波动"
    return "低于1σ，属于常态日波动范围"


def _trend_sigma(distance_pct: float | None, daily_volatility: float | None, horizon_days: int) -> float | None:
    if distance_pct is None or daily_volatility in (None, 0):
        return None
    horizon_volatility = daily_volatility * math.sqrt(horizon_days)
    if horizon_volatility == 0:
        return None
    return distance_pct / horizon_volatility


def _trend_stretch_label(trend_sigma: float | None) -> str:
    if trend_sigma is None:
        return "历史波动样本不足，暂不做趋势拉伸判断"
    magnitude = abs(trend_sigma)
    if trend_sigma >= 3:
        return "高于200日线超过3σ200，趋势极度拉伸，回撤敏感度较高"
    if trend_sigma >= 2:
        return "高于200日线达到2σ200以上，趋势偏热，需警惕均值回归"
    if trend_sigma >= 1:
        return "高于200日线约1-2σ200，趋势较强但尚未极端化"
    if trend_sigma <= -2:
        return "低于200日线超过2σ200，趋势压力较深，修复需要时间"
    if trend_sigma <= -1:
        return "低于200日线约1-2σ200，中期趋势仍偏弱"
    return "距200日线低于1σ200，趋势拉伸度仍在常态范围"


def _distance_to_sma(value: float | None, sma: float | None) -> float | None:
    if value is None or sma in (None, 0):
        return None
    return (value / sma - 1) * 100


def _pct_change(value: float | None, previous: float | None) -> float | None:
    if value is None or previous in (None, 0):
        return None
    return (value / previous - 1) * 100


def _percentile(value: float | None, values: list[float | None]) -> float | None:
    if value is None:
        return None
    clean = sorted(item for item in values if item is not None and math.isfinite(item))
    if len(clean) < 20:
        return None
    below = sum(1 for item in clean if item <= value)
    return below / len(clean) * 100


def _raw_number(value: Any) -> float | None:
    if isinstance(value, dict):
        return _safe_float(value.get("raw"))
    return _safe_float(value)


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _clamp(value: float, lower: int = 0, upper: int = 100) -> int:
    return int(max(lower, min(upper, round(value))))


def _replace_asset(asset: ETFAssetMonitor, **changes: Any) -> ETFAssetMonitor:
    data = asset.__dict__.copy()
    data.update(changes)
    return ETFAssetMonitor(**data)
