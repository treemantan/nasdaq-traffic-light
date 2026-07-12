from __future__ import annotations

import csv
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any


CACHE_PATH = Path("output") / "cache" / "market_data_cache.json"
CORE_KEYS = {"nasdaq", "sp500", "vix", "treasury_10y", "dxy", "gold"}
DEFAULT_HTTP_HEADERS = {"User-Agent": "macro-regime-radar/0.3"}
FRED_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,*/*",
    "Connection": "close",
}
CNN_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
}
INVESTING_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close",
}
INVESTING_RATE_SOURCES = {
    "treasury_2y": ("https://www.investing.com/rates-bonds/u.s.-2-year-bond-yield", "US2YT=X"),
    "treasury_10y": ("https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield", "US10YT=X"),
}
NAAIM_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,*/*",
    "Connection": "close",
}
VIX_TERM_STRUCTURE_URL = "https://www.cboe.com/tradable-products/vix/term-structure"


@dataclass(frozen=True)
class MarketMetric:
    key: str
    label: str
    description: str
    symbol: str
    source: str
    value: float | None
    previous_value: float | None
    as_of: date | None
    fetched_at: datetime
    unit: str = ""
    category: str = "macro"
    status: str = "ok"
    warnings: tuple[str, ...] = field(default_factory=tuple)
    delayed: bool = True
    importance: str = "auxiliary"
    freshness: str = "live"
    live_source: str | None = None
    fetch_error: str | None = None

    @property
    def change(self) -> float | None:
        if self.value is None or self.previous_value is None:
            return None
        return self.value - self.previous_value

    @property
    def change_pct(self) -> float | None:
        if self.value is None or self.previous_value in (None, 0):
            return None
        return (self.value / self.previous_value - 1) * 100

    @property
    def age_days(self) -> int | None:
        if self.as_of is None:
            return None
        return (_safe_today() - self.as_of).days

    @property
    def is_stale(self) -> bool:
        if self.value is None or self.age_days is None:
            return True
        if self.status in {"missing", "suspicious"}:
            return True
        return self.freshness in {"stale", "cache-stale"}


@dataclass(frozen=True)
class MarketSnapshot:
    as_of: date
    fetched_at: datetime
    metrics: dict[str, MarketMetric]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    description: str
    symbol: str
    source: str
    category: str
    unit: str = ""
    scale: float = 1.0
    min_value: float | None = None
    max_value: float | None = None
    stale_days: int = 4
    cache_days: int = 5
    required: bool = False

    @property
    def importance(self) -> str:
        return "core" if self.key in CORE_KEYS else "auxiliary"


YAHOO_SPECS = [
    MetricSpec("nasdaq", "纳斯达克100", "大型科技、AI主线与高久期成长资产风险偏好的核心代理变量", "^NDX", "Yahoo", "权益", required=True),
    MetricSpec("sp500", "标普500", "美股大盘风险资产定价锚", "^GSPC", "Yahoo", "权益", required=True),
    MetricSpec("russell2000", "罗素2000", "美国内需与中小盘风险偏好的代理变量", "^RUT", "Yahoo", "权益"),
    MetricSpec("vix", "VIX波动率", "权益风险溢价与避险需求的高频温度计", "^VIX", "Yahoo", "波动率", min_value=8, max_value=90, required=True),
    MetricSpec("vix9d", "VIX9D短期波动率", "SPX期权隐含的9日预期波动，用于识别近期事件风险是否前置", "^VIX9D", "Yahoo", "波动率", min_value=5, max_value=150),
    MetricSpec("vix3m", "VIX3M三个月波动率", "SPX期权隐含的三个月预期波动，用于判断波动期限结构", "^VIX3M", "Yahoo", "波动率", min_value=5, max_value=120),
    MetricSpec("vvix", "VVIX波动率", "VIX自身波动率，反映尾部风险定价", "^VVIX", "Yahoo", "波动率", min_value=50, max_value=220),
    MetricSpec("vixeq", "VIXEQ成分股隐含波动", "S&P 500成分股期权的市值加权30日隐含波动，用于观察指数表面之下的个股风险", "^VIXEQ", "Yahoo", "波动率", min_value=5, max_value=150),
    MetricSpec("cor1m", "COR1M一个月隐含相关性", "S&P 500成分股一个月隐含相关性，用于区分系统性共振与个股离散", "^COR1M", "Yahoo", "波动率", min_value=0, max_value=100),
    MetricSpec("dxy", "美元指数DXY", "美元流动性与全球金融条件的重要代理变量", "DX-Y.NYB", "Yahoo", "外汇", min_value=80, max_value=130, required=True),
    MetricSpec("gbpusd", "英镑兑美元", "非美货币风险偏好与美元强弱的交叉验证", "GBPUSD=X", "Yahoo", "外汇", min_value=0.8, max_value=1.6),
    MetricSpec("usdjpy", "美元兑日元", "利差、套息与美元流动性的综合代理变量", "JPY=X", "Yahoo", "外汇", min_value=90, max_value=180),
    MetricSpec("gold", "黄金", "实际利率、美元与避险需求的交叉资产映射", "GC=F", "Yahoo", "商品", min_value=1000, max_value=5000, required=True),
    MetricSpec("oil", "WTI原油", "增长、通胀与地缘风险的商品侧信号", "CL=F", "Yahoo", "商品", min_value=10, max_value=200),
    MetricSpec("move", "MOVE债券波动率", "美债市场波动与金融条件压力代理变量", "^MOVE", "Yahoo", "流动性", min_value=40, max_value=300),
]

