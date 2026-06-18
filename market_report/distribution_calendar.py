from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class DistributionEvent:
    symbol: str
    ex_date: str
    amount: float | None = None
    currency: str = "GBP"
    declaration_date: str = ""
    record_date: str = ""
    pay_date: str = ""
    source: str = ""
    source_url: str = ""
    confidence: str = "medium"


CASH_LIKE_DISTRIBUTION_SYMBOLS = {"ERNS", "ERNS.L"}

MANUAL_DISTRIBUTION_EVENTS: dict[str, DistributionEvent] = {
    "ERNS.L": DistributionEvent(
        symbol="ERNS.L",
        declaration_date="2026-06-11",
        ex_date="2026-06-18",
        record_date="2026-06-19",
        pay_date="2026-06-30",
        amount=1.0211,
        currency="GBP",
        source="DividendMax / DividendData manual check",
        source_url=(
            "https://www.dividendmax.com/united-kingdom/london-stock-exchange/unknown/"
            "ishares-iv-plc-ishares-ultrashort-bond-ucits-etf/dividends"
        ),
        confidence="high",
    )
}


def normalize_distribution_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized in MANUAL_DISTRIBUTION_EVENTS:
        return normalized
    if not normalized.endswith(".L") and f"{normalized}.L" in MANUAL_DISTRIBUTION_EVENTS:
        return f"{normalized}.L"
    return normalized


def cash_like_distribution_event(symbol: str, meta: dict[str, object]) -> DistributionEvent | None:
    normalized_symbol = normalize_distribution_symbol(symbol)
    if normalized_symbol not in CASH_LIKE_DISTRIBUTION_SYMBOLS:
        return None

    manual = MANUAL_DISTRIBUTION_EVENTS.get(normalized_symbol)
    if manual:
        return manual
    return latest_yahoo_distribution_event(normalized_symbol, meta)


def latest_yahoo_distribution_event(symbol: str, meta: dict[str, object]) -> DistributionEvent | None:
    raw_events = meta.get("_dividend_events")
    if not isinstance(raw_events, list):
        return None

    parsed: list[tuple[date, str, float | None]] = []
    today = date.today()
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        ex_date_raw = str(item.get("ex_date") or "")
        try:
            ex_day = date.fromisoformat(ex_date_raw)
        except ValueError:
            continue
        if ex_day > today:
            continue
        parsed.append((ex_day, ex_date_raw, _safe_float(item.get("amount"))))

    if not parsed:
        return None

    _, ex_date, amount = max(parsed, key=lambda item: item[0])
    return DistributionEvent(
        symbol=normalize_distribution_symbol(symbol),
        ex_date=ex_date,
        amount=amount,
        source="Yahoo dividend events",
        confidence="medium",
    )


def distribution_note(event: DistributionEvent | None) -> str:
    if event is None:
        return (
            "现金/超短债分派周期：未从可用数据源确认最新除息日；若发行商近期除息，"
            "约一个季度收益幅度的价格回落应按净值除息处理，到账日以Revolut入账为准。"
        )

    amount_text = _format_amount(event.amount, event.currency)
    if event.pay_date or event.record_date or event.declaration_date:
        source = f"（{event.source}）" if event.source else ""
        return (
            f"现金/超短债分派周期：Declaration {event.declaration_date or '待确认'}，"
            f"Ex-dividend {event.ex_date or '待确认'}，Record {event.record_date or '待确认'}，"
            f"Pay date {event.pay_date or '待确认'}，每份分派 {amount_text}{source}。"
            "除息日附近的价格回落应与分派现金合并观察，不按权益式趋势破坏处理；"
            "Revolut可能在pay date当日或之后若干个工作日入账。"
        )

    return (
        f"现金/超短债分派周期：{event.source or '可用数据源'}记录最近除息日 {event.ex_date}，"
        f"每份分派约 {amount_text}；净值回落应与分派现金合并观察，"
        "不按权益式趋势破坏处理。Revolut到账日取决于发行商payment date和券商入账节奏。"
    )


def distribution_fields(symbol: str, meta: dict[str, object]) -> dict[str, object]:
    if normalize_distribution_symbol(symbol) not in CASH_LIKE_DISTRIBUTION_SYMBOLS:
        return {
            "distribution_ex_date": "",
            "distribution_amount_native": None,
            "distribution_cycle_note": "",
        }

    event = cash_like_distribution_event(symbol, meta)
    return {
        "distribution_ex_date": event.ex_date if event else "",
        "distribution_amount_native": event.amount if event else None,
        "distribution_cycle_note": distribution_note(event),
    }


def _format_amount(amount: float | None, currency: str) -> str:
    if amount is None:
        return "待确认"
    if currency.upper() == "GBP":
        return f"£{amount:.4f}"
    return f"{amount:.4f} {currency.upper()}"


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
