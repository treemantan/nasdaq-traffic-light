from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .data_sources import DEFAULT_HTTP_HEADERS


@dataclass(frozen=True)
class OptionsGammaConfig:
    enabled: bool = True
    benchmark_tickers: tuple[str, ...] = ("SPY", "QQQ")
    extra_tickers: tuple[str, ...] = ()
    expirations_to_include: int = 3
    max_days_to_expiry: int = 30
    min_volume_threshold: int = 100
    min_open_interest_threshold: int = 100
    include_single_names: bool = True


@dataclass(frozen=True)
class OptionContract:
    ticker: str
    option_type: str
    strike: float
    expiry: date
    open_interest: int
    volume: int
    bid: float | None
    ask: float | None
    last_price: float | None
    implied_volatility: float | None
    contract_symbol: str = ""


@dataclass(frozen=True)
class OptionGammaAssessment:
    symbol: str
    origin: str
    spot_price: float | None
    nearest_expiry: str
    regime_label: str
    data_status: str
    call_wall: float | None
    put_wall: float | None
    near_spot_oi_strike: float | None
    largest_gamma_strike: float | None
    pin_strike: float | None
    gross_call_gamma: float
    gross_put_gamma: float
    notable_flow: str
    interpretation: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OptionsGammaMonitor:
    generated_at: str
    summary: str
    assessments: list[OptionGammaAssessment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


OptionChainFetcher = Callable[[str, OptionsGammaConfig], Any]


def build_options_gamma_monitor(
    config: OptionsGammaConfig,
    etf_monitor: Any,
    fetcher: OptionChainFetcher | None = None,
) -> OptionsGammaMonitor:
    generated_at = datetime.now(timezone.utc).astimezone().isoformat()
    if not config.enabled:
        return OptionsGammaMonitor(generated_at=generated_at, summary="Options gamma 模块未启用。")

    universe = _resolve_gamma_universe(config, etf_monitor)
    fetch = fetcher or fetch_yahoo_option_chain
    assessments: list[OptionGammaAssessment] = []
    warnings: list[str] = []

    for symbol, origin in universe:
        if fetcher is None and symbol.upper().endswith(".L"):
            assessments.append(
                _unavailable_assessment(
                    symbol,
                    origin,
                    generated_at,
                    "LSE/UK UCITS 标的通常没有 Yahoo 可用期权链；保留在覆盖范围内，但不强行估算 gamma。",
                )
            )
            continue
        try:
            spot, contracts, fetch_warnings = fetch(symbol, config)
            assessment = assess_gamma_for_contracts(
                symbol,
                origin,
                spot,
                contracts,
                generated_at=generated_at,
                min_volume_threshold=config.min_volume_threshold,
                min_open_interest_threshold=config.min_open_interest_threshold,
            )
            if fetch_warnings:
                assessment.warnings.extend(fetch_warnings)
            assessments.append(assessment)
        except Exception as exc:  # pragma: no cover - defensive degradation for live data
            warnings.append(f"{symbol}: options chain fetch failed: {exc}")
            assessments.append(_unavailable_assessment(symbol, origin, generated_at, str(exc)))

    available = sum(1 for item in assessments if item.data_status != "insufficient")
    summary = (
        f"已尝试 {len(assessments)} 个标的；{available} 个具备可用期权链。"
        "本模块基于 OI、成交量位置与近月 gamma 估算，不代表真实 dealer book。"
    )
    return OptionsGammaMonitor(generated_at=generated_at, summary=summary, assessments=assessments, warnings=warnings)


def assess_gamma_for_contracts(
    symbol: str,
    origin: str,
    spot: float | None,
    contracts: list[OptionContract],
    *,
    generated_at: str,
    min_volume_threshold: int,
    min_open_interest_threshold: int,
) -> OptionGammaAssessment:
    if not spot or spot <= 0 or not contracts:
        return _unavailable_assessment(symbol, origin, generated_at, "Yahoo 未提供可用期权链；UK UCITS ETF 常见此情况。")

    valid = [c for c in contracts if c.open_interest >= min_open_interest_threshold or c.volume >= min_volume_threshold]
    if not valid:
        return _unavailable_assessment(symbol, origin, generated_at, "期权链存在，但 OI/成交量低于阈值。", spot)

    nearest_expiry = min(c.expiry for c in valid).isoformat()
    call_wall = _max_oi_strike(valid, "call")
    put_wall = _max_oi_strike(valid, "put")
    near_spot_oi = _near_spot_oi_strike(valid, spot)
    gamma_by_strike = _gamma_by_strike(valid, spot)
    largest_gamma_strike = max(gamma_by_strike, key=gamma_by_strike.get) if gamma_by_strike else None
    pin_strike = near_spot_oi if near_spot_oi is not None and abs(near_spot_oi / spot - 1) <= 0.015 else None

    call_gamma = sum(gamma_exposure(c, spot) for c in valid if c.option_type == "call")
    put_gamma = sum(gamma_exposure(c, spot) for c in valid if c.option_type == "put")
    flow = _flow_stats(valid, spot)
    regime_label, interpretation = _classify_gamma_regime(flow, pin_strike, min_volume_threshold)
    notable_flow = _flow_text(flow)

    warnings: list[str] = []
    if origin == "covered_etf" and "." in symbol:
        warnings.append("该标的为交易所后缀 ticker；若无期权链，通常属于数据源或产品结构限制。")

    return OptionGammaAssessment(
        symbol=symbol,
        origin=origin,
        spot_price=spot,
        nearest_expiry=nearest_expiry,
        regime_label=regime_label,
        data_status="available",
        call_wall=call_wall,
        put_wall=put_wall,
        near_spot_oi_strike=near_spot_oi,
        largest_gamma_strike=largest_gamma_strike,
        pin_strike=pin_strike,
        gross_call_gamma=call_gamma,
        gross_put_gamma=put_gamma,
        notable_flow=notable_flow,
        interpretation=interpretation,
        warnings=warnings,
    )


def black_scholes_gamma(
    spot: float,
    strike: float,
    days_to_expiry: int,
    implied_volatility: float | None,
    risk_free_rate: float = 0.045,
    dividend_yield: float = 0.0,
) -> float:
    if spot <= 0 or strike <= 0 or not implied_volatility or implied_volatility <= 0:
        return 0.0
    t = max(days_to_expiry, 1) / 365.0
    sigma_sqrt_t = implied_volatility * math.sqrt(t)
    if sigma_sqrt_t <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (risk_free_rate - dividend_yield + 0.5 * implied_volatility**2) * t) / sigma_sqrt_t
    normal_pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return math.exp(-dividend_yield * t) * normal_pdf / (spot * sigma_sqrt_t)


