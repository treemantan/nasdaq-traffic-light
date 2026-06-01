from __future__ import annotations

import csv
import json
import math
import re
import statistics
import time
import urllib.parse
import urllib.request
from html import unescape
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ETF_CACHE_PATH = Path("output") / "cache" / "etf_monitor_cache.json"
ETF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
}
CROWDING_LOW_THRESHOLD = 35
CROWDING_ELEVATED_THRESHOLD = 70
CROWDING_HIGH_THRESHOLD = 80
CROWDING_BACKTEST_CEILING = CROWDING_ELEVATED_THRESHOLD
MARKET_ENV_SYMBOLS = {
    "spy": "SPY",
    "qqq": "QQQ",
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",
    "tnx": "^TNX",
    "gold": "GC=F",
    "oil": "CL=F",
}
_MARKET_ENV_HISTORY_CACHE: dict[str, list[tuple[date, float]]] | None = None


@dataclass(frozen=True)
class ETFPriceData:
    history: list[tuple[date, float]]
    volumes: list[tuple[date, float]]
    meta: dict[str, Any]


@dataclass(frozen=True)
class ETFHolding:
    symbol: str
    name: str
    weight: float


@dataclass(frozen=True)
class PortfolioPosition:
    symbol: str
    weight_pct: float
    quantity: float | None
    average_cost_gbp: float | None
    current_price_gbp: float | None
    market_value_gbp: float | None
    unrealized_pnl_gbp: float | None
    unrealized_pnl_pct: float | None
    day_change_pct: float | None
    monitor_status: str
    native_currency: str = ""
    current_price_native: float | None = None
    market_value_native: float | None = None
    fx_pair: str = ""
    fx_rate: float | None = None
    fx_as_of: str = ""
    price_source: str = ""
    year_peak_price_native: float | None = None
    year_peak_date: str = ""
    drawdown_from_year_peak_pct: float | None = None
    peak_watch: str = ""


@dataclass(frozen=True)
class PortfolioExposure:
    symbol: str
    label: str
    weight_pct: float
    direct_weight_pct: float
    etf_weight_pct: float


@dataclass(frozen=True)
class ETFSensitivity:
    factor: str
    label: str
    correlation: float | None
    beta: float | None
    beta_unit: str


@dataclass(frozen=True)
class ETFSimilarSample:
    as_of: str
    distance: float
    forward_1m: float
    forward_3m: float
    forward_6m: float
    drawdown_3m: float
    phase_id: str = ""
    phase_representative: bool = False
    tail_case: bool = False
    start_state: str = ""
    driver_notes: tuple[str, ...] = ()
    feature_coverage_pct: float | None = None


@dataclass(frozen=True)
class ETFSpec:
    key: str
    label: str
    symbol: str
    theme: str
    provider: str
    currency: str = "GBP"
    equity_like: bool = True
    ter: float | None = None


@dataclass(frozen=True)
class ETFThresholdCalibration:
    threshold: int
    crowding_ceiling: int
    label: str
    sample_count: int
    coverage_pct: float | None
    forward_1m: float | None
    forward_3m: float | None
    forward_6m: float | None
    hit_rate_3m: float | None
    max_drawdown_3m: float | None
    edge_3m: float | None
    edge_6m: float | None
    score: float | None
    supported: bool


@dataclass(frozen=True)
class ETFBacktestStats:
    threshold: int
    crowding_ceiling: int
    sample_size: int
    good_count: int
    coverage_pct: float | None
    good_forward_1m: float | None
    all_forward_1m: float | None
    good_forward_3m: float | None
    all_forward_3m: float | None
    good_forward_6m: float | None
    all_forward_6m: float | None
    good_hit_rate_3m: float | None
    all_hit_rate_3m: float | None
    good_max_drawdown_3m: float | None
    all_max_drawdown_3m: float | None
    reliability: str
    summary: str
    similar_count: int = 0
    similar_phase_count: int = 0
    similar_tail_phase_count: int = 0
    similar_tail_phase_rate: float | None = None
    similar_closest_tail_distance: float | None = None
    similar_avg_feature_coverage_pct: float | None = None
    similarity_confidence: str = "历史可比性待确认"
    similar_avg_score: float | None = None
    similar_avg_distance: float | None = None
    similar_forward_1m: float | None = None
    similar_forward_3m: float | None = None
    similar_forward_6m: float | None = None
    similar_hit_rate_3m: float | None = None
    similar_max_drawdown_3m: float | None = None
    similar_forward_3m_p25: float | None = None
    similar_forward_3m_p50: float | None = None
    similar_forward_3m_p75: float | None = None
    similar_samples: tuple[ETFSimilarSample, ...] = ()
    threshold_calibrations: tuple[ETFThresholdCalibration, ...] = ()
    best_threshold: int | None = None
    best_threshold_label: str = "未发现稳定阈值优势"


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
    ter: float | None = None
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
    valuation_as_of: str = ""
    pe_percentile: float | None = None
    pb_percentile: float | None = None
    pe_high_1y: float | None = None
    pe_high_1y_ratio: float | None = None
    aum: float | None = None
    avg_volume_20d: float | None = None
    avg_traded_value_20d: float | None = None
    bid_ask_spread_pct: float | None = None
    liquidity_label: str = "流动性待确认"
    liquidity_note: str = "成交量、规模或价差数据不足。"
    liquidity_source: str = "unavailable"
    holdings: tuple[ETFHolding, ...] = ()
    holdings_count: int | None = None
    top10_weight: float | None = None
    metadata_status: str = "待确认"
    metadata_note: str = "尚未完成 ticker 元数据审计。"
    sensitivities: tuple[ETFSensitivity, ...] = ()
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
    backtest: ETFBacktestStats | None = None
    source: str = "Yahoo"
    status: str = "ok"
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ETFMonitor:
    summary: str
    assets: list[ETFAssetMonitor]
    warnings: list[str]
    change_summary: list[str] = field(default_factory=list)
    portfolio_summary: list[str] = field(default_factory=list)
    portfolio_warnings: list[str] = field(default_factory=list)
    portfolio_positions: list[PortfolioPosition] = field(default_factory=list)
    portfolio_total_value_gbp: float | None = None
    portfolio_exposures: list[PortfolioExposure] = field(default_factory=list)
    portfolio_exposure_notes: list[str] = field(default_factory=list)


DEFAULT_ETF_SPECS = [
    ETFSpec("vwrl", "Vanguard FTSE All-World UCITS ETF", "VWRL.L", "Global Equity", "Vanguard", ter=0.22),
    ETFSpec("vuag", "Vanguard S&P 500 UCITS ETF", "VUAG.L", "S&P 500", "Vanguard", ter=0.07),
    ETFSpec("isf", "iShares Core FTSE 100 UCITS ETF", "ISF.L", "UK Large Cap", "iShares", ter=0.07),
    ETFSpec("cnx1", "iShares Nasdaq 100 UCITS ETF", "CNX1.L", "Nasdaq 100", "iShares", ter=0.33),
    ETFSpec("iitu", "iShares S&P 500 Information Technology Sector ETF", "IITU.L", "US Technology", "iShares", ter=0.15),
    ETFSpec("ainf", "iShares AI Infrastructure UCITS ETF", "AINF.L", "AI Infrastructure", "iShares", ter=0.35),
    ETFSpec("lazr", "L&G Optical Technology & Photonics ESG Exclusions UCITS ETF", "LAZR.L", "Optical Technology & Photonics", "L&G", currency="USD", ter=0.49),
    ETFSpec("wtai", "WisdomTree Artificial Intelligence ETF", "WTAI.L", "Artificial Intelligence", "WisdomTree", ter=0.40),
    ETFSpec("aiai", "L&G Artificial Intelligence UCITS ETF", "AIAI.L", "Artificial Intelligence", "L&G", ter=0.49),
    ETFSpec("semi", "iShares Global Semiconductors ETF", "SEMI.L", "Semiconductor", "iShares", ter=0.35),
    ETFSpec("smgb", "VanEck Semiconductor UCITS ETF", "SMGB.L", "Semiconductor", "VanEck", ter=0.35),
    ETFSpec("semg", "Amundi MSCI Semiconductors UCITS ETF", "SEMG.L", "Semiconductor", "Amundi", ter=0.35),
    ETFSpec("rbot", "iShares Automation & Robotics UCITS ETF", "RBOT.L", "Robotics & Automation", "iShares", ter=0.40),
    ETFSpec("wcld", "WisdomTree Cloud Computing UCITS ETF", "WCLD.L", "Cloud Software", "WisdomTree", ter=0.40),
    ETFSpec("lock", "iShares Digital Security UCITS ETF", "LOCK.L", "Cybersecurity", "iShares", ter=0.40),
    ETFSpec("qwtm", "WisdomTree Quantum Computing ETF", "QWTM.L", "Quantum Computing", "WisdomTree", ter=0.45),
    ETFSpec("qntm", "VanEck Quantum Computing ETF", "QNTM.L", "Quantum Computing", "VanEck", ter=0.55),
    ETFSpec("qant", "iShares Quantum Computing ETF", "QANT.L", "Quantum Computing", "iShares", ter=0.50),
    ETFSpec("cskr", "iShares MSCI Korea UCITS ETF", "CSKR.L", "South Korea Equity", "iShares", ter=0.65),
    ETFSpec("hkor", "HSBC MSCI Korea Capped UCITS ETF", "HKOR.L", "South Korea Equity", "HSBC", ter=0.50),
    ETFSpec("flrk", "Franklin FTSE Korea UCITS ETF", "FLRK.L", "South Korea Equity", "Franklin", ter=0.09),
    ETFSpec("igtm", "iShares $ Treasury Bond 7-10yr UCITS ETF GBP Hedged", "IGTM.L", "US Treasury 7-10Y GBP Hedged", "iShares", equity_like=False, ter=0.10),
    ETFSpec("dfnd", "iShares Global Aerospace & Defence UCITS ETF", "DFND.L", "Defence", "iShares", ter=0.35),
    ETFSpec("wdef", "WisdomTree Europe Defence UCITS ETF", "WDEF.L", "European Defence", "WisdomTree", ter=0.40),
    ETFSpec("dfng", "VanEck Defense UCITS ETF", "DFNG.L", "Defence", "VanEck", ter=0.55),
    ETFSpec("nato", "HANetf Future of Defence UCITS ETF", "NATO.L", "Defence", "HANetf", ter=0.49),
    ETFSpec("dfnx", "Invesco Defence Innovation UCITS ETF", "DFNX.L", "Defence Innovation", "Invesco", ter=0.35),
    ETFSpec("dfeu", "iShares Europe Defence UCITS ETF", "DFEU.L", "European Defence", "iShares", ter=0.35),
    ETFSpec("sgln", "iShares Physical Gold ETC", "SGLN.L", "Gold", "iShares", equity_like=False, ter=0.12),
    ETFSpec("phau", "WisdomTree Physical Gold", "PHAU.L", "Gold", "WisdomTree", equity_like=False, ter=0.39),
    ETFSpec("sgbx", "WisdomTree Physical Swiss Gold", "SGBX.L", "Gold", "WisdomTree", equity_like=False, ter=0.15),
]


