from __future__ import annotations

import json
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .data_sources import _read_json, _read_text


CACHE_PATH = Path("output") / "cache" / "news_monitor_cache.json"
WHITE_HOUSE_FEEDS = (
    ("白宫总统行动", "https://www.whitehouse.gov/presidential-actions/feed/"),
    ("白宫声明", "https://www.whitehouse.gov/briefing-room/statements-releases/feed/"),
)
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = (
    '"Donald Trump" (tariff OR semiconductor OR technology OR defense OR energy '
    'OR pharmaceutical OR automotive OR "stock market" OR "artificial intelligence")'
)
GOOGLE_NEWS_URL = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
    {
        "q": GDELT_QUERY,
        "hl": "en-GB",
        "gl": "GB",
        "ceid": "GB:en",
    }
)
GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"

THEMES = {
    "贸易与关税": ("tariff", "trade", "export control", "import", "customs"),
    "半导体与AI基础设施": ("semiconductor", "chip", "artificial intelligence", "ai ", "data center", "nvidia"),
    "国防与航空航天": ("defense", "defence", "military", "aerospace", "nato"),
    "能源与原油": ("oil", "energy", "gas", "drilling", "opec"),
    "医药与医疗": ("pharmaceutical", "drug", "healthcare", "medicare"),
    "汽车与工业": ("automotive", "vehicle", "car", "ev ", "manufacturing"),
    "美元、利率与流动性": (
        "dollar",
        "interest rate",
        "federal reserve",
        "treasury",
        "liquidity",
        "financial system",
        "financial technology",
        "fintech",
        "regulatory framework",
    ),
}
NEGATIVE_TERMS = (
    "tariff",
    "sanction",
    "restrict",
    "ban",
    "probe",
    "investigation",
    "threat",
    "uncertainty",
    "retaliat",
    "export control",
)
POSITIVE_TERMS = (
    "deal",
    "agreement",
    "approve",
    "support",
    "subsid",
    "investment",
    "relief",
    "exempt",
    "cut tax",
)
HIGH_IMPACT_TERMS = (
    "tariff",
    "sanction",
    "export control",
    "executive order",
    "semiconductor",
    "federal reserve",
    "oil",
    "defense",
    "defence",
)
TICKER_TERMS = {
    "DELL": ("dell",),
    "NVDA": ("nvidia",),
    "AVGO": ("broadcom",),
    "META": ("meta platforms", "facebook"),
    "MSFT": ("microsoft",),
    "AMZN": ("amazon",),
    "TSLA": ("tesla",),
    "XOM": ("exxon",),
    "CVX": ("chevron",),
    "LMT": ("lockheed",),
    "RTX": ("raytheon", "rtx"),
}


@dataclass(frozen=True)
class NewsEvent:
    title: str
    source: str
    published_at: str
    url: str
    themes: tuple[str, ...]
    tickers: tuple[str, ...]
    direction: str
    impact: str
    confidence: str
    source_type: str
    original_title: str = ""


@dataclass(frozen=True)
class NewsMonitor:
    fetched_at: str
    status: str
    summary: str
    events: tuple[NewsEvent, ...]
    warnings: tuple[str, ...]
    used_cache: bool = False


def fetch_news_monitor(now: datetime | None = None) -> NewsMonitor:
    fetched_at = now or datetime.now(timezone.utc)
    warnings: list[str] = []
    events: list[NewsEvent] = []

    for source, url in WHITE_HOUSE_FEEDS:
        try:
            events.extend(_fetch_rss(source, url))
        except Exception as exc:
            warnings.append(f"{source}暂不可用：{type(exc).__name__}")

    try:
        events.extend(_fetch_gdelt())
    except Exception as exc:
        warnings.append(f"GDELT新闻聚合暂不可用：{type(exc).__name__}")
        try:
            events.extend(_fetch_rss("Google News聚合", GOOGLE_NEWS_URL, source_type="新闻聚合"))
        except Exception as fallback_exc:
            warnings.append(f"Google News聚合暂不可用：{type(fallback_exc).__name__}")

    deduped = _dedupe_events(events)
    if deduped:
        monitor = NewsMonitor(
            fetched_at=fetched_at.isoformat(timespec="seconds"),
            status="正常" if not warnings else "部分来源不可用",
            summary=_summary(deduped),
            events=tuple(deduped[:8]),
            warnings=tuple(warnings),
        )
        _write_cache(monitor)
        return monitor

    cached = _load_cache(fetched_at)
    if cached is not None:
        return NewsMonitor(
            fetched_at=cached.fetched_at,
            status="使用缓存",
            summary=cached.summary,
            events=cached.events,
            warnings=tuple(warnings + ["实时新闻抓取失败，当前展示最近24小时内缓存。"]),
            used_cache=True,
        )

    return NewsMonitor(
        fetched_at=fetched_at.isoformat(timespec="seconds"),
        status="暂不可用",
        summary="新闻来源暂不可用；宏观评分仍基于市场价格与经济数据，不使用未经验证的新闻推断。",
        events=(),
        warnings=tuple(warnings),
    )


