from __future__ import annotations

import json
import math
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
    pe_percentile: float | None = None
    pb_percentile: float | None = None
    trend_label: str = "趋势待确认"
    momentum_label: str = "动量待确认"
    valuation_label: str = "估值数据不足"
    crowding_label: str = "拥挤度待确认"
    sigma_label: str = "日波动待确认"
    trend_stretch_label: str = "趋势拉伸待确认"
    crowding_score: int = 50
    source: str = "Yahoo"
    status: str = "ok"
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ETFMonitor:
    summary: str
    assets: list[ETFAssetMonitor]
    warnings: list[str]


DEFAULT_ETF_SPECS = [
    ETFSpec("vuag", "Vanguard S&P 500 UCITS ETF", "VUAG.L", "S&P 500", "Vanguard"),
    ETFSpec("cnx1", "iShares Nasdaq 100 UCITS ETF", "CNX1.L", "Nasdaq 100", "iShares"),
    ETFSpec("semi", "iShares Global Semiconductors ETF", "SEMI.L", "Semiconductor", "iShares"),
    ETFSpec("qwtm", "WisdomTree Quantum Computing ETF", "QWTM.L", "Quantum Computing", "WisdomTree"),
    ETFSpec("qntm", "VanEck Quantum Computing ETF", "QNTM.L", "Quantum Computing", "VanEck"),
    ETFSpec("qant", "iShares Quantum Computing ETF", "QANT.L", "Quantum Computing", "iShares"),
    ETFSpec("sgln", "iShares Physical Gold ETC", "SGLN.L", "Gold", "iShares", equity_like=False),
]


def fetch_etf_monitor(specs: list[ETFSpec] | None = None) -> ETFMonitor:
    fetched_at = datetime.now(timezone.utc)
    cache = _load_cache()
    assets: list[ETFAssetMonitor] = []
    warnings: list[str] = []
    for spec in specs or DEFAULT_ETF_SPECS:
        try:
            asset = _fetch_etf_asset(spec, fetched_at, cache)
        except Exception as exc:
            asset = _cached_or_failed(spec, fetched_at, cache, f"{type(exc).__name__}: {exc}")
        assets.append(asset)
        warnings.extend(asset.warnings)
    _save_cache(cache)
    return ETFMonitor(summary=_build_summary(assets), assets=assets, warnings=list(dict.fromkeys(warnings)))


def _fetch_etf_asset(spec: ETFSpec, fetched_at: datetime, cache: dict[str, Any]) -> ETFAssetMonitor:
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
    daily_sigma = _sigma_move(one_day_change, daily_volatility)
    valuation_fetch_warning: str | None = None
    try:
        valuations = _fetch_yahoo_valuation(spec.symbol) if spec.equity_like else {}
    except Exception as exc:
        valuations = {}
        valuation_fetch_warning = f"Yahoo估值接口暂不可用：{type(exc).__name__}"
    pe = _safe_float(valuations.get("trailingPE"))
    forward_pe = _safe_float(valuations.get("forwardPE"))
    pb = _safe_float(valuations.get("priceToBook"))
    pe_percentile, pb_percentile = _update_valuation_history(cache, spec.key, fetched_at.date(), pe, pb)
    warnings = _valuation_warnings(spec, pe, forward_pe, pb, pe_percentile)
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
        pe_percentile=pe_percentile,
        pb_percentile=pb_percentile,
        source="Yahoo",
        warnings=tuple(warnings),
    )
    distance = _distance_to_sma(asset.value, asset.sma200)
    trend_sigma = _trend_sigma(distance, asset.daily_volatility, 200)
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
    _write_asset_cache(cache, enriched)
    return enriched


def _cached_or_failed(spec: ETFSpec, fetched_at: datetime, cache: dict[str, Any], reason: str) -> ETFAssetMonitor:
    entry = (cache.get("assets") or {}).get(spec.key)
    if entry:
        asset = _asset_from_cache(spec, entry, fetched_at, reason)
        if asset is not None:
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


def _update_valuation_history(
    cache: dict[str, Any],
    key: str,
    day: date,
    pe: float | None,
    pb: float | None,
) -> tuple[float | None, float | None]:
    history = cache.setdefault("valuation_history", {}).setdefault(key, [])
    existing = {row.get("date"): row for row in history if isinstance(row, dict)}
    existing[day.isoformat()] = {"date": day.isoformat(), "pe": pe, "pb": pb}
    rows = sorted(existing.values(), key=lambda row: row["date"])[-1300:]
    cache["valuation_history"][key] = rows
    pe_values = [_safe_float(row.get("pe")) for row in rows]
    pb_values = [_safe_float(row.get("pb")) for row in rows]
    return _percentile(pe, pe_values), _percentile(pb, pb_values)


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
        "pe_percentile": asset.pe_percentile,
        "pb_percentile": asset.pb_percentile,
        "trend_label": asset.trend_label,
        "momentum_label": asset.momentum_label,
        "sigma_label": asset.sigma_label,
        "trend_stretch_label": asset.trend_stretch_label,
        "valuation_label": asset.valuation_label,
        "crowding_label": asset.crowding_label,
        "crowding_score": asset.crowding_score,
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
        pe_percentile=_safe_float(entry.get("pe_percentile")),
        pb_percentile=_safe_float(entry.get("pb_percentile")),
        sigma_label=entry.get("sigma_label") or "日波动待确认",
        trend_stretch_label=entry.get("trend_stretch_label") or "趋势拉伸待确认",
        trend_label=entry.get("trend_label") or "趋势待确认",
        momentum_label=entry.get("momentum_label") or "动量待确认",
        valuation_label=entry.get("valuation_label") or "估值数据不足",
        crowding_label=entry.get("crowding_label") or "拥挤度待确认",
        crowding_score=int(entry.get("crowding_score") or 50),
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
) -> list[str]:
    if not spec.equity_like:
        return ["黄金ETC不适用PE/PB估值，需结合实际利率、美元和金价趋势观察。"]
    warnings: list[str] = []
    if pe is None and forward_pe is None:
        warnings.append("Yahoo暂未返回可靠PE/Forward PE，估值分位数需要继续积累或使用发行商数据补充。")
    if pb is None:
        warnings.append("PB暂不可用；对科技与主题ETF而言，PB解释力本身弱于PE/Forward PE。")
    if pe_percentile is None:
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