FRED_SPECS = [
    MetricSpec("treasury_2y", "美国2年期收益率", "政策利率预期与前端利率定价", "DGS2", "FRED", "利率", "%", min_value=0.5, max_value=8, required=True, stale_days=7, cache_days=14),
    MetricSpec("treasury_10y", "美国10年期收益率", "长端贴现率、期限溢价与名义增长预期", "DGS10", "FRED", "利率", "%", min_value=1, max_value=8, required=True, stale_days=7, cache_days=14),
    MetricSpec("real_yield_10y", "10年期实际利率（市场近似）", "用市场10年期收益率减10年盈亏平衡通胀率估算，反映高估值成长与黄金面对的实时贴现率约束", "US10YT-X-T10YIE", "derived", "利率", "%", min_value=-2, max_value=5, stale_days=10, cache_days=21),
    MetricSpec("inflation_expectation_10y", "10年盈亏平衡通胀率（年化）", "FRED T10YIE，反映市场隐含的未来10年平均年化通胀补偿", "T10YIE", "FRED", "利率", "%", min_value=0.5, max_value=5, stale_days=10, cache_days=21),
    MetricSpec("credit_spread_hy", "高收益信用利差", "信用风险补偿与融资条件压力", "BAMLH0A0HYM2", "FRED", "信用", "%", min_value=2, max_value=20, stale_days=10, cache_days=21),
    MetricSpec("fed_balance_sheet", "美联储资产负债表", "QE/QT方向性代理变量", "WALCL", "FRED", "流动性", "USD bn", scale=1 / 1000, min_value=3000, max_value=12000, stale_days=21, cache_days=35),
    MetricSpec("rrp", "隔夜逆回购RRP", "闲置美元流动性与货币市场缓冲", "RRPONTSYD", "FRED", "流动性", "USD bn", min_value=0, max_value=3000, stale_days=10, cache_days=21),
    MetricSpec("tga", "财政部一般账户TGA", "财政现金余额变化对银行体系流动性的抽离或释放", "WTREGEN", "FRED", "流动性", "USD bn", scale=1 / 1000, min_value=0, max_value=2000, stale_days=21, cache_days=35),
    MetricSpec("bank_reserves", "银行准备金", "银行体系美元流动性底层缓冲", "WRESBAL", "FRED", "流动性", "USD bn", scale=1 / 1000, min_value=1000, max_value=6000, stale_days=21, cache_days=35),
]

CNN_SPECS = [
    MetricSpec(
        "cnn_fear_greed",
        "CNN恐惧与贪婪指数",
        "CNN Fear & Greed Index，衡量美股市场情绪与风险偏好极端程度",
        "CNN:FearGreed",
        "CNN",
        "情绪",
        "",
        min_value=0,
        max_value=100,
        stale_days=7,
        cache_days=14,
    ),
]

NAAIM_SPECS = [
    MetricSpec(
        "naaim_exposure",
        "NAAIM主动管理人权益敞口",
        "NAAIM Exposure Index，周频调查主动管理人对美股权益市场的平均敞口",
        "NAAIM:Exposure",
        "NAAIM",
        "情绪",
        "",
        min_value=-200,
        max_value=200,
        stale_days=10,
        cache_days=21,
    ),
]


