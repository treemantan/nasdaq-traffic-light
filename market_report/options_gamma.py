from __future__ import annotations

import json
import math
import os
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
    data_source_priority: tuple[str, ...] = ("alpha_vantage", "yahoo")
    alpha_vantage_api_key_env: str = "ALPHA_VANTAGE_API_KEY"
    alpha_vantage_max_requests: int = 8
    alpha_vantage_fetch_spot_quote: bool = True
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
    fetch = fetcher or _DefaultOptionChainFetcher(config).fetch
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


class _DefaultOptionChainFetcher:
    def __init__(self, config: OptionsGammaConfig):
        self.alpha_requests = 0
        self.alpha_budget = max(0, int(config.alpha_vantage_max_requests))

    def fetch(self, symbol: str, config: OptionsGammaConfig) -> tuple[float | None, list[OptionContract], list[str]]:
        warnings: list[str] = []
        errors: list[str] = []
        sources = tuple(str(source).strip().lower() for source in config.data_source_priority if str(source).strip())

        for source in sources:
            if source in {"alpha", "alpha_vantage", "alphavantage"}:
                if self.alpha_requests >= self.alpha_budget:
                    warnings.append("Alpha Vantage request budget exhausted for this run; using fallback source.")
                    continue
                if not _alpha_vantage_api_key(config):
                    warnings.append("Alpha Vantage API key is not configured; using fallback source.")
                    continue
                self.alpha_requests += 1
                try:
                    spot, contracts, source_warnings = fetch_alpha_vantage_option_chain(symbol, config)
                    if not contracts:
                        warnings.extend(source_warnings)
                        warnings.append("Alpha Vantage returned no usable option contracts; trying fallback source.")
                        continue
                    return spot, contracts, warnings + source_warnings
                except Exception as exc:
                    warnings.append(f"Alpha Vantage option-chain fetch failed: {exc}")
                    errors.append(str(exc))
                    continue

            if source in {"yahoo", "yfinance"}:
                try:
                    spot, contracts, source_warnings = fetch_yahoo_option_chain(symbol, config)
                    return spot, contracts, warnings + source_warnings
                except Exception as exc:
                    warnings.append(f"Yahoo option-chain fetch failed: {exc}")
                    errors.append(str(exc))
                    continue

            warnings.append(f"Unknown options gamma data source '{source}' skipped.")

        if errors:
            details = warnings + [f"Final source errors: {'; '.join(errors)}"]
            raise RuntimeError("; ".join(details))
        raise RuntimeError("No usable options gamma data source is configured.")


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


def fetch_alpha_vantage_option_chain(
    symbol: str,
    config: OptionsGammaConfig,
) -> tuple[float | None, list[OptionContract], list[str]]:
    api_key = _alpha_vantage_api_key(config)
    if not api_key:
        raise RuntimeError(f"{config.alpha_vantage_api_key_env} is not configured")

    query = urllib.parse.urlencode(
        {
            "function": "HISTORICAL_OPTIONS",
            "symbol": symbol,
            "apikey": api_key,
        }
    )
    payload = _read_json(f"https://www.alphavantage.co/query?{query}")
    _raise_alpha_vantage_error(payload)

    rows = payload.get("data") or payload.get("options") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        rows = []

    spot = _alpha_spot_from_rows(rows)
    if spot is None and config.alpha_vantage_fetch_spot_quote:
        spot = fetch_alpha_vantage_spot_quote(symbol, config)

    contracts = [
        contract
        for row in rows
        if isinstance(row, dict)
        for contract in [_contract_from_alpha_vantage(symbol, row)]
        if contract is not None
    ]
    contracts = _limit_contract_expirations(contracts, config)
    warnings = ["Alpha Vantage HISTORICAL_OPTIONS used; option OI/volume can be delayed."]
    if not contracts:
        warnings.append("Alpha Vantage returned no usable option contracts.")
    return spot, contracts, warnings


def fetch_alpha_vantage_spot_quote(symbol: str, config: OptionsGammaConfig) -> float | None:
    api_key = _alpha_vantage_api_key(config)
    if not api_key:
        return None
    query = urllib.parse.urlencode(
        {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": api_key,
        }
    )
    payload = _read_json(f"https://www.alphavantage.co/query?{query}")
    _raise_alpha_vantage_error(payload)
    quote = payload.get("Global Quote") or payload.get("globalQuote") or {}
    return _to_float(
        quote.get("05. price")
        or quote.get("price")
        or quote.get("regularMarketPrice")
        or quote.get("previousClose")
    )


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
        strike=_to_float(raw.get("strike")) or 0.0,
        expiry=expiry,
        open_interest=_to_int(raw.get("openInterest")) or 0,
        volume=_to_int(raw.get("volume")) or 0,
        bid=_to_float(raw.get("bid")),
        ask=_to_float(raw.get("ask")),
        last_price=_to_float(raw.get("lastPrice")),
        implied_volatility=_normalize_iv(raw.get("impliedVolatility")),
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