VALUATION_PROXY_SYMBOLS = {
    "VWRL.L": ("VT", "StockAnalysis proxy: VT"),
    "VUAG.L": ("VOO", "StockAnalysis proxy: VOO"),
    "IITU.L": ("XLK", "StockAnalysis proxy: XLK"),
    "SEMI.L": ("SMH", "StockAnalysis proxy: SMH"),
    "SMGB.L": ("SMH", "StockAnalysis proxy: SMH"),
    "SEMG.L": ("SMH", "StockAnalysis proxy: SMH"),
    "QWTM.L": ("QTUM", "StockAnalysis proxy: QTUM"),
    "CSKR.L": ("EWY", "StockAnalysis proxy: EWY"),
    "HKOR.L": ("EWY", "StockAnalysis proxy: EWY"),
    "FLRK.L": ("EWY", "StockAnalysis proxy: EWY"),
    "DFND.L": ("ITA", "StockAnalysis proxy: ITA"),
    "DFNG.L": ("ITA", "StockAnalysis proxy: ITA"),
    "NATO.L": ("ITA", "StockAnalysis proxy: ITA"),
}

ISHARES_PORTFOLIO_VALUATION_URLS = {
    "ISF.L": "https://www.ishares.com/uk/professional/en/products/251795/ishares-core-ftse-100-ucits-etf/?siteEntryPassthrough=true",
    "CNX1.L": "https://www.ishares.com/uk/professional/en/products/253741/ishares-nasdaq-100-ucits-etf/?siteEntryPassthrough=true",
    "IITU.L": "https://www.ishares.com/uk/professional/en/products/280510/ishares-sp-500-information-technology-sector-ucits-etf/?siteEntryPassthrough=true",
    "SEMI.L": "https://www.ishares.com/uk/professional/en/products/319084/ishares-msci-global-semiconductors-ucits-etf/?siteEntryPassthrough=true",
    "RBOT.L": "https://www.ishares.com/uk/professional/en/products/284219/ishares-automation-robotics-ucits-etf/?siteEntryPassthrough=true",
    "LOCK.L": "https://www.ishares.com/uk/professional/en/products/297843/ishares-digital-security-ucits-etf/?siteEntryPassthrough=true",
    "CSKR.L": "https://www.ishares.com/uk/professional/en/products/253733/ishares-msci-korea-ucits-etf-acc-fund/?siteEntryPassthrough=true",
    "DFND.L": "https://www.ishares.com/uk/professional/en/products/334464/ishares-global-aerospace-defence-ucits-etf/?siteEntryPassthrough=true",
}


def fetch_etf_monitor(specs: list[ETFSpec] | None = None, macro_metrics: dict[str, Any] | None = None) -> ETFMonitor:
    fetched_at = datetime.now(timezone.utc)
    cache = _load_cache()
    previous_assets = dict(cache.get("assets") or {})
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
    portfolio_summary, portfolio_warnings, portfolio_positions, portfolio_total = _load_portfolio_summary(assets)
    portfolio_exposures, portfolio_exposure_notes = _portfolio_exposure_summary(assets, portfolio_positions)
    return ETFMonitor(
        summary=_build_summary(assets),
        assets=assets,
        warnings=list(dict.fromkeys(warnings)),
        change_summary=_build_change_summary(assets, previous_assets),
        portfolio_summary=portfolio_summary,
        portfolio_warnings=portfolio_warnings,
        portfolio_positions=portfolio_positions,
        portfolio_total_value_gbp=portfolio_total,
        portfolio_exposures=portfolio_exposures,
        portfolio_exposure_notes=portfolio_exposure_notes,
    )