def fetch_market_snapshot() -> MarketSnapshot:
    fetched_at = datetime.now(timezone.utc)
    cache = _load_cache()
    metrics: dict[str, MarketMetric] = {}
    warnings: list[str] = []

    for spec in YAHOO_SPECS:
        metric = _fetch_with_cache(spec, fetched_at, cache, _fetch_yahoo_live)
        metrics[spec.key] = metric
        warnings.extend(metric.warnings)

    futures_metrics = _fetch_vix_futures_curve(fetched_at, cache)
    metrics.update(futures_metrics)
    for metric in futures_metrics.values():
        warnings.extend(metric.warnings)

    for spec in CNN_SPECS:
        metric = _fetch_with_cache(spec, fetched_at, cache, _fetch_cnn_fear_greed_live)
        metrics[spec.key] = metric
        warnings.extend(metric.warnings)

    for spec in NAAIM_SPECS:
        metric = _fetch_with_cache(spec, fetched_at, cache, _fetch_naaim_exposure_live)
        metrics[spec.key] = metric
        warnings.extend(metric.warnings)

    pending_fred: list[MetricSpec] = []
    for spec in FRED_SPECS:
        pending_fred.append(spec)

    if pending_fred:
        with ThreadPoolExecutor(max_workers=min(4, len(pending_fred))) as executor:
            futures = {executor.submit(_fetch_with_cache, spec, fetched_at, cache, _fetch_fred_live): spec for spec in pending_fred}
            for future in as_completed(futures):
                spec = futures[future]
                try:
                    metric = future.result()
                except Exception as exc:
                    metric = _cache_or_failed(spec, fetched_at, cache, f"FRED请求异常：{type(exc).__name__}")
                if metric.status != "ok":
                    _write_provider_failure(cache, "FRED", fetched_at)
                metrics[spec.key] = metric
                warnings.extend(metric.warnings)

    _apply_market_rate_overrides(metrics, fetched_at, cache, warnings)
    _apply_critical_fallbacks(metrics, fetched_at, cache, warnings)
    _derive_missing_metrics(metrics, fetched_at, cache, warnings)

    _save_cache(cache)
    latest_dates = [metric.as_of for metric in metrics.values() if metric.as_of is not None]
    as_of = max(latest_dates) if latest_dates else _safe_today()
    warnings.extend(_snapshot_warnings(metrics))
    return MarketSnapshot(as_of=as_of, fetched_at=fetched_at, metrics=metrics, warnings=tuple(dict.fromkeys(warnings)))


def _fetch_vix_futures_curve(fetched_at: datetime, cache: dict[str, Any]) -> dict[str, MarketMetric]:
    specs = [
        MetricSpec(f"vix_future_{month}", f"VIX期货M{month}", "Cboe VIX期货期限结构", f"VIX{month}", "Cboe", "波动率", min_value=5, max_value=150, cache_days=7)
        for month in range(1, 4)
    ]
    try:
        request = urllib.request.Request(VIX_TERM_STRUCTURE_URL, headers=DEFAULT_HTTP_HEADERS)
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace").replace('\\"', '"')
        expirations = {
            symbol: expiry
            for symbol, expiry in re.findall(r'"symbol":"(VIX[1-3])","month":\d+,"expirationDate":"([^"]+)"', html)
        }
        prices = {
            symbol: (float(price), price_time)
            for symbol, price, price_time in re.findall(
                r'"index_symbol":"(VIX[1-3])"[^}]*?"price":([0-9.]+),"price_time":"([^"]+)"', html
            )
        }
        result: dict[str, MarketMetric] = {}
        for month, spec in enumerate(specs, start=1):
            symbol = f"VIX{month}"
            if symbol not in prices:
                raise ValueError(f"Cboe payload missing {symbol}")
            price, price_time = prices[symbol]
            as_of = datetime.strptime(price_time.split()[0], "%m/%d/%Y").date()
            metric = MarketMetric(
                key=spec.key,
                label=spec.label,
                description=f"{spec.description}；到期 {expirations.get(symbol, 'N/A')}",
                symbol=symbol,
                source="Cboe term structure",
                value=price,
                previous_value=None,
                as_of=as_of,
                fetched_at=fetched_at,
                category=spec.category,
                delayed=True,
                importance=spec.importance,
            )
            metric = _validate_metric(metric, spec)
            _write_cache_entry(cache, metric)
            result[spec.key] = metric
        return result
    except Exception as exc:
        return {
            spec.key: _cache_or_failed(spec, fetched_at, cache, f"Cboe VIX期限结构获取失败：{type(exc).__name__}")
            for spec in specs
        }


def _fetch_with_cache(spec: MetricSpec, fetched_at: datetime, cache: dict[str, Any], fetcher) -> MarketMetric:
    try:
        metric = fetcher(spec, fetched_at)
        metric = _validate_metric(metric, spec)
        if metric.status == "ok":
            _write_cache_entry(cache, metric)
        return metric
    except Exception as exc:
        cached = _metric_from_cache(spec, fetched_at, cache, f"{type(exc).__name__}: {exc}")
        if cached is not None:
            return cached
        return _failed_metric(spec, fetched_at, f"{spec.label}（{spec.symbol}）实时数据获取失败，且无可用新鲜缓存：{type(exc).__name__}")


def _cache_or_failed(spec: MetricSpec, fetched_at: datetime, cache: dict[str, Any], reason: str) -> MarketMetric:
    cached = _metric_from_cache(spec, fetched_at, cache, reason)
    if cached is not None:
        return cached
    return _failed_metric(spec, fetched_at, reason)


