from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
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
    status: str = "declared"
    distribution_type: str = "quarterly"


CASH_LIKE_DISTRIBUTION_SYMBOLS = {"ERNS", "ERNS.L"}
DIVIDENDMAX_ERNS_URL = (
    "https://www.dividendmax.com/united-kingdom/london-stock-exchange/unknown/"
    "ishares-iv-plc-ishares-ultrashort-bond-ucits-etf/dividends"
)

MANUAL_DISTRIBUTION_SCHEDULES: dict[str, list[DistributionEvent]] = {
    "ERNS.L": [
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2026-06-11",
            ex_date="2026-06-18",
            record_date="2026-06-19",
            pay_date="2026-06-30",
            amount=1.0211,
            currency="GBP",
            source="DividendMax / DividendData manual check",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="high",
            status="declared",
        ),
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2026-09-16",
            ex_date="2026-09-17",
            pay_date="2026-09-30",
            currency="GBP",
            source="DividendMax forecast",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="forecast",
            status="forecast",
        ),
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2026-12-16",
            ex_date="2026-12-17",
            pay_date="2026-12-31",
            currency="GBP",
            source="DividendMax forecast",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="forecast",
            status="forecast",
        ),
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2027-03-11",
            ex_date="2027-03-18",
            pay_date="2027-03-30",
            currency="GBP",
            source="DividendMax forecast",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="forecast",
            status="forecast",
        ),
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2027-06-10",
            ex_date="2027-06-17",
            pay_date="2027-06-29",
            currency="GBP",
            source="DividendMax forecast",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="forecast",
            status="forecast",
        ),
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2027-09-15",
            ex_date="2027-09-16",
            pay_date="2027-09-29",
            currency="GBP",
            source="DividendMax forecast",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="forecast",
            status="forecast",
        ),
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2027-12-15",
            ex_date="2027-12-16",
            pay_date="2027-12-30",
            currency="GBP",
            source="DividendMax forecast",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="forecast",
            status="forecast",
        ),
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2028-03-09",
            ex_date="2028-03-16",
            pay_date="2028-03-28",
            currency="GBP",
            source="DividendMax forecast",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="forecast",
            status="forecast",
        ),
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2028-06-08",
            ex_date="2028-06-15",
            pay_date="2028-06-27",
            currency="GBP",
            source="DividendMax forecast",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="forecast",
            status="forecast",
        ),
        DistributionEvent(
            symbol="ERNS.L",
            declaration_date="2028-09-13",
            ex_date="2028-09-14",
            pay_date="2028-09-27",
            currency="GBP",
            source="DividendMax forecast",
            source_url=DIVIDENDMAX_ERNS_URL,
            confidence="forecast",
            status="forecast",
        ),
    ]
}


def normalize_distribution_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized in MANUAL_DISTRIBUTION_SCHEDULES:
        return normalized
    if not normalized.endswith(".L") and f"{normalized}.L" in MANUAL_DISTRIBUTION_SCHEDULES:
        return f"{normalized}.L"
    return normalized


def cash_like_distribution_event(
    symbol: str,
    meta: dict[str, object],
    as_of: date | None = None,
) -> DistributionEvent | None:
    normalized_symbol = normalize_distribution_symbol(symbol)
    if normalized_symbol not in CASH_LIKE_DISTRIBUTION_SYMBOLS:
        return None

    manual = manual_distribution_event(normalized_symbol, as_of=as_of)
    if manual:
        return manual
    return latest_yahoo_distribution_event(normalized_symbol, meta, as_of=as_of)


def manual_distribution_event(symbol: str, as_of: date | None = None) -> DistributionEvent | None:
    normalized_symbol = normalize_distribution_symbol(symbol)
    events = MANUAL_DISTRIBUTION_SCHEDULES.get(normalized_symbol)
    if not events:
        return None

    as_of = as_of or date.today()
    dated = sorted(
        ((event, _parse_iso_date(event.ex_date), _parse_iso_date(event.pay_date)) for event in events),
        key=lambda item: item[1] or date.max,
    )

    # Keep the most recent ex-dividend event visible until shortly after pay date,
    # because brokers may post cash distributions a few business days later.
    active_recent = [
        (event, ex_day, pay_day)
        for event, ex_day, pay_day in dated
        if ex_day is not None and ex_day <= as_of and (pay_day is None or as_of <= pay_day + timedelta(days=5))
    ]
    if active_recent:
        return max(active_recent, key=lambda item: item[1] or date.min)[0]

    upcoming = [
        (event, ex_day, pay_day)
        for event, ex_day, pay_day in dated
        if ex_day is not None and ex_day >= as_of
    ]
    if upcoming:
        return min(upcoming, key=lambda item: item[1] or date.max)[0]

    past = [(event, ex_day, pay_day) for event, ex_day, pay_day in dated if ex_day is not None and ex_day < as_of]
    if past:
        return max(past, key=lambda item: item[1] or date.min)[0]

    return None


def latest_yahoo_distribution_event(
    symbol: str,
    meta: dict[str, object],
    as_of: date | None = None,
) -> DistributionEvent | None:
    raw_events = meta.get("_dividend_events")
    if not isinstance(raw_events, list):
        return None

    parsed: list[tuple[date, str, float | None]] = []
    as_of = as_of or date.today()
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        ex_date_raw = str(item.get("ex_date") or "")
        ex_day = _parse_iso_date(ex_date_raw)
        if ex_day is None or ex_day > as_of:
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
    status_text = "已宣告" if event.status == "declared" else "预测"
    if event.pay_date or event.record_date or event.declaration_date:
        source = f"（{event.source}）" if event.source else ""
        return (
            f"现金/超短债分派周期：{status_text} {event.distribution_type} 分派，"
            f"Declaration {event.declaration_date or '待确认'}，"
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


def distribution_fields(
    symbol: str,
    meta: dict[str, object],
    as_of: date | None = None,
) -> dict[str, object]:
    if normalize_distribution_symbol(symbol) not in CASH_LIKE_DISTRIBUTION_SYMBOLS:
        return {
            "distribution_ex_date": "",
            "distribution_amount_native": None,
            "distribution_cycle_note": "",
        }

    event = cash_like_distribution_event(symbol, meta, as_of=as_of)
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


def _parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