def _fetch_etf_asset(
    spec: ETFSpec,
    fetched_at: datetime,
    cache: dict[str, Any],
    macro_metrics: dict[str, Any] | None = None,
) -> ETFAssetMonitor:
    price_data = _fetch_yahoo_price_data(spec.symbol)
    metadata_status, metadata_note = _audit_metadata(spec, price_data.meta)
    if metadata_status == "异常":
        raise ValueError(f"metadata audit failed: {metadata_note}")
    history = price_data.history
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
    valuations: dict[str, Any] = {}
    valuation_source = "unavailable"
    valuation_as_of = ""
    if spec.equity_like and spec.symbol.upper() in ISHARES_PORTFOLIO_VALUATION_URLS:
        try:
            valuations = _fetch_ishares_portfolio_valuation(spec.symbol)
            if _has_any_valuation(valuations):
                valuation_source = "iShares官方组合估值"
                valuation_as_of = str(valuations.get("asOf") or "")
        except Exception as exc:
            valuation_fetch_warning = f"iShares官方组合估值暂不可用：{type(exc).__name__}"
    try:
        yahoo_valuations = _fetch_yahoo_valuation(spec.symbol) if spec.equity_like else {}
        valuations = _merge_missing_valuations(valuations, yahoo_valuations)
    except Exception as exc:
        fallback_warning = f"Yahoo估值接口暂不可用：{type(exc).__name__}"
        valuation_fetch_warning = (
            f"{valuation_fetch_warning}; {fallback_warning}"
            if valuation_fetch_warning
            else fallback_warning
        )
    if valuation_source == "unavailable" and _has_any_valuation(valuations):
        valuation_source = "Yahoo"
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
    valuation_day = _parse_iso_date(valuation_as_of) or fetched_at.date()
    pe_percentile, pb_percentile, pe_high_1y, pe_high_1y_ratio = _update_valuation_history(
        cache, spec.key, valuation_day, pe, pb
    )
    warnings = _valuation_warnings(spec, pe, forward_pe, pb, pe_percentile, pe_high_1y_ratio)
    if valuation_fetch_warning:
        warnings.append(valuation_fetch_warning)
    liquidity = _fetch_liquidity_profile(spec, history, price_data.volumes)
    warnings.extend(liquidity["warnings"])
    asset = ETFAssetMonitor(
        key=spec.key,
        label=spec.label,
        symbol=spec.symbol,
        theme=spec.theme,
        provider=spec.provider,
        currency=_normalize_currency(price_data.meta.get("currency")) or spec.currency,
        value=value,
        previous_value=previous,
        as_of=history[-1][0],
        fetched_at=fetched_at,
        ter=spec.ter,
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
        valuation_as_of=valuation_as_of,
        pe_percentile=pe_percentile,
        pb_percentile=pb_percentile,
        pe_high_1y=pe_high_1y,
        pe_high_1y_ratio=pe_high_1y_ratio,
        aum=liquidity["aum"],
        avg_volume_20d=liquidity["avg_volume_20d"],
        avg_traded_value_20d=liquidity["avg_traded_value_20d"],
        bid_ask_spread_pct=liquidity["bid_ask_spread_pct"],
        liquidity_label=liquidity["label"],
        liquidity_note=liquidity["note"],
        liquidity_source=liquidity["source"],
        holdings=liquidity["holdings"],
        holdings_count=liquidity["holdings_count"],
        top10_weight=liquidity["top10_weight"],
        metadata_status=metadata_status,
        metadata_note=metadata_note,
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
    market_histories = _fetch_market_env_histories()
    enriched = _replace_asset(
        enriched,
        sensitivities=_rolling_sensitivities(history, market_histories),
        backtest=_backtest_entry_environment(spec, history, macro_metrics, market_histories),
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
    if "metadata audit failed" in reason:
        return ETFAssetMonitor(
            key=spec.key, label=spec.label, symbol=spec.symbol, theme=spec.theme, provider=spec.provider,
            currency=spec.currency, value=None, previous_value=None, as_of=None, fetched_at=fetched_at,
            ter=spec.ter, status="metadata-error", metadata_status="异常", metadata_note=reason,
            warnings=(f"{spec.label}（{spec.symbol}）ticker元数据审计失败，已停止纳入评分：{reason}",),
        )
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
        ter=spec.ter,
        status="missing",
        warnings=(f"{spec.label}（{spec.symbol}）ETF数据暂不可用：{reason}",),
    )


def _fetch_yahoo_history(symbol: str) -> list[tuple[date, float]]:
    return _fetch_yahoo_price_data(symbol).history


def _fetch_yahoo_price_data(symbol: str) -> ETFPriceData:
    encoded = urllib.parse.quote(symbol, safe="")
    urls = [
        f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded}?range=5y&interval=1d",
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5y&interval=1d",
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
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    closes = quote.get("close", [])
    raw_volumes = quote.get("volume", [])
    pairs: list[tuple[date, float]] = []
    volumes: list[tuple[date, float]] = []
    for index, timestamp in enumerate(timestamps):
        day = datetime.fromtimestamp(timestamp, timezone.utc).date()
        close = closes[index] if index < len(closes) else None
        volume = raw_volumes[index] if index < len(raw_volumes) else None
        value = _safe_float(close)
        vol = _safe_float(volume)
        if value is not None:
            pairs.append((day, value * scale))
        if vol is not None:
            volumes.append((day, vol))
    return ETFPriceData(history=pairs, volumes=volumes, meta=result.get("meta", {}))


def _fetch_market_env_histories() -> dict[str, list[tuple[date, float]]]:
    global _MARKET_ENV_HISTORY_CACHE
    if _MARKET_ENV_HISTORY_CACHE is not None:
        return _MARKET_ENV_HISTORY_CACHE
    histories: dict[str, list[tuple[date, float]]] = {}
    for key, symbol in MARKET_ENV_SYMBOLS.items():
        try:
            history = sorted(_fetch_yahoo_history(symbol), key=lambda item: item[0])
            if len(history) >= 260:
                histories[key] = history
        except Exception:
            continue
    _MARKET_ENV_HISTORY_CACHE = histories
    return histories


def _rolling_sensitivities(
    asset_history: list[tuple[date, float]],
    market_histories: dict[str, list[tuple[date, float]]],
    window: int = 60,
) -> tuple[ETFSensitivity, ...]:
    definitions = (
        ("qqq", "Nasdaq 100", "每1%变动"),
        ("dxy", "美元指数DXY", "每1%变动"),
        ("tnx", "美国10年期收益率", "每上行10bp"),
        ("gold", "黄金", "每1%变动"),
    )
    sensitivities = []
    for key, label, beta_unit in definitions:
        correlation, beta = _rolling_sensitivity(asset_history, market_histories.get(key) or [], key, window)
        sensitivities.append(ETFSensitivity(key, label, correlation, beta, beta_unit))
    return tuple(sensitivities)


def _rolling_sensitivity(
    asset_history: list[tuple[date, float]],
    factor_history: list[tuple[date, float]],
    factor_key: str,
    window: int,
) -> tuple[float | None, float | None]:
    asset = _daily_moves_by_date(asset_history, "return")
    factor_mode = "yield_10bp" if factor_key == "tnx" else "return"
    factor = _daily_moves_by_date(factor_history, factor_mode)
    shared_dates = sorted(set(asset) & set(factor))[-window:]
    if len(shared_dates) < 30:
        return None, None
    asset_moves = [asset[day] for day in shared_dates]
    factor_moves = [factor[day] for day in shared_dates]
    factor_variance = _variance(factor_moves)
    if factor_variance in (None, 0):
        return None, None
    covariance = _covariance(asset_moves, factor_moves)
    asset_std = math.sqrt(_variance(asset_moves) or 0)
    factor_std = math.sqrt(factor_variance)
    correlation = covariance / (asset_std * factor_std) if asset_std and factor_std else None
    return correlation, covariance / factor_variance


def _daily_moves_by_date(history: list[tuple[date, float]], mode: str) -> dict[date, float]:
    moves: dict[date, float] = {}
    for (previous_day, previous), (current_day, current) in zip(history, history[1:]):
        if previous in (None, 0):
            continue
        if mode == "yield_10bp":
            normalized_previous = previous / 10 if previous > 20 else previous
            normalized_current = current / 10 if current > 20 else current
            moves[current_day] = (normalized_current - normalized_previous) / 0.10
        else:
            moves[current_day] = (current / previous - 1) * 100
    return moves


def _covariance(left: list[float], right: list[float]) -> float:
    left_avg = sum(left) / len(left)
    right_avg = sum(right) / len(right)
    return sum((a - left_avg) * (b - right_avg) for a, b in zip(left, right)) / len(left)


def _variance(values: list[float]) -> float | None:
    if not values:
        return None
    average = sum(values) / len(values)
    return sum((value - average) ** 2 for value in values) / len(values)


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


def _fetch_ishares_portfolio_valuation(symbol: str) -> dict[str, Any]:
    url = ISHARES_PORTFOLIO_VALUATION_URLS.get(symbol.upper())
    if not url:
        return {}
    return _parse_ishares_portfolio_valuation(_read_text(url, timeout=15))


def _parse_ishares_portfolio_valuation(text: str) -> dict[str, Any]:
    plain = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>|<!--.*?-->", " ", text, flags=re.DOTALL))).strip()
    pe, pe_as_of = _extract_ishares_portfolio_ratio(plain, "P/E Ratio")
    pb, pb_as_of = _extract_ishares_portfolio_ratio(plain, "P/B Ratio")
    as_of = pb_as_of or pe_as_of
    return {
        "trailingPE": pe,
        "forwardPE": None,
        "priceToBook": pb,
        "asOf": as_of.isoformat() if as_of else "",
    }


def _extract_ishares_portfolio_ratio(text: str, label: str) -> tuple[float | None, date | None]:
    match = re.search(
        rf"{re.escape(label)}\s+as of\s+(\d{{1,2}}/[A-Za-z]+/\d{{4}})\s+(-?\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, None
    return _safe_float(match.group(2)), _parse_ishares_date(match.group(1))


def _parse_ishares_date(raw: str) -> date | None:
    for pattern in ("%d/%b/%Y", "%d/%B/%Y"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    return None


def _merge_missing_valuations(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key in ("trailingPE", "forwardPE", "priceToBook"):
        if _safe_float(merged.get(key)) is None and _safe_float(fallback.get(key)) is not None:
            merged[key] = fallback[key]
    return merged


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


def _fetch_liquidity_profile(
    spec: ETFSpec,
    history: list[tuple[date, float]],
    volumes: list[tuple[date, float]],
) -> dict[str, Any]:
    warnings: list[str] = []
    recent_prices = {day: close for day, close in history[-40:]}
    traded_values = [
        recent_prices[day] * volume
        for day, volume in volumes[-40:]
        if day in recent_prices and volume is not None and volume >= 0
    ]
    recent_volumes = [volume for _, volume in volumes[-20:] if volume is not None and volume >= 0]
    avg_volume_20d = sum(recent_volumes) / len(recent_volumes) if recent_volumes else None
    avg_traded_value_20d = sum(traded_values[-20:]) / len(traded_values[-20:]) if traded_values else None
    aum = None
    holdings: tuple[ETFHolding, ...] = ()
    holdings_count = None
    top10_weight = None
    aum_source = ""
    try:
        aum = _fetch_stockanalysis_assets(spec.symbol)
        aum_source = "StockAnalysis assets" if aum is not None else ""
    except Exception as exc:
        warnings.append(f"{spec.symbol} AUM暂不可用：{type(exc).__name__}")
    if spec.equity_like:
        try:
            holdings, holdings_count, top10_weight = _fetch_stockanalysis_holdings(spec.symbol)
        except Exception as exc:
            warnings.append(f"{spec.symbol} 持仓明细暂不可用：{type(exc).__name__}")
    source_parts = ["Yahoo volume"]
    if aum_source:
        source_parts.append(aum_source)
    label, note = _liquidity_assessment(aum, avg_volume_20d, avg_traded_value_20d, None)
    if spec.key == "lazr":
        label = f"观察型标的 · {label}"
        note += "；光通信主题基金规模较小，执行前需额外核对实时价差与盘口深度"
        warnings.append("LAZR.L 为小规模光通信主题ETF，仅作为产业链观察代理；执行前需核对实时价差与盘口深度。")
    return {
        "aum": aum,
        "avg_volume_20d": avg_volume_20d,
        "avg_traded_value_20d": avg_traded_value_20d,
        "bid_ask_spread_pct": None,
        "label": label,
        "note": note,
        "source": "; ".join(source_parts),
        "holdings": holdings,
        "holdings_count": holdings_count,
        "top10_weight": top10_weight,
        "warnings": warnings,
    }


def _fetch_stockanalysis_assets(symbol: str) -> float | None:
    ticker = symbol.upper()
    if ticker.endswith(".L"):
        ticker = ticker[:-2]
    if not ticker or not re.fullmatch(r"[A-Z0-9]+", ticker):
        return None
    text = _read_text(f"https://stockanalysis.com/quote/lon/{ticker}/", timeout=15)
    match = re.search(r">\s*Assets\s*</td>\s*<td[^>]*>\s*([^<]+)\s*</td>", text, re.IGNORECASE)
    if not match:
        return None
    return _parse_compact_number(match.group(1))


def _fetch_stockanalysis_holdings(symbol: str) -> tuple[tuple[ETFHolding, ...], int | None, float | None]:
    ticker = symbol.upper()
    if ticker.endswith(".L"):
        ticker = ticker[:-2]
    if not ticker or not re.fullmatch(r"[A-Z0-9]+", ticker):
        return (), None, None
    text = _read_text(f"https://stockanalysis.com/quote/lon/{ticker}/holdings/", timeout=15)
    holdings_count = _extract_html_number(text, "Total Holdings")
    top10_weight = _extract_html_number(text, "Top 10 Percentage")
    tbody = text[text.find("<tbody") : text.find("</tbody>")]
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.IGNORECASE | re.DOTALL)
    holdings: list[ETFHolding] = []
    for row in rows[:10]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.IGNORECASE | re.DOTALL)
        if len(cells) < 4:
            continue
        symbol_text = _strip_html(cells[1])
        name = _strip_html(cells[2])
        weight = _safe_float(_strip_html(cells[3]).replace("%", ""))
        if name and weight is not None:
            holdings.append(ETFHolding(symbol=symbol_text, name=name, weight=weight))
    return tuple(holdings), int(holdings_count) if holdings_count is not None else None, top10_weight


def _extract_html_number(text: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}\s*<div[^>]*>\s*([^<]+)", text, re.IGNORECASE)
    return _safe_float(match.group(1).replace("%", "").replace(",", "").strip()) if match else None


def _strip_html(text: str) -> str:
    return unescape(re.sub(r"<[^>]+>|<!--.*?-->", "", text, flags=re.DOTALL)).strip()


def _audit_metadata(spec: ETFSpec, meta: dict[str, Any]) -> tuple[str, str]:
    exchange = str(meta.get("exchangeName") or "")
    instrument = str(meta.get("instrumentType") or "")
    long_name = str(meta.get("longName") or meta.get("shortName") or "")
    problems = []
    if exchange != "LSE":
        problems.append(f"交易所为{exchange or '未知'}，预期LSE")
    if spec.equity_like and instrument != "ETF":
        problems.append(f"资产类型为{instrument or '未知'}，预期ETF")
    if spec.theme == "Semiconductor" and "semiconductor" not in long_name.lower():
        problems.append("基金名称未包含Semiconductor")
    if spec.theme == "South Korea Equity" and "korea" not in long_name.lower():
        problems.append("基金名称未包含Korea")
    if problems:
        return "异常", "；".join(problems)
    currency = _normalize_currency(meta.get("currency")) or "币种未知"
    return "已核验", f"{exchange} · {instrument or 'ETC'} · {currency} · {long_name}"


def _normalize_currency(raw: Any) -> str:
    currency = str(raw or "").strip()
    return "GBP" if currency == "GBp" else currency


def _parse_compact_number(raw: str) -> float | None:
    text = raw.replace(",", "").strip()
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([KMBT]?)", text, re.IGNORECASE)
    if not match:
        return None
    value = _safe_float(match.group(1))
    if value is None:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}
    return value * multiplier.get(match.group(2).upper(), 1)


def _format_money_short(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


def _format_shares(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


def _liquidity_assessment(
    aum: float | None,
    avg_volume_20d: float | None,
    avg_traded_value_20d: float | None,
    bid_ask_spread_pct: float | None,
) -> tuple[str, str]:
    if avg_traded_value_20d is None and aum is None:
        return "流动性待确认", "成交额和AUM暂缺；买卖价差免费数据源未稳定提供。"
    if avg_traded_value_20d is not None and avg_traded_value_20d >= 5_000_000 and (aum is None or aum >= 1_000_000_000):
        label = "规模与成交较好"
    elif avg_traded_value_20d is not None and avg_traded_value_20d >= 1_000_000:
        label = "流动性可用"
    elif avg_traded_value_20d is not None and avg_traded_value_20d < 250_000:
        label = "流动性偏弱"
    elif aum is not None and aum < 100_000_000:
        label = "规模偏小"
    else:
        label = "流动性中性"
    parts = []
    if avg_traded_value_20d is not None:
        parts.append(f"20日均成交额约{_format_money_short(avg_traded_value_20d)}")
    if avg_volume_20d is not None:
        parts.append(f"20日均成交量约{_format_shares(avg_volume_20d)}份")
    if aum is not None:
        parts.append(f"AUM约{_format_money_short(aum)}")
    spread = f"{bid_ask_spread_pct:.2f}%" if bid_ask_spread_pct is not None else "待确认"
    parts.append(f"买卖价差{spread}")
    return label, "；".join(parts)


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


def _parse_iso_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _write_asset_cache(cache: dict[str, Any], asset: ETFAssetMonitor) -> None:
    cache.setdefault("assets", {})[asset.key] = {
        "label": asset.label,
        "symbol": asset.symbol,
        "theme": asset.theme,
        "provider": asset.provider,
        "currency": asset.currency,
        "ter": asset.ter,
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
        "valuation_as_of": asset.valuation_as_of,
        "pe_percentile": asset.pe_percentile,
        "pb_percentile": asset.pb_percentile,
        "pe_high_1y": asset.pe_high_1y,
        "pe_high_1y_ratio": asset.pe_high_1y_ratio,
        "aum": asset.aum,
        "avg_volume_20d": asset.avg_volume_20d,
        "avg_traded_value_20d": asset.avg_traded_value_20d,
        "bid_ask_spread_pct": asset.bid_ask_spread_pct,
        "liquidity_label": asset.liquidity_label,
        "liquidity_note": asset.liquidity_note,
        "liquidity_source": asset.liquidity_source,
        "holdings": [holding.__dict__ for holding in asset.holdings],
        "holdings_count": asset.holdings_count,
        "top10_weight": asset.top10_weight,
        "metadata_status": asset.metadata_status,
        "metadata_note": asset.metadata_note,
        "sensitivities": [item.__dict__ for item in asset.sensitivities],
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
        "backtest": _backtest_to_cache(asset.backtest),
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
        ter=_safe_float(entry.get("ter")) if entry.get("ter") is not None else spec.ter,
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
        valuation_as_of=str(entry.get("valuation_as_of") or ""),
        pe_percentile=_safe_float(entry.get("pe_percentile")),
        pb_percentile=_safe_float(entry.get("pb_percentile")),
        pe_high_1y=_safe_float(entry.get("pe_high_1y")),
        pe_high_1y_ratio=_safe_float(entry.get("pe_high_1y_ratio")),
        aum=_safe_float(entry.get("aum")),
        avg_volume_20d=_safe_float(entry.get("avg_volume_20d")),
        avg_traded_value_20d=_safe_float(entry.get("avg_traded_value_20d")),
        bid_ask_spread_pct=_safe_float(entry.get("bid_ask_spread_pct")),
        liquidity_label=entry.get("liquidity_label") or "流动性待确认",
        liquidity_note=entry.get("liquidity_note") or "成交量、规模或价差数据不足。",
        liquidity_source=entry.get("liquidity_source") or "unavailable",
        holdings=tuple(
            ETFHolding(str(item.get("symbol") or ""), str(item.get("name") or ""), float(item.get("weight") or 0))
            for item in (entry.get("holdings") or [])
            if isinstance(item, dict)
        ),
        holdings_count=int(entry["holdings_count"]) if entry.get("holdings_count") is not None else None,
        top10_weight=_safe_float(entry.get("top10_weight")),
        metadata_status=entry.get("metadata_status") or "待确认",
        metadata_note=entry.get("metadata_note") or "尚未完成 ticker 元数据审计。",
        sensitivities=tuple(
            ETFSensitivity(
                str(item.get("factor") or ""),
                str(item.get("label") or ""),
                _safe_float(item.get("correlation")),
                _safe_float(item.get("beta")),
                str(item.get("beta_unit") or ""),
            )
            for item in (entry.get("sensitivities") or [])
            if isinstance(item, dict)
        ),
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
        backtest=_backtest_from_cache(entry.get("backtest")),
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


def _backtest_entry_environment(
    spec: ETFSpec,
    history: list[tuple[date, float]],
    macro_metrics: dict[str, Any] | None = None,
    market_histories: dict[str, list[tuple[date, float]]] | None = None,
    threshold: int = 60,
    crowding_ceiling: int = CROWDING_BACKTEST_CEILING,
) -> ETFBacktestStats:
    # Weekly sampling reduces overlapping forward windows and avoids overstating precision.
    if len(history) < 330:
        return _empty_backtest(threshold, "历史价格样本不足，暂不回测新增仓位环境。")

    records: list[dict[str, Any]] = []
    closes = [close for _, close in history]
    current_features = _entry_similarity_features(spec, history, None, market_histories)
    start = 252
    end = len(history) - 126
    for index in range(start, end, 5):
        window = history[: index + 1]
        snapshot = _historical_entry_snapshot(spec, window, None)
        features = _entry_similarity_features(spec, window, None, market_histories)
        if snapshot is None:
            continue
        score = int(snapshot["score"])
        crowding_score = int(snapshot["crowding_score"])
        current = closes[index]
        future_1m = _forward_return(closes, index, 21)
        future_3m = _forward_return(closes, index, 63)
        future_6m = _forward_return(closes, index, 126)
        drawdown_3m = _forward_max_drawdown(closes, index, 63)
        if future_1m is None or future_3m is None or future_6m is None or drawdown_3m is None or current in (None, 0):
            continue
        records.append(
            {
                "score": score,
                "as_of": history[index][0].isoformat(),
                "crowding_score": crowding_score,
                "forward_1m": future_1m,
                "forward_3m": future_3m,
                "forward_6m": future_6m,
                "drawdown_3m": drawdown_3m,
                "features": features,
            }
        )

    if len(records) < 25:
        return _empty_backtest(threshold, "可回测信号不足，暂不评价历史有效性。")

    good = _qualified_records(records, threshold, crowding_ceiling)
    similar = _similar_samples(records, current_features)
    similar_values = _similar_stats(similar)
    threshold_calibrations = _threshold_calibrations(records, crowding_ceiling)
    best_threshold, best_threshold_label = _best_threshold(threshold_calibrations)
    if len(good) < 8:
        return ETFBacktestStats(
            threshold=threshold,
            crowding_ceiling=crowding_ceiling,
            sample_size=len(records),
            good_count=len(good),
            coverage_pct=len(good) / len(records) * 100 if records else None,
            good_forward_1m=_avg([float(row["forward_1m"]) for row in good]),
            all_forward_1m=_avg([float(row["forward_1m"]) for row in records]),
            good_forward_3m=_avg([float(row["forward_3m"]) for row in good]),
            all_forward_3m=_avg([float(row["forward_3m"]) for row in records]),
            good_forward_6m=_avg([float(row["forward_6m"]) for row in good]),
            all_forward_6m=_avg([float(row["forward_6m"]) for row in records]),
            good_hit_rate_3m=_hit_rate([float(row["forward_3m"]) for row in good]),
            all_hit_rate_3m=_hit_rate([float(row["forward_3m"]) for row in records]),
            good_max_drawdown_3m=_avg([float(row["drawdown_3m"]) for row in good]),
            all_max_drawdown_3m=_avg([float(row["drawdown_3m"]) for row in records]),
            reliability="样本偏少",
            summary=f"过去可用周度样本中，分数≥{threshold}的信号较少，统计结论需谨慎。",
            similar_count=int(similar_values["count"]),
            similar_phase_count=int(similar_values["phase_count"]),
            similar_tail_phase_count=int(similar_values["tail_phase_count"]),
            similar_tail_phase_rate=similar_values["tail_phase_rate"],
            similar_closest_tail_distance=similar_values["closest_tail_distance"],
            similar_avg_feature_coverage_pct=similar_values["avg_feature_coverage_pct"],
            similarity_confidence=str(similar_values["similarity_confidence"]),
            similar_avg_score=similar_values["avg_score"],
            similar_avg_distance=similar_values["avg_distance"],
            similar_forward_1m=similar_values["forward_1m"],
            similar_forward_3m=similar_values["forward_3m"],
            similar_forward_6m=similar_values["forward_6m"],
            similar_hit_rate_3m=similar_values["hit_rate_3m"],
            similar_max_drawdown_3m=similar_values["max_drawdown_3m"],
            similar_forward_3m_p25=similar_values["forward_3m_p25"],
            similar_forward_3m_p50=similar_values["forward_3m_p50"],
            similar_forward_3m_p75=similar_values["forward_3m_p75"],
            similar_samples=similar_values["samples"],
            threshold_calibrations=threshold_calibrations,
            best_threshold=best_threshold,
            best_threshold_label=best_threshold_label,
        )

    good_3m = _avg([float(row["forward_3m"]) for row in good])
    all_3m = _avg([float(row["forward_3m"]) for row in records])
    good_dd = _avg([float(row["drawdown_3m"]) for row in good])
    all_dd = _avg([float(row["drawdown_3m"]) for row in records])
    edge = (good_3m or 0) - (all_3m or 0)
    dd_edge = (good_dd or 0) - (all_dd or 0)
    if len(records) >= 80 and edge > 1 and dd_edge >= -1:
        reliability = "历史支持"
        summary = f"过去周度样本显示，分数≥{threshold}后的3个月平均表现优于全样本，且回撤没有明显恶化。"
    elif edge > 0:
        reliability = "温和支持"
        summary = f"过去周度样本显示，分数≥{threshold}后表现略优于全样本，但优势不应过度外推。"
    else:
        reliability = "未验证优势"
        summary = f"过去周度样本未显示分数≥{threshold}相对全样本有稳定优势，当前分数应更多视为风险过滤。"

    return ETFBacktestStats(
        threshold=threshold,
        crowding_ceiling=crowding_ceiling,
        sample_size=len(records),
        good_count=len(good),
        coverage_pct=len(good) / len(records) * 100,
        good_forward_1m=_avg([float(row["forward_1m"]) for row in good]),
        all_forward_1m=_avg([float(row["forward_1m"]) for row in records]),
        good_forward_3m=good_3m,
        all_forward_3m=all_3m,
        good_forward_6m=_avg([float(row["forward_6m"]) for row in good]),
        all_forward_6m=_avg([float(row["forward_6m"]) for row in records]),
        good_hit_rate_3m=_hit_rate([float(row["forward_3m"]) for row in good]),
        all_hit_rate_3m=_hit_rate([float(row["forward_3m"]) for row in records]),
        good_max_drawdown_3m=good_dd,
        all_max_drawdown_3m=all_dd,
        reliability=reliability,
        summary=summary,
        similar_count=int(similar_values["count"]),
        similar_phase_count=int(similar_values["phase_count"]),
        similar_tail_phase_count=int(similar_values["tail_phase_count"]),
        similar_tail_phase_rate=similar_values["tail_phase_rate"],
        similar_closest_tail_distance=similar_values["closest_tail_distance"],
        similar_avg_feature_coverage_pct=similar_values["avg_feature_coverage_pct"],
        similarity_confidence=str(similar_values["similarity_confidence"]),
        similar_avg_score=similar_values["avg_score"],
        similar_avg_distance=similar_values["avg_distance"],
        similar_forward_1m=similar_values["forward_1m"],
        similar_forward_3m=similar_values["forward_3m"],
        similar_forward_6m=similar_values["forward_6m"],
        similar_hit_rate_3m=similar_values["hit_rate_3m"],
        similar_max_drawdown_3m=similar_values["max_drawdown_3m"],
        similar_forward_3m_p25=similar_values["forward_3m_p25"],
        similar_forward_3m_p50=similar_values["forward_3m_p50"],
        similar_forward_3m_p75=similar_values["forward_3m_p75"],
        similar_samples=similar_values["samples"],
        threshold_calibrations=threshold_calibrations,
        best_threshold=best_threshold,
        best_threshold_label=best_threshold_label,
    )


def _historical_entry_score(
    spec: ETFSpec,
    history: list[tuple[date, float]],
    macro_metrics: dict[str, Any] | None = None,
) -> int | None:
    snapshot = _historical_entry_snapshot(spec, history, macro_metrics)
    return int(snapshot["score"]) if snapshot is not None else None


def _historical_entry_snapshot(
    spec: ETFSpec,
    history: list[tuple[date, float]],
    macro_metrics: dict[str, Any] | None = None,
) -> dict[str, int] | None:
    if len(history) < 253:
        return None
    closes = [close for _, close in history]
    daily_returns = _daily_returns(closes)
    value = closes[-1]
    previous = closes[-2]
    daily_volatility = _rolling_std(daily_returns, 252)
    trend_volatility = _robust_trend_volatility(daily_returns)
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
        fetched_at=datetime.combine(history[-1][0], datetime.min.time(), timezone.utc),
        ter=spec.ter,
        change_pct=_pct_change(value, previous),
        daily_sigma=_sigma_move(_pct_change(value, previous), daily_volatility),
        daily_volatility=daily_volatility,
        trend_volatility=trend_volatility,
        momentum_5d=_momentum(closes, 5),
        momentum_1m=_momentum(closes, 21),
        momentum_3m=_momentum(closes, 63),
        sma13=_sma(closes, 13),
        sma50=_sma(closes, 50),
        sma200=_sma(closes, 200),
        rsi14=_rsi(closes, 14),
    )
    distance = _distance_to_sma(asset.value, asset.sma200)
    crowding_score = _crowding_score(asset.rsi14, distance, None, asset.momentum_1m)
    asset = _replace_asset(
        asset,
        distance_sma200=distance,
        trend_sigma_200d=_trend_sigma(distance, trend_volatility or daily_volatility, 200),
        crowding_score=crowding_score,
    )
    score, _, _, _ = _entry_quality(asset, macro_metrics)
    return {"score": score, "crowding_score": crowding_score}


def _entry_similarity_features(
    spec: ETFSpec,
    history: list[tuple[date, float]],
    macro_metrics: dict[str, Any] | None = None,
    market_histories: dict[str, list[tuple[date, float]]] | None = None,
) -> dict[str, float] | None:
    score = _historical_entry_score(spec, history, macro_metrics)
    if score is None or len(history) < 253:
        return None
    closes = [close for _, close in history]
    daily_returns = _daily_returns(closes)
    value = closes[-1]
    daily_volatility = _rolling_std(daily_returns, 252)
    trend_volatility = _robust_trend_volatility(daily_returns)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)
    distance_50 = _distance_to_sma(value, sma50)
    distance_200 = _distance_to_sma(value, sma200)
    trend_sigma = _trend_sigma(distance_200, trend_volatility or daily_volatility, 200)
    features = {
        "score": float(score),
        "rsi14": _rsi(closes, 14),
        "momentum_1m": _momentum(closes, 21),
        "momentum_3m": _momentum(closes, 63),
        "distance_sma50": distance_50,
        "distance_sma200": distance_200,
        "trend_sigma_200d": trend_sigma,
        "daily_volatility": daily_volatility,
        "crowding_score": _crowding_score(_rsi(closes, 14), distance_200, None, _momentum(closes, 21)),
    }
    features.update(_market_env_features(market_histories, history[-1][0]))
    clean = {key: value for key, value in features.items() if isinstance(value, (int, float)) and math.isfinite(value)}
    return clean or None


def _market_env_features(
    market_histories: dict[str, list[tuple[date, float]]] | None,
    as_of: date,
) -> dict[str, float]:
    if not market_histories:
        return {}
    features: dict[str, float] = {}
    for key, history in market_histories.items():
        index = _history_index_at_or_before(history, as_of)
        if index is None or index < 22:
            continue
        closes = [close for _, close in history[: index + 1]]
        value = closes[-1]
        if key == "vix":
            features["mkt_vix_level"] = value
            features["mkt_vix_5d"] = _momentum(closes, 5)
            features["mkt_vix_1m"] = _momentum(closes, 21)
        elif key == "tnx":
            features["mkt_10y_level"] = value
            features["mkt_10y_1m"] = _momentum(closes, 21)
        else:
            features[f"mkt_{key}_1m"] = _momentum(closes, 21)
            features[f"mkt_{key}_3m"] = _momentum(closes, 63)
        if key in {"spy", "qqq"} and len(closes) >= 200:
            features[f"mkt_{key}_distance_sma200"] = _distance_to_sma(value, _sma(closes, 200))
    return {key: value for key, value in features.items() if value is not None}


def _history_index_at_or_before(history: list[tuple[date, float]], as_of: date) -> int | None:
    dates = [item[0] for item in history]
    index = bisect_right(dates, as_of) - 1
    return index if index >= 0 else None


def _similar_samples(
    records: list[dict[str, Any]],
    current_features: dict[str, float] | None,
    top_n: int = 12,
) -> list[dict[str, Any]]:
    if not current_features:
        return []
    scales = _adaptive_feature_scales(records)
    scored: list[dict[str, Any]] = []
    for row in records:
        features = row.get("features")
        distance, coverage = _feature_distance_details(current_features, features, scales)
        if distance is None:
            continue
        if coverage < 65:
            continue
        item = dict(row)
        item["distance"] = distance
        item["feature_coverage_pct"] = coverage
        scored.append(item)
    scored.sort(key=lambda row: row["distance"])
    return scored[:top_n]


def _feature_distance(current: dict[str, float], past: Any) -> float | None:
    distance, _ = _feature_distance_details(current, past, FEATURE_SCALES)
    return distance


FEATURE_SCALES = {
    "score": 15.0,
    "rsi14": 15.0,
    "momentum_1m": 8.0,
    "momentum_3m": 15.0,
    "distance_sma50": 8.0,
    "distance_sma200": 18.0,
    "trend_sigma_200d": 1.5,
    "daily_volatility": 2.0,
    "crowding_score": 18.0,
    "mkt_spy_1m": 6.0,
    "mkt_spy_3m": 12.0,
    "mkt_spy_distance_sma200": 12.0,
    "mkt_qqq_1m": 8.0,
    "mkt_qqq_3m": 15.0,
    "mkt_qqq_distance_sma200": 15.0,
    "mkt_vix_level": 12.0,
    "mkt_vix_5d": 18.0,
    "mkt_vix_1m": 30.0,
    "mkt_dxy_1m": 3.0,
    "mkt_dxy_3m": 5.0,
    "mkt_10y_level": 8.0,
    "mkt_10y_1m": 8.0,
    "mkt_gold_1m": 6.0,
    "mkt_gold_3m": 10.0,
    "mkt_oil_1m": 8.0,
    "mkt_oil_3m": 14.0,
}

FEATURE_WEIGHTS = {
    "score": 1.2,
    "rsi14": 1.0,
    "momentum_1m": 1.0,
    "momentum_3m": 0.8,
    "distance_sma50": 0.8,
    "distance_sma200": 1.1,
    "trend_sigma_200d": 1.1,
    "daily_volatility": 0.7,
    "crowding_score": 1.0,
    "mkt_spy_1m": 1.1,
    "mkt_spy_3m": 0.8,
    "mkt_spy_distance_sma200": 0.8,
    "mkt_qqq_1m": 1.2,
    "mkt_qqq_3m": 0.9,
    "mkt_qqq_distance_sma200": 0.9,
    "mkt_vix_level": 1.2,
    "mkt_vix_5d": 1.3,
    "mkt_vix_1m": 1.0,
    "mkt_dxy_1m": 1.0,
    "mkt_dxy_3m": 0.8,
    "mkt_10y_level": 1.0,
    "mkt_10y_1m": 1.0,
    "mkt_gold_1m": 0.6,
    "mkt_gold_3m": 0.5,
    "mkt_oil_1m": 0.5,
    "mkt_oil_3m": 0.4,
}


def _adaptive_feature_scales(records: list[dict[str, Any]]) -> dict[str, float]:
    scales = dict(FEATURE_SCALES)
    for key, fallback in FEATURE_SCALES.items():
        values = [
            value
            for row in records
            if isinstance(row.get("features"), dict)
            for value in [_safe_float(row["features"].get(key))]
            if value is not None
        ]
        if len(values) < 20:
            continue
        median = statistics.median(values)
        mad = statistics.median(abs(value - median) for value in values) * 1.4826
        if mad > 0:
            scales[key] = min(max(mad, fallback * 0.5), fallback * 2)
    return scales


def _feature_distance_details(
    current: dict[str, float],
    past: Any,
    scales: dict[str, float],
) -> tuple[float | None, float]:
    if not isinstance(past, dict):
        return None, 0
    total = 0.0
    weight_sum = 0.0
    possible_weight = sum(FEATURE_WEIGHTS.get(key, 1.0) for key in scales if key in current)
    for key, scale in scales.items():
        if key not in current or key not in past:
            continue
        current_value = _safe_float(current.get(key))
        past_value = _safe_float(past.get(key))
        if current_value is None or past_value is None:
            continue
        weight = FEATURE_WEIGHTS.get(key, 1.0)
        total += weight * ((current_value - past_value) / scale) ** 2
        weight_sum += weight
    if weight_sum <= 0:
        return None, 0
    coverage = weight_sum / possible_weight * 100 if possible_weight else 0
    return math.sqrt(total / weight_sum), coverage


def _similar_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {
            "count": 0,
            "phase_count": 0,
            "tail_phase_count": 0,
            "tail_phase_rate": None,
            "closest_tail_distance": None,
            "avg_feature_coverage_pct": None,
            "similarity_confidence": "历史可比性不足",
            "avg_score": None,
            "avg_distance": None,
            "forward_1m": None,
            "forward_3m": None,
            "forward_6m": None,
            "hit_rate_3m": None,
            "max_drawdown_3m": None,
            "forward_3m_p25": None,
            "forward_3m_p50": None,
            "forward_3m_p75": None,
            "samples": (),
        }
    phase_rows = _cluster_similar_samples(samples)
    representatives = [item["representative"] for item in phase_rows]
    tail_representatives = [row for row in representatives if _is_tail_case(row)]
    phase_by_date = {
        str(row.get("as_of") or ""): (phase["phase_id"], row is phase["representative"])
        for phase in phase_rows
        for row in phase["rows"]
    }
    forward_3m = [float(row["forward_3m"]) for row in representatives]
    avg_coverage = _avg([float(row.get("feature_coverage_pct") or 0) for row in representatives])
    avg_distance = _avg([float(row["distance"]) for row in representatives])
    return {
        "count": len(samples),
        "phase_count": len(representatives),
        "tail_phase_count": len(tail_representatives),
        "tail_phase_rate": len(tail_representatives) / len(representatives) * 100 if representatives else None,
        "closest_tail_distance": min((float(row["distance"]) for row in tail_representatives), default=None),
        "avg_score": _avg([float(row["score"]) for row in representatives]),
        "avg_distance": avg_distance,
        "avg_feature_coverage_pct": avg_coverage,
        "similarity_confidence": _similarity_confidence(len(representatives), avg_distance, avg_coverage),
        "forward_1m": _avg([float(row["forward_1m"]) for row in representatives]),
        "forward_3m": _avg(forward_3m),
        "forward_6m": _avg([float(row["forward_6m"]) for row in representatives]),
        "hit_rate_3m": _hit_rate([float(row["forward_3m"]) for row in representatives]),
        "max_drawdown_3m": _avg([float(row["drawdown_3m"]) for row in representatives]),
        "forward_3m_p25": _percentile_value(forward_3m, 0.25),
        "forward_3m_p50": _percentile_value(forward_3m, 0.50),
        "forward_3m_p75": _percentile_value(forward_3m, 0.75),
        "samples": tuple(
            _similar_sample_from_row(
                row,
                phase_by_date.get(str(row.get("as_of") or ""), ("", False)),
            )
            for row in samples
        ),
    }


def _cluster_similar_samples(
    samples: list[dict[str, Any]],
    max_gap_days: int = 28,
    max_span_days: int = 63,
) -> list[dict[str, Any]]:
    ordered = sorted(samples, key=lambda row: str(row.get("as_of") or ""))
    phases: list[dict[str, Any]] = []
    for row in ordered:
        as_of = date.fromisoformat(str(row["as_of"]))
        if (
            not phases
            or as_of - phases[-1]["last_date"] > timedelta(days=max_gap_days)
            or as_of - phases[-1]["start_date"] > timedelta(days=max_span_days)
        ):
            phases.append({"rows": [row], "start_date": as_of, "last_date": as_of})
        else:
            phases[-1]["rows"].append(row)
            phases[-1]["last_date"] = as_of
    for index, phase in enumerate(phases, start=1):
        phase["phase_id"] = f"P{index}"
        phase["representative"] = min(phase["rows"], key=lambda row: float(row["distance"]))
    return phases


def _similar_sample_from_row(row: dict[str, Any], phase: tuple[str, bool]) -> ETFSimilarSample:
    tail_case = _is_tail_case(row)
    return ETFSimilarSample(
                as_of=str(row.get("as_of") or ""),
                distance=float(row["distance"]),
                forward_1m=float(row["forward_1m"]),
                forward_3m=float(row["forward_3m"]),
                forward_6m=float(row["forward_6m"]),
                drawdown_3m=float(row["drawdown_3m"]),
        phase_id=phase[0],
        phase_representative=phase[1],
        tail_case=tail_case,
        start_state=_tail_start_state(row) if tail_case else "",
        driver_notes=_historical_driver_notes(row) if tail_case else (),
        feature_coverage_pct=_safe_float(row.get("feature_coverage_pct")),
    )


def _similarity_confidence(phase_count: int, avg_distance: float | None, avg_coverage: float | None) -> str:
    if phase_count < 3 or avg_distance is None or avg_coverage is None:
        return "历史可比性偏低"
    if avg_coverage < 75 or avg_distance > 1.25:
        return "历史可比性偏低"
    if phase_count >= 5 and avg_coverage >= 90 and avg_distance <= 0.85:
        return "历史可比性较高"
    return "历史可比性中等"


def _is_tail_case(row: dict[str, Any]) -> bool:
    return (
        float(row.get("forward_3m") or 0) < 0
        or float(row.get("drawdown_3m") or 0) <= -5
        or all(float(row.get(key) or 0) < 0 for key in ("forward_1m", "forward_3m", "forward_6m"))
    )


def _tail_start_state(row: dict[str, Any]) -> str:
    features = row.get("features") or {}
    conditions = []
    if float(features.get("crowding_score") or 0) >= 70:
        conditions.append("拥挤度偏高")
    if float(features.get("rsi14") or 0) >= 70:
        conditions.append("RSI处于偏热区间")
    if float(features.get("mkt_qqq_distance_sma200") or 0) >= 10:
        conditions.append("Nasdaq 100相对长期均线拉伸")
    if float(features.get("mkt_vix_level") or 100) < 18:
        conditions.append("波动率尚未充分反映尾部风险")
    return "；".join(conditions) if conditions else "起点表面平稳，但后续路径显示其对新增冲击较为敏感"


def _historical_driver_notes(row: dict[str, Any]) -> tuple[str, ...]:
    start = date.fromisoformat(str(row["as_of"]))
    end = start + timedelta(days=180)
    events = (
        (
            date(2024, 12, 18),
            "2024-12-18",
            "Fed鹰派降息：FOMC下调2025年降息幅度预期，长端收益率上行，高估值资产重新定价。",
        ),
        (
            date(2025, 1, 27),
            "2025-01-27",
            "DeepSeek冲击：市场重新评估AI模型效率、芯片需求与AI基础设施资本开支的估值假设。",
        ),
        (
            date(2025, 3, 1),
            "2025-03起",
            "关税不确定性升温：通胀、供应链与增长预期受到扰动，风险偏好降温。",
        ),
    )
    matched = [f"{label}：{note}" for event, label, note in events if start <= event <= end]
    if not matched:
        matched.append("该窗口未匹配到内置历史事件标签；需结合当期新闻和宏观数据进一步复核。")
    matched.append("事件窗口重叠仅用于解释线索，不构成单一因果归因，也不代表当前环境会重复同一路径。")
    return tuple(matched)


def _percentile_value(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _threshold_calibrations(records: list[dict[str, Any]], crowding_ceiling: int) -> tuple[ETFThresholdCalibration, ...]:
    all_1m = _avg([float(row["forward_1m"]) for row in records])
    all_3m = _avg([float(row["forward_3m"]) for row in records])
    all_6m = _avg([float(row["forward_6m"]) for row in records])
    all_dd = _avg([float(row["drawdown_3m"]) for row in records])
    return tuple(
        _threshold_calibration(records, threshold, crowding_ceiling, all_1m, all_3m, all_6m, all_dd)
        for threshold in (60, 70, 75)
    )


def _threshold_calibration(
    records: list[dict[str, Any]],
    threshold: int,
    crowding_ceiling: int,
    all_1m: float | None,
    all_3m: float | None,
    all_6m: float | None,
    all_dd: float | None,
) -> ETFThresholdCalibration:
    selected = _qualified_records(records, threshold, crowding_ceiling)
    forward_1m = _avg([float(row["forward_1m"]) for row in selected])
    forward_3m = _avg([float(row["forward_3m"]) for row in selected])
    forward_6m = _avg([float(row["forward_6m"]) for row in selected])
    drawdown = _avg([float(row["drawdown_3m"]) for row in selected])
    edge_3m = _diff(forward_3m, all_3m)
    edge_6m = _diff(forward_6m, all_6m)
    dd_edge = _diff(drawdown, all_dd)
    hit_rate = _hit_rate([float(row["forward_3m"]) for row in selected])
    sample_count = len(selected)
    coverage = sample_count / len(records) * 100 if records else None
    min_samples = 20 if threshold < 75 else 12
    supported = (
        sample_count >= min_samples
        and edge_3m is not None
        and edge_6m is not None
        and edge_3m > 0.5
        and edge_6m > 0
        and (dd_edge is None or dd_edge >= -2)
    )
    score = None
    if edge_3m is not None and edge_6m is not None:
        score = edge_3m * 0.45 + edge_6m * 0.35 + (hit_rate or 0) * 0.03 + (dd_edge or 0) * 0.25
        if sample_count < min_samples:
            score -= 100
        if coverage is not None and coverage > 80:
            score -= 4
    return ETFThresholdCalibration(
        threshold=threshold,
        crowding_ceiling=crowding_ceiling,
        label=_threshold_label(threshold),
        sample_count=sample_count,
        coverage_pct=coverage,
        forward_1m=forward_1m,
        forward_3m=forward_3m,
        forward_6m=forward_6m,
        hit_rate_3m=hit_rate,
        max_drawdown_3m=drawdown,
        edge_3m=edge_3m,
        edge_6m=edge_6m,
        score=score,
        supported=supported,
    )


def _best_threshold(calibrations: tuple[ETFThresholdCalibration, ...]) -> tuple[int | None, str]:
    supported = [item for item in calibrations if item.supported and item.score is not None]
    if not supported:
        return None, "未发现稳定阈值优势"
    best = max(supported, key=lambda item: item.score or -999)
    return best.threshold, f"历史最优阈值：{best.threshold}且拥挤度<{best.crowding_ceiling}（{best.label}）"


def _qualified_records(records: list[dict[str, Any]], threshold: int, crowding_ceiling: int) -> list[dict[str, Any]]:
    return [
        row
        for row in records
        if int(row["score"]) >= threshold and int(row.get("crowding_score", 100)) < crowding_ceiling
    ]


def _threshold_label(threshold: int) -> str:
    if threshold >= 75:
        return "趋势结构较强，但需检查拥挤度"
    if threshold >= 70:
        return "环境较好"
    return "环境尚可"


def _diff(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _forward_return(closes: list[float], index: int, horizon: int) -> float | None:
    if index + horizon >= len(closes) or closes[index] == 0:
        return None
    return (closes[index + horizon] / closes[index] - 1) * 100


def _forward_max_drawdown(closes: list[float], index: int, horizon: int) -> float | None:
    if index + 1 >= len(closes):
        return None
    path = closes[index : min(len(closes), index + horizon + 1)]
    if not path:
        return None
    peak = path[0]
    max_drawdown = 0.0
    for value in path:
        peak = max(peak, value)
        if peak:
            max_drawdown = min(max_drawdown, (value / peak - 1) * 100)
    return max_drawdown


def _empty_backtest(threshold: int, summary: str) -> ETFBacktestStats:
    return ETFBacktestStats(
        threshold=threshold,
        crowding_ceiling=CROWDING_BACKTEST_CEILING,
        sample_size=0,
        good_count=0,
        coverage_pct=None,
        good_forward_1m=None,
        all_forward_1m=None,
        good_forward_3m=None,
        all_forward_3m=None,
        good_forward_6m=None,
        all_forward_6m=None,
        good_hit_rate_3m=None,
        all_hit_rate_3m=None,
        good_max_drawdown_3m=None,
        all_max_drawdown_3m=None,
        reliability="样本不足",
        summary=summary,
        best_threshold_label="未发现稳定阈值优势",
    )


def _backtest_to_cache(backtest: ETFBacktestStats | None) -> dict[str, Any] | None:
    if backtest is None:
        return None
    return {
        "threshold": backtest.threshold,
        "crowding_ceiling": backtest.crowding_ceiling,
        "sample_size": backtest.sample_size,
        "good_count": backtest.good_count,
        "coverage_pct": backtest.coverage_pct,
        "good_forward_1m": backtest.good_forward_1m,
        "all_forward_1m": backtest.all_forward_1m,
        "good_forward_3m": backtest.good_forward_3m,
        "all_forward_3m": backtest.all_forward_3m,
        "good_forward_6m": backtest.good_forward_6m,
        "all_forward_6m": backtest.all_forward_6m,
        "good_hit_rate_3m": backtest.good_hit_rate_3m,
        "all_hit_rate_3m": backtest.all_hit_rate_3m,
        "good_max_drawdown_3m": backtest.good_max_drawdown_3m,
        "all_max_drawdown_3m": backtest.all_max_drawdown_3m,
        "reliability": backtest.reliability,
        "summary": backtest.summary,
        "similar_count": backtest.similar_count,
        "similar_phase_count": backtest.similar_phase_count,
        "similar_tail_phase_count": backtest.similar_tail_phase_count,
        "similar_tail_phase_rate": backtest.similar_tail_phase_rate,
        "similar_closest_tail_distance": backtest.similar_closest_tail_distance,
        "similar_avg_feature_coverage_pct": backtest.similar_avg_feature_coverage_pct,
        "similarity_confidence": backtest.similarity_confidence,
        "similar_avg_score": backtest.similar_avg_score,
        "similar_avg_distance": backtest.similar_avg_distance,
        "similar_forward_1m": backtest.similar_forward_1m,
        "similar_forward_3m": backtest.similar_forward_3m,
        "similar_forward_6m": backtest.similar_forward_6m,
        "similar_hit_rate_3m": backtest.similar_hit_rate_3m,
        "similar_max_drawdown_3m": backtest.similar_max_drawdown_3m,
        "similar_forward_3m_p25": backtest.similar_forward_3m_p25,
        "similar_forward_3m_p50": backtest.similar_forward_3m_p50,
        "similar_forward_3m_p75": backtest.similar_forward_3m_p75,
        "similar_samples": [item.__dict__ for item in backtest.similar_samples],
        "threshold_calibrations": [_threshold_calibration_to_cache(item) for item in backtest.threshold_calibrations],
        "best_threshold": backtest.best_threshold,
        "best_threshold_label": backtest.best_threshold_label,
    }


def _backtest_from_cache(entry: Any) -> ETFBacktestStats | None:
    if not isinstance(entry, dict):
        return None
    try:
        return ETFBacktestStats(
            threshold=int(entry.get("threshold") or 60),
            crowding_ceiling=int(entry.get("crowding_ceiling") or CROWDING_BACKTEST_CEILING),
            sample_size=int(entry.get("sample_size") or 0),
            good_count=int(entry.get("good_count") or 0),
            coverage_pct=_safe_float(entry.get("coverage_pct")),
            good_forward_1m=_safe_float(entry.get("good_forward_1m")),
            all_forward_1m=_safe_float(entry.get("all_forward_1m")),
            good_forward_3m=_safe_float(entry.get("good_forward_3m")),
            all_forward_3m=_safe_float(entry.get("all_forward_3m")),
            good_forward_6m=_safe_float(entry.get("good_forward_6m")),
            all_forward_6m=_safe_float(entry.get("all_forward_6m")),
            good_hit_rate_3m=_safe_float(entry.get("good_hit_rate_3m")),
            all_hit_rate_3m=_safe_float(entry.get("all_hit_rate_3m")),
            good_max_drawdown_3m=_safe_float(entry.get("good_max_drawdown_3m")),
            all_max_drawdown_3m=_safe_float(entry.get("all_max_drawdown_3m")),
            reliability=str(entry.get("reliability") or "样本不足"),
            summary=str(entry.get("summary") or "历史回测样本不足。"),
            similar_count=int(entry.get("similar_count") or 0),
            similar_phase_count=int(entry.get("similar_phase_count") or 0),
            similar_tail_phase_count=int(entry.get("similar_tail_phase_count") or 0),
            similar_tail_phase_rate=_safe_float(entry.get("similar_tail_phase_rate")),
            similar_closest_tail_distance=_safe_float(entry.get("similar_closest_tail_distance")),
            similar_avg_feature_coverage_pct=_safe_float(entry.get("similar_avg_feature_coverage_pct")),
            similarity_confidence=str(entry.get("similarity_confidence") or "历史可比性待确认"),
            similar_avg_score=_safe_float(entry.get("similar_avg_score")),
            similar_avg_distance=_safe_float(entry.get("similar_avg_distance")),
            similar_forward_1m=_safe_float(entry.get("similar_forward_1m")),
            similar_forward_3m=_safe_float(entry.get("similar_forward_3m")),
            similar_forward_6m=_safe_float(entry.get("similar_forward_6m")),
            similar_hit_rate_3m=_safe_float(entry.get("similar_hit_rate_3m")),
            similar_max_drawdown_3m=_safe_float(entry.get("similar_max_drawdown_3m")),
            similar_forward_3m_p25=_safe_float(entry.get("similar_forward_3m_p25")),
            similar_forward_3m_p50=_safe_float(entry.get("similar_forward_3m_p50")),
            similar_forward_3m_p75=_safe_float(entry.get("similar_forward_3m_p75")),
            similar_samples=tuple(
                ETFSimilarSample(
                    as_of=str(item.get("as_of") or ""),
                    distance=float(item.get("distance") or 0),
                    forward_1m=float(item.get("forward_1m") or 0),
                    forward_3m=float(item.get("forward_3m") or 0),
                    forward_6m=float(item.get("forward_6m") or 0),
                    drawdown_3m=float(item.get("drawdown_3m") or 0),
                    phase_id=str(item.get("phase_id") or ""),
                    phase_representative=bool(item.get("phase_representative")),
                    tail_case=bool(item.get("tail_case")),
                    start_state=str(item.get("start_state") or ""),
                    driver_notes=tuple(str(note) for note in (item.get("driver_notes") or [])),
                    feature_coverage_pct=_safe_float(item.get("feature_coverage_pct")),
                )
                for item in (entry.get("similar_samples") or [])
                if isinstance(item, dict)
            ),
            threshold_calibrations=tuple(
                item
                for item in (_threshold_calibration_from_cache(raw) for raw in entry.get("threshold_calibrations") or [])
                if item is not None
            ),
            best_threshold=int(entry["best_threshold"]) if entry.get("best_threshold") is not None else None,
            best_threshold_label=str(entry.get("best_threshold_label") or "未发现稳定阈值优势"),
        )
    except (TypeError, ValueError):
        return None


def _threshold_calibration_to_cache(item: ETFThresholdCalibration) -> dict[str, Any]:
    return {
        "threshold": item.threshold,
        "crowding_ceiling": item.crowding_ceiling,
        "label": item.label,
        "sample_count": item.sample_count,
        "coverage_pct": item.coverage_pct,
        "forward_1m": item.forward_1m,
        "forward_3m": item.forward_3m,
        "forward_6m": item.forward_6m,
        "hit_rate_3m": item.hit_rate_3m,
        "max_drawdown_3m": item.max_drawdown_3m,
        "edge_3m": item.edge_3m,
        "edge_6m": item.edge_6m,
        "score": item.score,
        "supported": item.supported,
    }


def _threshold_calibration_from_cache(entry: Any) -> ETFThresholdCalibration | None:
    if not isinstance(entry, dict):
        return None
    try:
        return ETFThresholdCalibration(
            threshold=int(entry.get("threshold") or 0),
            crowding_ceiling=int(entry.get("crowding_ceiling") or CROWDING_BACKTEST_CEILING),
            label=str(entry.get("label") or ""),
            sample_count=int(entry.get("sample_count") or 0),
            coverage_pct=_safe_float(entry.get("coverage_pct")),
            forward_1m=_safe_float(entry.get("forward_1m")),
            forward_3m=_safe_float(entry.get("forward_3m")),
            forward_6m=_safe_float(entry.get("forward_6m")),
            hit_rate_3m=_safe_float(entry.get("hit_rate_3m")),
            max_drawdown_3m=_safe_float(entry.get("max_drawdown_3m")),
            edge_3m=_safe_float(entry.get("edge_3m")),
            edge_6m=_safe_float(entry.get("edge_6m")),
            score=_safe_float(entry.get("score")),
            supported=bool(entry.get("supported")),
        )
    except (TypeError, ValueError):
        return None


def _avg(values: list[float]) -> float | None:
    clean = [value for value in values if math.isfinite(value)]
    return sum(clean) / len(clean) if clean else None


def _hit_rate(values: list[float]) -> float | None:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return None
    return sum(1 for value in clean if value > 0) / len(clean) * 100


def _build_summary(assets: list[ETFAssetMonitor]) -> str:
    live_assets = [asset for asset in assets if asset.value is not None]
    if not live_assets:
        return "ETF资产池暂缺实时数据，当前无法形成趋势与估值判断。"
    hot = [asset for asset in live_assets if asset.crowding_score >= CROWDING_ELEVATED_THRESHOLD]
    weak = [asset for asset in live_assets if asset.distance_sma200 is not None and asset.distance_sma200 < 0]
    strong = [asset for asset in live_assets if asset.distance_sma200 is not None and asset.distance_sma200 > 5]
    parts = [
        f"UK ETF资产池覆盖{len(live_assets)}只可跟踪产品（含观察型标的），用于观察趋势、估值重估与短线拥挤度。",
    ]
    if strong:
        parts.append("中长期趋势较强的资产包括：" + "、".join(asset.symbol for asset in strong[:4]) + "。")
    if hot:
        parts.append("短线拥挤度偏高的资产包括：" + "、".join(asset.symbol for asset in hot[:4]) + "，需关注RSI与均线乖离。")
    if weak:
        parts.append("低于200日线的资产包括：" + "、".join(asset.symbol for asset in weak[:4]) + "，趋势确认度较弱。")
    return " ".join(parts)


def _build_change_summary(assets: list[ETFAssetMonitor], previous_assets: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    for asset in assets:
        previous = previous_assets.get(asset.key) or {}
        previous_entry = previous.get("entry_score")
        previous_crowding = previous.get("crowding_score")
        previous_liquidity = previous.get("liquidity_label")
        if isinstance(previous_entry, (int, float)) and abs(asset.entry_score - previous_entry) >= 10:
            changes.append(f"{asset.symbol} 新增仓位环境由{int(previous_entry)}变为{asset.entry_score}。")
        if isinstance(previous_crowding, (int, float)) and previous_crowding < 70 <= asset.crowding_score:
            changes.append(f"{asset.symbol} 拥挤度升至{asset.crowding_score}/100，进入偏高区间。")
        if previous_liquidity and previous_liquidity != asset.liquidity_label:
            changes.append(f"{asset.symbol} 流动性观察由“{previous_liquidity}”变为“{asset.liquidity_label}”。")
    return changes[:8] or ["ETF观察池未出现需要特别标记的状态切换。"]


def _load_portfolio_summary(
    assets: list[ETFAssetMonitor], path: Path = Path("portfolio.csv")
) -> tuple[list[str], list[str], list[PortfolioPosition], float | None]:
    if not path.exists():
        return [], ["尚未导入实际组合。可基于 Revolut investment statement 整理 portfolio.csv。"], [], None
    asset_map = {asset.symbol.upper(): asset for asset in assets}
    rows = []
    warnings = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:
        return [], [f"portfolio.csv 无法读取：{type(exc).__name__}"], [], None
    portfolio_positions = [
        PortfolioPosition(
            symbol=str(row.get("symbol") or "").strip().upper(),
            weight_pct=_safe_float(row.get("weight_pct")) or 0,
            quantity=_safe_float(row.get("quantity")),
            average_cost_gbp=_safe_float(row.get("average_cost_gbp")),
            current_price_gbp=_safe_float(row.get("current_price_gbp")),
            market_value_gbp=_safe_float(row.get("estimated_market_value_gbp")),
            unrealized_pnl_gbp=_safe_float(row.get("unrealized_pnl_gbp")),
            unrealized_pnl_pct=_safe_float(row.get("unrealized_pnl_pct")),
            day_change_pct=_safe_float(row.get("day_change_pct")),
            monitor_status=str(row.get("monitor_status") or "unknown"),
            native_currency=str(row.get("native_currency") or ""),
            current_price_native=_safe_float(row.get("current_price_native")),
            market_value_native=_safe_float(row.get("market_value_native")),
            fx_pair=str(row.get("fx_pair") or ""),
            fx_rate=_safe_float(row.get("fx_rate")),
            fx_as_of=str(row.get("fx_as_of") or ""),
            price_source=str(row.get("price_source") or ""),
            year_peak_price_native=_safe_float(row.get("year_peak_price_native")),
            year_peak_date=str(row.get("year_peak_date") or ""),
            drawdown_from_year_peak_pct=_safe_float(row.get("drawdown_from_year_peak_pct")),
            peak_watch=str(row.get("peak_watch") or ""),
        )
        for row in rows
        if str(row.get("symbol") or "").strip()
    ]
    portfolio_total = sum(item.market_value_gbp or 0 for item in portfolio_positions) or None
    red_peak_watches = [
        f"{item.symbol} {_fmt_signed_pct(item.drawdown_from_year_peak_pct)}"
        for item in portfolio_positions
        if item.drawdown_from_year_peak_pct is not None and item.drawdown_from_year_peak_pct <= -10
    ]
    yellow_peak_watches = [
        f"{item.symbol} {_fmt_signed_pct(item.drawdown_from_year_peak_pct)}"
        for item in portfolio_positions
        if item.drawdown_from_year_peak_pct is not None and -10 < item.drawdown_from_year_peak_pct <= -5
    ]
    if red_peak_watches:
        warnings.append("红色回撤观察：以下持仓较年内高点回撤超过10%，需复核趋势、估值与仓位风险：" + "、".join(red_peak_watches) + "。")
    if yellow_peak_watches:
        warnings.append("黄色回撤观察：以下持仓较年内高点回撤超过5%，需观察回撤性质与支撑位：" + "、".join(yellow_peak_watches) + "。")
    positions = []
    uncovered = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        weight = _safe_float(row.get("weight_pct"))
        if not symbol or weight is None or weight <= 0:
            continue
        asset = asset_map.get(symbol)
        if asset is None:
            uncovered.append(symbol)
            continue
        positions.append((asset, weight))
    if not positions:
        return [], warnings + ["portfolio.csv 未包含可识别的 symbol,weight_pct 持仓。"], portfolio_positions, portfolio_total
    if uncovered:
        warnings.append("以下个股或观察池外ETF暂未纳入ETF趋势模型；直接持仓仍会计入组合暴露：" + "、".join(uncovered) + "。")
    total = sum(weight for _, weight in positions)
    themes: dict[str, float] = {}
    weighted_ter = 0.0
    for asset, weight in positions:
        themes[asset.theme] = themes.get(asset.theme, 0.0) + weight
        weighted_ter += (asset.ter or 0) * weight
    top_themes = sorted(themes.items(), key=lambda item: item[1], reverse=True)[:4]
    summary = [
        f"已导入{len(positions)}只 ETF，识别权重合计{total:.1f}%。",
        "主要主题暴露：" + "、".join(f"{theme} {weight:.1f}%" for theme, weight in top_themes) + "。",
        f"组合加权TER约{weighted_ter / total:.2f}%。",
    ]
    fx_notes = _portfolio_fx_notes(portfolio_positions)
    if fx_notes:
        summary.append("GBP参考估值使用抓取时点FX：" + "；".join(fx_notes) + "。")
    return summary, warnings, portfolio_positions, portfolio_total


def _portfolio_fx_notes(positions: list[PortfolioPosition]) -> list[str]:
    notes = {}
    for item in positions:
        if not item.fx_pair or item.fx_rate in (None, 0):
            continue
        notes[item.fx_pair] = f"{item.fx_pair} {item.fx_rate:.4f}（Yahoo，{item.fx_as_of or '时间待确认'}）"
    return [notes[key] for key in sorted(notes)]


def _fmt_signed_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


def _portfolio_exposure_summary(
    assets: list[ETFAssetMonitor], positions: list[PortfolioPosition]
) -> tuple[list[PortfolioExposure], list[str]]:
    focus = {
        "NVDA": ("NVIDIA", ("NVDA", "NVIDIA")),
        "AVGO": ("Broadcom", ("AVGO", "BROADCOM")),
        "META": ("Meta Platforms", ("META", "META PLATFORMS")),
        "AMD": ("AMD", ("AMD", "ADVANCED MICRO DEVICES")),
        "TSM": ("TSMC", ("TSM", "TSMC", "TAIWAN SEMICONDUCTOR")),
        "ASML": ("ASML", ("ASML",)),
        "005930": ("Samsung Electronics", ("005930", "SAMSUNG ELECTRONICS", "SAMSUNG ELEC")),
        "000660": ("SK hynix", ("000660", "SK HYNIX", "SKHYNIX")),
    }
    asset_map = {asset.symbol.upper(): asset for asset in assets}
    direct = {symbol: 0.0 for symbol in focus}
    indirect = {symbol: 0.0 for symbol in focus}
    covered_etf_weight = 0.0
    lookthrough_weight = 0.0

    for position in positions:
        symbol = position.symbol.upper()
        direct_symbol = _focus_exposure_symbol(symbol, symbol, focus)
        if direct_symbol:
            direct[direct_symbol] += position.weight_pct
        asset = asset_map.get(symbol)
        if asset is None:
            continue
        covered_etf_weight += position.weight_pct
        if not asset.holdings:
            continue
        lookthrough_weight += position.weight_pct
        for holding in asset.holdings:
            holding_symbol = _focus_exposure_symbol(holding.symbol, holding.name, focus)
            if holding_symbol:
                indirect[holding_symbol] += position.weight_pct * holding.weight / 100

    exposures = [
        PortfolioExposure(
            symbol=symbol,
            label=label,
            weight_pct=direct[symbol] + indirect[symbol],
            direct_weight_pct=direct[symbol],
            etf_weight_pct=indirect[symbol],
        )
        for symbol, (label, _aliases) in focus.items()
        if direct[symbol] + indirect[symbol] > 0
    ]
    exposures.sort(key=lambda item: item.weight_pct, reverse=True)
    if not exposures:
        return [], []

    ai_total = sum(item.weight_pct for item in exposures)
    ai_direct = sum(item.direct_weight_pct for item in exposures)
    ai_indirect = sum(item.etf_weight_pct for item in exposures)
    semiconductor_total = sum(
        item.weight_pct for item in exposures if item.symbol in {"NVDA", "AVGO", "AMD", "TSM", "ASML", "005930", "000660"}
    )
    notes = [
        f"AI核心公司可识别暴露下限 {ai_total:.1f}%：直接持仓 {ai_direct:.1f}%，ETF前十大持仓间接暴露 {ai_indirect:.1f}%。",
        f"其中半导体设备、算力与存储链可识别暴露下限 {semiconductor_total:.1f}%。",
    ]
    if covered_etf_weight > lookthrough_weight:
        notes.append(
            f"当前已识别ETF权重 {covered_etf_weight:.1f}%，其中 {lookthrough_weight:.1f}% 可获得前十大持仓；"
            "未穿透部分可能继续包含AI相关公司。"
        )
    notes.append("组合穿透基于直接持仓与ETF前十大持仓近似计算，属于可识别下限，不等同于完整基金穿透。")
    hbm_total = sum(item.weight_pct for item in exposures if item.symbol in {"005930", "000660"})
    notes.append(f"Samsung Electronics 与 SK hynix 的 HBM / 存储链可识别暴露下限 {hbm_total:.1f}%。")
    return exposures, notes


def _focus_exposure_symbol(
    symbol: str,
    name: str,
    focus: dict[str, tuple[str, tuple[str, ...]]],
) -> str | None:
    haystack = f"{symbol} {name}".upper()
    for canonical_symbol, (_label, aliases) in focus.items():
        if any(re.search(rf"(?<![A-Z0-9]){re.escape(alias)}(?![A-Z0-9])", haystack) for alias in aliases):
            return canonical_symbol
    return None


def _valuation_warnings(
    spec: ETFSpec,
    pe: float | None,
    forward_pe: float | None,
    pb: float | None,
    pe_percentile: float | None,
    pe_high_1y_ratio: float | None,
) -> list[str]:
    if spec.theme == "Gold":
        return ["黄金ETC不适用PE/PB估值，需结合实际利率、美元和金价趋势观察。"]
    if not spec.equity_like:
        return ["固定收益ETF不适用PE/PB估值，需结合久期、收益率曲线与利率风险观察。"]
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
    if spec.theme == "Gold":
        return "黄金不适用盈利估值，重点观察实际利率与美元"
    if not spec.equity_like:
        return "固定收益ETF不适用盈利估值，重点观察久期与利率风险"
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
    if score >= CROWDING_HIGH_THRESHOLD:
        return "拥挤度高：趋势强但短线回撤敏感度上升"
    if score >= CROWDING_ELEVATED_THRESHOLD:
        return "拥挤度偏高：需关注RSI和均线乖离"
    if score >= 65:
        return "拥挤度升温：接近偏高区，需观察动量延续性"
    if score <= CROWDING_LOW_THRESHOLD:
        return "拥挤度偏低：价格尚未形成明显过热结构"
    if rsi14 is not None and rsi14 <= 30:
        return "短线超卖：风险释放后可能进入修复观察区"
    if distance_sma200 is not None and distance_sma200 < 0:
        return "趋势偏弱：仍需等待重新站上长期均线"
    return "拥挤度中性：尚未出现极端过热或超卖"


def _entry_quality(asset: ETFAssetMonitor, macro_metrics: dict[str, Any] | None = None) -> tuple[int, str, str, str]:
    if asset.theme == "US Treasury 7-10Y GBP Hedged":
        return _fixed_income_entry_quality(asset)
    if asset.theme == "Gold":
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


def _fixed_income_entry_quality(asset: ETFAssetMonitor) -> tuple[int, str, str, str]:
    if asset.value is None or asset.sma200 is None:
        return (
            50,
            "久期环境待确认",
            "价格历史不足，暂不判断中久期美债配置环境。",
            "固定收益ETF需结合久期、收益率曲线与利率波动观察。",
        )
    score = 50.0
    score += 10 if asset.value >= asset.sma200 else -10
    if asset.sma50 is not None and asset.sma200 is not None:
        score += 5 if asset.sma50 >= asset.sma200 else -5
    if asset.rsi14 is not None:
        if 40 <= asset.rsi14 <= 65:
            score += 6
        elif asset.rsi14 >= 75:
            score -= 8
    if asset.momentum_1m is not None:
        if 0 <= asset.momentum_1m <= 5:
            score += 5
        elif asset.momentum_1m < -5:
            score -= 5
    final_score = _clamp(score)
    if final_score >= 65:
        label = "中久期美债趋势环境偏友好"
    elif final_score >= 45:
        label = "中久期美债环境中性"
    else:
        label = "中久期美债价格趋势承压"
    note = "IGTM为GBP对冲的美国7-10年期国债ETF，趋势分数只反映价格与久期环境，不套用股票估值或AI拥挤度框架。"
    risk = "风险管理重点：观察美国长端收益率、MOVE债券波动率与期限溢价变化。"
    return final_score, label, note, risk


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