def _fetch_yahoo_live(spec: MetricSpec, fetched_at: datetime) -> MarketMetric:
    encoded = urllib.parse.quote(spec.symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=15d&interval=1d"
    payload = _read_json(url, timeout=15)
    result = payload["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    timestamps = result.get("timestamp", [])
    pairs = [
        (datetime.fromtimestamp(ts, timezone.utc).date(), float(close) * spec.scale)
        for ts, close in zip(timestamps, closes)
        if close is not None and math.isfinite(float(close))
    ]
    return _metric_from_pairs(spec, pairs, fetched_at, "live", spec.source)


def _fetch_fred_live(spec: MetricSpec, fetched_at: datetime) -> MarketMetric:
    if spec.key == "real_yield_10y":
        raise ValueError("real_yield_10y is derived from market 10Y and breakeven inflation")
    observation_start = (_safe_today() - timedelta(days=180)).isoformat()
    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(spec.symbol)}"
        f"&cosd={observation_start}"
    )
    text = _read_text(url, timeout=15, attempts=2, headers=FRED_HTTP_HEADERS)
    rows = list(csv.DictReader(StringIO(text)))
    pairs: list[tuple[date, float]] = []
    for row in rows:
        raw_value = row.get(spec.symbol, ".")
        if raw_value in ("", "."):
            continue
        pairs.append((date.fromisoformat(row["observation_date"]), float(raw_value) * spec.scale))
    return _metric_from_pairs(spec, pairs, fetched_at, "recent-valid", spec.source)


def _fetch_cnn_fear_greed_live(spec: MetricSpec, fetched_at: datetime) -> MarketMetric:
    start = (_safe_today() - timedelta(days=45)).isoformat()
    urls = [
        f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start}",
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            payload = _read_json(url, timeout=15, headers=CNN_HTTP_HEADERS)
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    else:
        raise RuntimeError("; ".join(errors))
    pairs = _extract_cnn_fear_greed_pairs(payload)
    return _metric_from_pairs(spec, pairs, fetched_at, "recent-valid", spec.source)


def _fetch_investing_bond_yield(spec: MetricSpec, fetched_at: datetime) -> MarketMetric:
    url, symbol = INVESTING_RATE_SOURCES[spec.key]
    text = _read_text(url, timeout=15, attempts=2, headers=INVESTING_HTTP_HEADERS)
    value = _extract_html_number(text, r'data-test="instrument-price-last"[^>]*>([^<]+)')
    change = _extract_html_number(text, r'data-test="instrument-price-change"[^>]*>([^<]+)')
    update_ms = _extract_html_number(text, r'"lastUpdateTime"\s*:\s*"(\d+)"', required=False)
    if value is None:
        raise ValueError(f"{symbol} returned no market yield")
    as_of = _safe_today()
    if update_ms is not None:
        as_of = datetime.fromtimestamp(update_ms / 1000, timezone.utc).date()
    previous = value - change if change is not None else None
    return MarketMetric(
        key=spec.key,
        label=spec.label,
        description=spec.description,
        symbol=symbol,
        source="Investing market quote",
        value=value,
        previous_value=previous,
        as_of=as_of,
        fetched_at=fetched_at,
        unit=spec.unit,
        category=spec.category,
        status="ok",
        warnings=(),
        delayed=True,
        importance=spec.importance,
        freshness="live",
        live_source="Investing",
    )


def _fetch_naaim_exposure_live(spec: MetricSpec, fetched_at: datetime) -> MarketMetric:
    url = "https://naaim.org/programs/naaim-exposure-index/"
    text = _read_text(url, timeout=20, attempts=2, headers=NAAIM_HTTP_HEADERS)
    pairs = _extract_naaim_pairs(text)
    return _metric_from_pairs(spec, pairs, fetched_at, "recent-valid", spec.source)