def gamma_exposure(contract: OptionContract, spot: float, multiplier: int = 100) -> float:
    gamma = black_scholes_gamma(
        spot=spot,
        strike=contract.strike,
        days_to_expiry=(contract.expiry - date.today()).days,
        implied_volatility=contract.implied_volatility,
    )
    return gamma * contract.open_interest * multiplier * spot * spot * 0.01


def classify_trade_location(last_price: float | None, bid: float | None, ask: float | None) -> str:
    if last_price is None or bid is None or ask is None or bid < 0 or ask <= bid:
        return "unknown"
    spread = ask - bid
    if last_price >= ask - spread * 0.25:
        return "ask"
    if last_price <= bid + spread * 0.25:
        return "bid"
    return "mid"


def fetch_yahoo_option_chain(symbol: str, config: OptionsGammaConfig) -> tuple[float | None, list[OptionContract], list[str]]:
    encoded = urllib.parse.quote(symbol, safe="")
    base_url = f"https://query2.finance.yahoo.com/v7/finance/options/{encoded}"
    payload = _read_json(base_url)
    result = _first_result(payload)
    quote = result.get("quote") or {}
    spot = _to_float(quote.get("regularMarketPrice") or quote.get("postMarketPrice") or quote.get("preMarketPrice"))
    expiration_epochs = _select_expirations(result.get("expirationDates") or [], config)
    contracts: list[OptionContract] = []
    warnings: list[str] = []

    if not expiration_epochs:
        return spot, [], ["Yahoo 未返回可用 expirationDates。"]

    for expiry_epoch in expiration_epochs:
        time.sleep(0.05)
        chain_payload = _read_json(f"{base_url}?date={int(expiry_epoch)}")
        chain_result = _first_result(chain_payload)
        options = (chain_result.get("options") or [{}])[0]
        expiry = datetime.fromtimestamp(int(expiry_epoch), tz=timezone.utc).date()
        for raw in options.get("calls") or []:
            contracts.append(_contract_from_yahoo(symbol, "call", expiry, raw))
        for raw in options.get("puts") or []:
            contracts.append(_contract_from_yahoo(symbol, "put", expiry, raw))

    if not contracts:
        warnings.append("Yahoo option chain 为空。")
    return spot, contracts, warnings