def classify_news_event(
    title: str,
    source: str,
    published_at: str,
    url: str,
    source_type: str,
) -> NewsEvent:
    lowered = title.lower()
    themes = tuple(label for label, keywords in THEMES.items() if any(term in lowered for term in keywords))
    tickers = tuple(ticker for ticker, terms in TICKER_TERMS.items() if any(term in lowered for term in terms))
    positive = sum(term in lowered for term in POSITIVE_TERMS)
    negative = sum(term in lowered for term in NEGATIVE_TERMS)
    if negative > positive:
        direction = "偏紧缩 / 风险溢价上行"
    elif positive > negative:
        direction = "边际支持 / 风险溢价缓和"
    else:
        direction = "方向待确认"
    impact = "高" if any(term in lowered for term in HIGH_IMPACT_TERMS) else "中"
    confidence = "高" if source_type == "政策原文" else "中"
    return NewsEvent(
        title=title.strip(),
        source=source.strip(),
        published_at=published_at.strip(),
        url=url.strip(),
        themes=themes or ("跨资产叙事",),
        tickers=tickers,
        direction=direction,
        impact=impact,
        confidence=confidence,
        source_type=source_type,
    )


def _fetch_rss(source: str, url: str, source_type: str = "政策原文") -> list[NewsEvent]:
    root = ET.fromstring(_read_text(url, timeout=15))
    events = []
    for item in root.findall(".//item")[:8]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        if title and link:
            event = classify_news_event(title, source, published, link, source_type)
            if _is_relevant_event(event):
                events.append(_translate_event_if_needed(event))
    return events


def _is_relevant_event(event: NewsEvent) -> bool:
    if event.source_type == "政策原文":
        return event.themes != ("跨资产叙事",) or bool(event.tickers)
    searchable_title = f"{event.title} {event.original_title}".lower()
    return "trump" in searchable_title or bool(event.tickers)


def _is_supported_title_language(title: str) -> bool:
    for character in title:
        if character.isascii():
            continue
        if "\u4e00" <= character <= "\u9fff":
            continue
        if unicodedata.category(character)[0] in {"P", "S", "Z"}:
            continue
        return False
    return True


def _translate_event_if_needed(event: NewsEvent) -> NewsEvent:
    if _is_supported_title_language(event.title):
        return event
    try:
        translated = _translate_title_to_english(event.title)
        if translated:
            translated_event = classify_news_event(
                translated,
                event.source,
                event.published_at,
                event.url,
                event.source_type,
            )
            return replace(translated_event, original_title=event.title)
    except Exception:
        pass
    return replace(
        event,
        title="Non-English headline; automatic translation is temporarily unavailable. Open the source link for the original.",
        original_title=event.title,
    )


def _translate_title_to_english(title: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "auto",
            "tl": "en",
            "dt": "t",
            "q": title,
        }
    )
    payload = json.loads(_read_text(f"{GOOGLE_TRANSLATE_URL}?{query}", timeout=12))
    return "".join(str(part[0]) for part in payload[0] if part and part[0]).strip()


def _fetch_gdelt() -> list[NewsEvent]:
    query = urllib.parse.urlencode(
        {
            "query": GDELT_QUERY,
            "mode": "artlist",
            "format": "json",
            "maxrecords": "25",
            "timespan": "3d",
            "sort": "datedesc",
        }
    )
    payload = _read_json(f"{GDELT_URL}?{query}", timeout=20)
    events = []
    for item in payload.get("articles", []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        source = str(item.get("domain") or item.get("sourcecountry") or "GDELT").strip()
        published = str(item.get("seendate") or "").strip()
        event = classify_news_event(title, source, published, url, "新闻聚合")
        if _is_relevant_event(event):
            events.append(_translate_event_if_needed(event))
    return events


def _dedupe_events(events: list[NewsEvent]) -> list[NewsEvent]:
    seen: set[str] = set()
    result = []
    for event in events:
        key = " ".join(event.title.lower().split())
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return sorted(result, key=lambda item: (item.impact == "高", item.published_at), reverse=True)


def _summary(events: list[NewsEvent]) -> str:
    high_impact = sum(event.impact == "高" for event in events)
    restrictive = sum(event.direction.startswith("偏紧缩") for event in events)
    themes = []
    for event in events:
        for theme in event.themes:
            if theme not in themes:
                themes.append(theme)
    theme_text = "、".join(themes[:4]) or "跨资产叙事"
    return (
        f"最近事件覆盖{theme_text}；识别到{high_impact}条高影响事件，"
        f"其中{restrictive}条带有金融条件收紧或风险溢价上行含义。"
        "新闻模块仅用于解释市场叙事，不直接改变量化评分。"
    )


def _write_cache(monitor: NewsMonitor) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(asdict(monitor), ensure_ascii=False, indent=2), encoding="utf-8")


def _load_cache(now: datetime) -> NewsMonitor | None:
    if not CACHE_PATH.exists():
        return None
    try:
        raw: dict[str, Any] = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(str(raw.get("fetched_at") or ""))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if now - fetched_at > timedelta(hours=24):
            return None
        return NewsMonitor(
            fetched_at=fetched_at.isoformat(timespec="seconds"),
            status=str(raw.get("status") or "使用缓存"),
            summary=str(raw.get("summary") or ""),
            events=tuple(
                event
                for item in raw.get("events", [])
                for event in (NewsEvent(**item),)
                if _is_relevant_event(event)
            ),
            warnings=tuple(str(item) for item in raw.get("warnings", [])),
            used_cache=True,
        )
    except Exception:
        return None