def _alpha_vantage_api_key(config: OptionsGammaConfig) -> str | None:
    preferred = str(config.alpha_vantage_api_key_env or "ALPHA_VANTAGE_API_KEY").strip()
    candidates = [preferred, "ALPHA_VANTAGE_API_KEY", "ALPHAVANTAGE_API_KEY"]
    for name in dict.fromkeys(candidates):
        value = os.environ.get(name)
        if value:
            return value.strip()
    return None


def _raise_alpha_vantage_error(payload: dict[str, Any]) -> None:
    for key in ("Error Message", "Note", "Information"):
        message = payload.get(key)
        if message:
            raise RuntimeError(str(message))


def _alpha_spot_from_rows(rows: list[Any]) -> float | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = _first_present(
            row,
            (
                "underlying_price",
                "underlyingPrice",
                "underlying",
                "spot",
                "spotPrice",
                "last_underlying_price",
            ),
        )
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _contract_from_alpha_vantage(symbol: str, raw: dict[str, Any]) -> OptionContract | None:
    contract_symbol = str(_first_present(raw, ("contractID", "contractSymbol", "optionSymbol", "symbol")) or "")
    option_type = _normalize_option_type(
        _first_present(raw, ("type", "option_type", "optionType", "put_call", "putCall", "side"))
    ) or _infer_option_type_from_symbol(contract_symbol)
    expiry = _parse_date(
        _first_present(raw, ("expiration", "expiry", "expirationDate", "expiration_date", "maturity"))
    )
    strike = _to_float(_first_present(raw, ("strike", "strikePrice", "strike_price")))

    if option_type is None or expiry is None or strike is None:
        return None

    return OptionContract(
        ticker=symbol,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        open_interest=_to_int(_first_present(raw, ("open_interest", "openInterest", "open interest"))) or 0,
        volume=_to_int(_first_present(raw, ("volume", "vol"))) or 0,
        bid=_to_float(_first_present(raw, ("bid", "bidPrice"))),
        ask=_to_float(_first_present(raw, ("ask", "askPrice"))),
        last_price=_to_float(_first_present(raw, ("last", "lastPrice", "last_price", "mark", "mid"))),
        implied_volatility=_normalize_iv(
            _first_present(raw, ("implied_volatility", "impliedVolatility", "iv", "IV"))
        ),
        contract_symbol=contract_symbol,
    )


def _limit_contract_expirations(contracts: list[OptionContract], config: OptionsGammaConfig) -> list[OptionContract]:
    if not contracts:
        return []
    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=max(0, int(config.max_days_to_expiry)))
    future = [contract for contract in contracts if contract.expiry >= today]
    within_window = [contract for contract in future if contract.expiry <= cutoff]
    scoped = within_window or future or contracts
    expiries = sorted({contract.expiry for contract in scoped})[: max(1, int(config.expirations_to_include))]
    expiry_set = set(expiries)
    return [contract for contract in scoped if contract.expiry in expiry_set]


def _first_present(raw: dict[str, Any], names: tuple[str, ...]) -> object:
    lower_lookup = {str(key).lower(): value for key, value in raw.items()}
    for name in names:
        if name in raw and raw[name] not in (None, ""):
            return raw[name]
        value = lower_lookup.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _parse_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value in (None, ""):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _normalize_option_type(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"c", "call", "calls"}:
        return "call"
    if text in {"p", "put", "puts"}:
        return "put"
    return None


def _infer_option_type_from_symbol(contract_symbol: str) -> str | None:
    text = contract_symbol.upper()
    if len(text) >= 9:
        tail = text[-9:]
        if tail[0] == "C":
            return "call"
        if tail[0] == "P":
            return "put"
    if "CALL" in text:
        return "call"
    if "PUT" in text:
        return "put"
    return None


def _to_int(value: object) -> int | None:
    parsed = _to_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _normalize_iv(value: object) -> float | None:
    parsed = _to_float(value)
    if parsed is None:
        return None
    if parsed > 3:
        return parsed / 100
    return parsed


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
        if isinstance(value, str):
            text = value.strip()
            if not text or text.upper() in {"N/A", "NA", "NONE", "NULL", "-"}:
                return None
            percent = text.endswith("%")
            text = text[:-1].strip() if percent else text
            parsed = float(text.replace(",", ""))
            if percent:
                parsed = parsed / 100
        else:
            parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    except (TypeError, ValueError):
        return None