def _resolve_gamma_universe(config: OptionsGammaConfig, etf_monitor: Any) -> list[tuple[str, str]]:
    ordered: list[tuple[str, str]] = []

    def add(symbol: object, origin: str) -> None:
        text = str(symbol or "").strip().upper()
        if not text:
            return
        if any(existing == text for existing, _ in ordered):
            return
        ordered.append((text, origin))

    for symbol in config.benchmark_tickers:
        add(symbol, "benchmark")
    for asset in getattr(etf_monitor, "assets", []) or []:
        add(getattr(asset, "symbol", ""), "covered_etf")
    for position in getattr(etf_monitor, "portfolio_positions", []) or []:
        symbol = getattr(position, "symbol", "")
        if config.include_single_names or "." in str(symbol):
            add(symbol, "holding")
    for symbol in config.extra_tickers:
        add(symbol, "extra")
    return ordered


def _contract_from_yahoo(symbol: str, option_type: str, expiry: date, raw: dict[str, Any]) -> OptionContract:
    return OptionContract(
        ticker=symbol,
        option_type=option_type,
        strike=float(raw.get("strike") or 0),
        expiry=expiry,
        open_interest=int(raw.get("openInterest") or 0),
        volume=int(raw.get("volume") or 0),
        bid=_to_float(raw.get("bid")),
        ask=_to_float(raw.get("ask")),
        last_price=_to_float(raw.get("lastPrice")),
        implied_volatility=_to_float(raw.get("impliedVolatility")),
        contract_symbol=str(raw.get("contractSymbol") or ""),
    )


def _select_expirations(expiration_epochs: list[int], config: OptionsGammaConfig) -> list[int]:
    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=config.max_days_to_expiry)
    selected = []
    for epoch in sorted(int(x) for x in expiration_epochs):
        expiry = datetime.fromtimestamp(epoch, tz=timezone.utc).date()
        if today <= expiry <= cutoff:
            selected.append(epoch)
        if len(selected) >= max(1, config.expirations_to_include):
            break
    return selected


def _read_json(url: str, timeout: int = 15) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=DEFAULT_HTTP_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _first_result(payload: dict[str, Any]) -> dict[str, Any]:
    result = ((payload.get("optionChain") or {}).get("result") or [])
    if not result:
        raise ValueError("Yahoo optionChain result is empty")
    return result[0]


def _max_oi_strike(contracts: list[OptionContract], option_type: str) -> float | None:
    items = [c for c in contracts if c.option_type == option_type and c.open_interest > 0]
    if not items:
        return None
    return max(items, key=lambda c: c.open_interest).strike


def _near_spot_oi_strike(contracts: list[OptionContract], spot: float) -> float | None:
    totals: dict[float, int] = {}
    for contract in contracts:
        if abs(contract.strike / spot - 1) <= 0.08:
            totals[contract.strike] = totals.get(contract.strike, 0) + contract.open_interest
    if not totals:
        return None
    return max(totals, key=totals.get)