def _extract_naaim_pairs(text: str) -> list[tuple[date, float]]:
    rows = re.findall(r"<tr[^>]*>\s*<td>(\d{2}/\d{2}/\d{4})</td>\s*<td>([-\d.]+)</td>", text, re.I)
    pairs: list[tuple[date, float]] = []
    for raw_date, raw_value in rows:
        try:
            day = datetime.strptime(raw_date, "%m/%d/%Y").date()
            value = float(raw_value)
        except ValueError:
            continue
        if math.isfinite(value):
            pairs.append((day, value))
    if pairs:
        return sorted(dict(pairs).items(), key=lambda item: item[0])

    value = _extract_html_number(
        text,
        r"This week(?:&#8217;|['’])s NAAIM Exposure Index number is\*:</h4>\s*<div[^>]*>([-\d.]+)</div>",
    )
    posted = re.search(r"\*Posted on [^,]+,\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text, re.I)
    if posted:
        day = datetime.strptime(posted.group(1), "%B %d, %Y").date()
    else:
        day = _safe_today()
    return [(day, value)]


def _extract_cnn_fear_greed_pairs(payload: dict[str, Any]) -> list[tuple[date, float]]:
    historical = payload.get("fear_and_greed_historical", {})
    rows = historical.get("data", []) if isinstance(historical, dict) else []
    pairs: list[tuple[date, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("x") or row.get("date") or row.get("timestamp")
        raw_value = row.get("y") or row.get("score") or row.get("value")
        parsed_date = _parse_cnn_date(raw_date)
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if parsed_date is not None and math.isfinite(value):
            pairs.append((parsed_date, value))

    current = payload.get("fear_and_greed", {})
    if isinstance(current, dict):
        raw_value = current.get("score") or current.get("value")
        raw_date = current.get("timestamp") or current.get("date") or current.get("asOf")
        parsed_date = _parse_cnn_date(raw_date) or _safe_today()
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = float("nan")
        if math.isfinite(value):
            pairs.append((parsed_date, value))

    dedup: dict[date, float] = {}
    for day, value in pairs:
        dedup[day] = value
    return sorted(dedup.items(), key=lambda item: item[0])


def _parse_cnn_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        timestamp = float(raw)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, timezone.utc).date()
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            if text.isdigit():
                return _parse_cnn_date(float(text))
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def _apply_critical_fallbacks(
    metrics: dict[str, MarketMetric],
    fetched_at: datetime,
    cache: dict[str, Any],
    warnings: list[str],
) -> None:
    ten_year = metrics.get("treasury_10y")
    if ten_year is None or ten_year.status != "ok":
        fallback = _fetch_alpha_treasury("10year", "treasury_10y", "美国10年期收益率", fetched_at, cache)
        if fallback.status != "ok":
            fallback = _fetch_yahoo_treasury("^TNX", "treasury_10y", "美国10年期收益率", fetched_at, cache)
        metrics["treasury_10y"] = fallback
        warnings.extend(fallback.warnings)

    two_year = metrics.get("treasury_2y")
    if two_year is None or two_year.status != "ok":
        fallback = _fetch_alpha_treasury("2year", "treasury_2y", "美国2年期收益率", fetched_at, cache)
        if fallback.status != "ok":
            fallback = _fetch_yahoo_treasury("^UST2Y", "treasury_2y", "美国2年期收益率", fetched_at, cache)
        metrics["treasury_2y"] = fallback
        warnings.extend(fallback.warnings)


def _apply_market_rate_overrides(
    metrics: dict[str, MarketMetric],
    fetched_at: datetime,
    cache: dict[str, Any],
    warnings: list[str],
) -> None:
    for key in ("treasury_2y", "treasury_10y"):
        current = metrics.get(key)
        spec = next(item for item in FRED_SPECS if item.key == key)
        try:
            market_quote = _validate_metric(_fetch_investing_bond_yield(spec, fetched_at), spec)
        except Exception as exc:
            if current is None or current.status != "ok":
                market_quote = _cache_or_failed(spec, fetched_at, cache, f"Investing市场报价获取失败：{type(exc).__name__}")
                metrics[key] = market_quote
                warnings.extend(market_quote.warnings)
            continue
        if current and current.value is not None and abs(market_quote.value - current.value) >= 0.05:
            market_quote = _replace_warnings(
                market_quote,
                [
                    *market_quote.warnings,
                    f"{spec.label}市场报价与FRED官方日度值相差{abs(market_quote.value - current.value) * 100:.0f}bp；dashboard优先采用市场报价，FRED用于口径校验。",
                ],
            )
            warnings.extend(market_quote.warnings)
        metrics[key] = market_quote
        _write_cache_entry(cache, market_quote)


def _derive_missing_metrics(
    metrics: dict[str, MarketMetric],
    fetched_at: datetime,
    cache: dict[str, Any],
    warnings: list[str],
) -> None:
    ten_year = metrics.get("treasury_10y")
    inflation = metrics.get("inflation_expectation_10y")
    real_yield = metrics.get("real_yield_10y")
    if _ok(ten_year) and _ok(inflation):
        assert ten_year and inflation and ten_year.value is not None and inflation.value is not None
        previous = None
        if ten_year.previous_value is not None and inflation.previous_value is not None:
            previous = ten_year.previous_value - inflation.previous_value
        derived = MarketMetric(
            key="real_yield_10y",
            label="10年期实际利率（市场近似）",
            description="用市场10年期收益率减10年盈亏平衡通胀率估算，反映实时贴现率约束",
            symbol=f"{ten_year.symbol}-T10YIE",
            source="derived",
            value=ten_year.value - inflation.value,
            previous_value=previous,
            as_of=min(ten_year.as_of or _safe_today(), inflation.as_of or _safe_today()),
            fetched_at=fetched_at,
            unit="%",
            category="利率",
            status="ok",
            warnings=("实际利率使用市场10Y收益率减FRED 10Y breakeven近似估算；混合源用于提升实时性，非TIPS直接报价。",),
            importance="auxiliary",
            freshness="derived",
            live_source="derived",
        )
        metrics["real_yield_10y"] = derived
        _write_cache_entry(cache, derived)
        warnings.extend(derived.warnings)

    if _ok(metrics.get("treasury_2y")) and _ok(metrics.get("treasury_10y")):
        metrics["curve_2s10s"] = _build_curve_metric(metrics["treasury_2y"], metrics["treasury_10y"], fetched_at)


def _fetch_yahoo_treasury(
    symbol: str,
    key: str,
    label: str,
    fetched_at: datetime,
    cache: dict[str, Any],
) -> MarketMetric:
    spec = MetricSpec(
        key,
        label,
        "关键利率备用市场源",
        symbol,
        "Yahoo fallback",
        "利率",
        "%",
        min_value=0.5 if key == "treasury_2y" else 1,
        max_value=8,
        required=True,
        stale_days=5,
        cache_days=10,
    )
    metric = _fetch_with_cache(spec, fetched_at, cache, _fetch_yahoo_live)
    if metric.value is not None and metric.value > 20:
        metric = _scale_metric(metric, 0.1)
    if metric.status == "ok":
        metric = _replace_warnings(metric, [*metric.warnings, f"FRED主源不可用，{label}使用{symbol}备用源；系统已显式标注fallback。"])
        _write_cache_entry(cache, metric)
    return metric


def _fetch_alpha_treasury(
    maturity: str,
    key: str,
    label: str,
    fetched_at: datetime,
    cache: dict[str, Any],
) -> MarketMetric:
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    spec = MetricSpec(
        key,
        label,
        "Alpha Vantage Treasury Yield备用源",
        f"AV:TREASURY_YIELD:{maturity}",
        "Alpha Vantage fallback",
        "利率",
        "%",
        min_value=0.5 if key == "treasury_2y" else 1,
        max_value=8,
        required=True,
        stale_days=7,
        cache_days=14,
    )
    if not api_key:
        return _cache_or_failed(spec, fetched_at, cache, "未配置ALPHAVANTAGE_API_KEY，跳过Alpha Vantage Treasury Yield备用源。")

    def fetcher(local_spec: MetricSpec, now: datetime) -> MarketMetric:
        url = (
            "https://www.alphavantage.co/query"
            f"?function=TREASURY_YIELD&interval=daily&maturity={urllib.parse.quote(maturity)}"
            f"&apikey={urllib.parse.quote(api_key)}"
        )
        payload = _read_json(url, timeout=15)
        rows = payload.get("data", [])
        pairs: list[tuple[date, float]] = []
        for row in rows:
            raw_value = row.get("value")
            if raw_value in (None, "", "."):
                continue
            try:
                pairs.append((date.fromisoformat(row["date"]), float(raw_value)))
            except (KeyError, ValueError):
                continue
        pairs.sort(key=lambda item: item[0])
        return _metric_from_pairs(local_spec, pairs, now, "recent-valid", "Alpha Vantage")

    metric = _fetch_with_cache(spec, fetched_at, cache, fetcher)
    if metric.status == "ok":
        metric = _replace_warnings(metric, [*metric.warnings, f"FRED主源不可用，{label}使用Alpha Vantage Treasury Yield备用源。"])
        _write_cache_entry(cache, metric)
    return metric


def _metric_from_pairs(
    spec: MetricSpec,
    pairs: list[tuple[date, float]],
    fetched_at: datetime,
    freshness: str,
    live_source: str,
) -> MarketMetric:
    if not pairs:
        raise ValueError(f"{spec.symbol} returned no valid observations")
    as_of, value = pairs[-1]
    previous = pairs[-2][1] if len(pairs) >= 2 else None
    return MarketMetric(
        key=spec.key,
        label=spec.label,
        description=spec.description,
        symbol=spec.symbol,
        source=spec.source,
        value=value,
        previous_value=previous,
        as_of=as_of,
        fetched_at=fetched_at,
        unit=spec.unit,
        category=spec.category,
        status="ok",
        warnings=(),
        delayed=True,
        importance=spec.importance,
        freshness=freshness,
        live_source=live_source,
    )


def _validate_metric(metric: MarketMetric, spec: MetricSpec) -> MarketMetric:
    warnings: list[str] = list(metric.warnings)
    status = metric.status
    freshness = metric.freshness
    if metric.value is None:
        return metric
    if not _in_range(metric.value, spec.min_value, spec.max_value):
        status = "suspicious"
        warnings.append(f"{spec.label}数值{_fmt_plain(metric.value, spec.unit)}超出合理区间，已标记为可疑数据。")
    if spec.key in {"treasury_2y", "treasury_10y"} and metric.value < 1:
        status = "suspicious"
        warnings.append(f"{spec.label}低于1%，与2026年利率环境不匹配，需核验是否存在小数点移位。")
    if (
        status == "ok"
        and freshness == "live"
        and spec.source == "Yahoo"
        and metric.as_of is not None
        and _is_yahoo_live_quote_unexpectedly_old(metric.as_of, _safe_today())
    ):
        status = "stale"
        freshness = "stale"
        warnings.append(
            f"{spec.label}Yahoo行情最近有效值为{metric.as_of.isoformat()}，"
            "未覆盖当前可接受交易日窗口，已标记为非实时。"
        )
    elif status == "ok" and freshness == "live" and spec.source == "Yahoo" and metric.as_of is not None:
        if metric.as_of < _safe_today():
            freshness = "recent-valid"
    if metric.as_of is not None and (_safe_today() - metric.as_of).days > spec.stale_days:
        if status == "ok":
            status = "stale"
            freshness = "stale"
        warnings.append(f"{spec.label}最近有效值为{metric.as_of.isoformat()}，超出常规新鲜度窗口。")
    return _replace_metric(metric, status=status, warnings=tuple(dict.fromkeys(warnings)), freshness=freshness)


def _is_yahoo_live_quote_unexpectedly_old(as_of: date, today: date) -> bool:
    age_days = (today - as_of).days
    if age_days <= 1:
        return False
    # Friday close is still the latest normal quote through the weekend and early Monday.
    if today.weekday() == 6 and age_days <= 2:
        return False
    if today.weekday() == 0 and age_days <= 3:
        return False
    return True


def _metric_from_cache(
    spec: MetricSpec,
    fetched_at: datetime,
    cache: dict[str, Any],
    error: str,
) -> MarketMetric | None:
    entry = cache.get(spec.key)
    if not entry:
        return None
    try:
        as_of = date.fromisoformat(entry["observation_date"]) if entry.get("observation_date") else None
        cache_fetched = datetime.fromisoformat(entry["fetch_timestamp"])
        value = float(entry["value"]) if entry.get("value") is not None else None
        previous = float(entry["previous_value"]) if entry.get("previous_value") is not None else None
    except (KeyError, TypeError, ValueError):
        return None
    if as_of is None or (_safe_today() - as_of).days > spec.cache_days:
        return None
    warnings = (
        f"{spec.label}实时源失败，使用本地缓存；最近有效值：{as_of.isoformat()}，缓存抓取时间：{cache_fetched.isoformat(timespec='seconds')}。",
    )
    return MarketMetric(
        key=spec.key,
        label=spec.label,
        description=spec.description,
        symbol=entry.get("symbol", spec.symbol),
        source=f"{entry.get('source', spec.source)} cache",
        value=value,
        previous_value=previous,
        as_of=as_of,
        fetched_at=fetched_at,
        unit=entry.get("unit", spec.unit),
        category=spec.category,
        status="ok",
        warnings=warnings,
        delayed=True,
        importance=spec.importance,
        freshness="cache",
        live_source=entry.get("source", spec.source),
        fetch_error=error,
    )


def _recent_cache_metric(spec: MetricSpec, fetched_at: datetime, cache: dict[str, Any]) -> MarketMetric | None:
    entry = cache.get(spec.key)
    if not entry:
        return None
    try:
        cache_fetched = datetime.fromisoformat(entry["fetch_timestamp"])
    except (KeyError, TypeError, ValueError):
        return None
    if cache_fetched.tzinfo is None:
        cache_fetched = cache_fetched.replace(tzinfo=timezone.utc)
    if fetched_at - cache_fetched > timedelta(hours=12):
        return None
    return _metric_from_cache(spec, fetched_at, cache, "12小时内已有新鲜缓存，本次跳过重复实时请求。")


def _write_cache_entry(cache: dict[str, Any], metric: MarketMetric) -> None:
    if metric.value is None or metric.status != "ok":
        return
    cache[metric.key] = {
        "ticker": metric.symbol,
        "series_id": metric.symbol,
        "key": metric.key,
        "label": metric.label,
        "value": metric.value,
        "previous_value": metric.previous_value,
        "change": metric.change,
        "percent_change": metric.change_pct,
        "source": metric.live_source or metric.source,
        "unit": metric.unit,
        "observation_date": metric.as_of.isoformat() if metric.as_of else None,
        "fetch_timestamp": metric.fetched_at.isoformat(timespec="seconds"),
    }


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _recent_provider_failure(cache: dict[str, Any], provider: str, fetched_at: datetime) -> bool:
    raw = cache.get("_provider_failures", {}).get(provider)
    if not raw:
        return False
    try:
        failed_at = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if failed_at.tzinfo is None:
        failed_at = failed_at.replace(tzinfo=timezone.utc)
    return fetched_at - failed_at < timedelta(hours=6)


def _write_provider_failure(cache: dict[str, Any], provider: str, fetched_at: datetime) -> None:
    failures = cache.setdefault("_provider_failures", {})
    failures[provider] = fetched_at.isoformat(timespec="seconds")


def _build_curve_metric(two_year: MarketMetric, ten_year: MarketMetric, fetched_at: datetime) -> MarketMetric:
    assert two_year.value is not None and ten_year.value is not None
    previous = None
    if two_year.previous_value is not None and ten_year.previous_value is not None:
        previous = (ten_year.previous_value - two_year.previous_value) * 100
    value = (ten_year.value - two_year.value) * 100
    return MarketMetric(
        key="curve_2s10s",
        label="2s10s期限利差",
        description="10年期与2年期收益率之差，反映曲线形态与衰退定价",
        symbol="DGS10-DGS2",
        source="derived",
        value=value,
        previous_value=previous,
        as_of=min(two_year.as_of or _safe_today(), ten_year.as_of or _safe_today()),
        fetched_at=fetched_at,
        unit="bp",
        category="利率",
        status="ok",
        warnings=(),
        delayed=True,
        importance="auxiliary",
        freshness="derived",
        live_source="derived",
    )


def _failed_metric(spec: MetricSpec, fetched_at: datetime, warning: str) -> MarketMetric:
    if spec.importance == "auxiliary":
        warning = f"{spec.label}辅助数据暂不可用；dashboard将基于核心市场价格继续生成。"
    return MarketMetric(
        key=spec.key,
        label=spec.label,
        description=spec.description,
        symbol=spec.symbol,
        source=spec.source,
        value=None,
        previous_value=None,
        as_of=None,
        fetched_at=fetched_at,
        unit=spec.unit,
        category=spec.category,
        status="missing",
        warnings=(warning,),
        delayed=True,
        importance=spec.importance,
        freshness="missing",
    )


def _snapshot_warnings(metrics: dict[str, MarketMetric]) -> list[str]:
    warnings: list[str] = []
    core_missing = [m.label for m in metrics.values() if m.importance == "core" and m.status != "ok"]
    core_cached = [m.label for m in metrics.values() if m.importance == "core" and m.freshness == "cache"]
    aux_missing = [m.label for m in metrics.values() if m.importance == "auxiliary" and m.status != "ok"]
    if core_missing:
        warnings.append("核心指标缺失：" + "、".join(core_missing) + "；宏观判断置信度显著下调。")
    if core_cached:
        warnings.append("核心指标使用缓存：" + "、".join(core_cached) + "；报告已显式标注缓存状态。")
    if aux_missing:
        warnings.append(f"辅助数据暂不可用：{len(aux_missing)}项；流动性与信用条件解释基于可用市场价格推断。")
    return warnings


def _replace_warnings(metric: MarketMetric, warnings: list[str]) -> MarketMetric:
    return _replace_metric(metric, warnings=tuple(dict.fromkeys(warnings)))


def _replace_metric(
    metric: MarketMetric,
    *,
    status: str | None = None,
    warnings: tuple[str, ...] | None = None,
    freshness: str | None = None,
) -> MarketMetric:
    return MarketMetric(
        key=metric.key,
        label=metric.label,
        description=metric.description,
        symbol=metric.symbol,
        source=metric.source,
        value=metric.value,
        previous_value=metric.previous_value,
        as_of=metric.as_of,
        fetched_at=metric.fetched_at,
        unit=metric.unit,
        category=metric.category,
        status=status or metric.status,
        warnings=warnings if warnings is not None else metric.warnings,
        delayed=metric.delayed,
        importance=metric.importance,
        freshness=freshness or metric.freshness,
        live_source=metric.live_source,
        fetch_error=metric.fetch_error,
    )


def _scale_metric(metric: MarketMetric, scale: float) -> MarketMetric:
    value = metric.value * scale if metric.value is not None else None
    previous = metric.previous_value * scale if metric.previous_value is not None else None
    status = metric.status
    warnings = [w for w in metric.warnings if "超出合理区间" not in w and "低于1%" not in w]
    if status == "suspicious":
        status = "ok"
    if value is not None and not 1 <= value <= 8:
        status = "suspicious"
        warnings.append("Yahoo利率备用源口径换算后仍超出合理区间，需人工核验。")
    return MarketMetric(
        key=metric.key,
        label=metric.label,
        description=metric.description,
        symbol=metric.symbol,
        source=metric.source,
        value=value,
        previous_value=previous,
        as_of=metric.as_of,
        fetched_at=metric.fetched_at,
        unit=metric.unit,
        category=metric.category,
        status=status,
        warnings=tuple(dict.fromkeys(warnings)),
        delayed=metric.delayed,
        importance=metric.importance,
        freshness=metric.freshness,
        live_source=metric.live_source,
        fetch_error=metric.fetch_error,
    )


def _ok(metric: MarketMetric | None) -> bool:
    return metric is not None and metric.value is not None and metric.status == "ok"


def _in_range(value: float, minimum: float | None, maximum: float | None) -> bool:
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def _read_json(url: str, timeout: int = 15, headers: dict[str, str] | None = None) -> dict:
    return json.loads(_read_text(url, timeout=timeout, headers=headers))


def _read_text(url: str, timeout: int = 15, attempts: int = 3, headers: dict[str, str] | None = None) -> str:
    last_error: Exception | None = None
    request_headers = dict(DEFAULT_HTTP_HEADERS)
    if headers:
        request_headers.update(headers)
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(1.5 ** attempt)
    raise RuntimeError(str(last_error))


def _extract_html_number(text: str, pattern: str, required: bool = True) -> float | None:
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        if required:
            raise ValueError(f"Pattern not found: {pattern}")
        return None
    raw = match.group(1).strip().replace(",", "").replace("%", "").replace("(", "").replace(")", "")
    try:
        return float(raw)
    except ValueError:
        if required:
            raise
        return None


def _safe_today() -> date:
    return datetime.now(timezone.utc).date()


def _fmt_plain(value: float, unit: str = "") -> str:
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "bp":
        return f"{value:.0f}bp"
    return f"{value:.2f}"