def _gamma_by_strike(contracts: list[OptionContract], spot: float) -> dict[float, float]:
    totals: dict[float, float] = {}
    for contract in contracts:
        totals[contract.strike] = totals.get(contract.strike, 0.0) + gamma_exposure(contract, spot)
    return totals


def _flow_stats(contracts: list[OptionContract], spot: float) -> dict[str, float]:
    stats = {
        "otm_call_ask": 0.0,
        "otm_put_ask": 0.0,
        "bid_volume": 0.0,
        "ask_volume": 0.0,
        "total_volume": 0.0,
        "total_oi": 0.0,
    }
    for contract in contracts:
        location = classify_trade_location(contract.last_price, contract.bid, contract.ask)
        volume = float(contract.volume or 0)
        stats["total_volume"] += volume
        stats["total_oi"] += float(contract.open_interest or 0)
        if location == "ask":
            stats["ask_volume"] += volume
            if contract.option_type == "call" and contract.strike > spot:
                stats["otm_call_ask"] += volume
            if contract.option_type == "put" and contract.strike < spot:
                stats["otm_put_ask"] += volume
        elif location == "bid":
            stats["bid_volume"] += volume
    stats["volume_oi_ratio"] = stats["total_volume"] / stats["total_oi"] if stats["total_oi"] else 0.0
    return stats


def _classify_gamma_regime(
    flow: dict[str, float],
    pin_strike: float | None,
    min_volume_threshold: int,
) -> tuple[str, str]:
    directional_buying = flow["otm_call_ask"] + flow["otm_put_ask"]
    seller_volume = flow["bid_volume"]
    buyer_volume = flow["ask_volume"]
    if directional_buying >= min_volume_threshold and directional_buying > seller_volume * 1.2:
        return (
            "偏负Gamma / dealer short gamma",
            "OTM 期权买盘较强，若该方向继续放量，dealer 对冲可能放大盘中单边波动。",
        )
    if seller_volume >= min_volume_threshold and seller_volume > buyer_volume * 1.2:
        return (
            "偏正Gamma / dealer long gamma",
            "成交更偏卖方发起，若集中在高 OI 行权价附近，dealer 对冲更可能呈现均值回归或压波动特征。",
        )
    if pin_strike is not None:
        return (
            "信号混合 / 可能pinning",
            "现价接近高 OI 行权价，但方向性成交不足，临近到期可能存在磁吸或钉住效应。",
        )
    return (
        "信号混合 / unclear",
        "OI 与成交方向没有形成单边结论，应将其作为波动结构观察项，而非方向信号。",
    )


def _flow_text(flow: dict[str, float]) -> str:
    return (
        f"OTM call ask量 {flow['otm_call_ask']:.0f}；OTM put ask量 {flow['otm_put_ask']:.0f}；"
        f"bid侧成交量 {flow['bid_volume']:.0f}；ask侧成交量 {flow['ask_volume']:.0f}；"
        f"成交/OI {flow['volume_oi_ratio']:.2f}x。"
    )


def _unavailable_assessment(
    symbol: str,
    origin: str,
    generated_at: str,
    warning: str,
    spot: float | None = None,
) -> OptionGammaAssessment:
    return OptionGammaAssessment(
        symbol=symbol,
        origin=origin,
        spot_price=spot,
        nearest_expiry="N/A",
        regime_label="数据不足",
        data_status="insufficient",
        call_wall=None,
        put_wall=None,
        near_spot_oi_strike=None,
        largest_gamma_strike=None,
        pin_strike=None,
        gross_call_gamma=0.0,
        gross_put_gamma=0.0,
        notable_flow="Options gamma data unavailable for this ticker today.",
        interpretation="当前无法基于免费期权链估算 dealer hedging regime。",
        warnings=[warning],
    )


def _to_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    except (TypeError, ValueError):
        return None
