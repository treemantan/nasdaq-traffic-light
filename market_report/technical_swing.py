from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .etf_monitor import PortfolioPosition
from .price_history import InstrumentIdentity, PriceHistory, fetch_price_history
from .technical_indicators import IndicatorSnapshot, PriceBar, indicator_snapshot


TECHNICAL_STATE_PATH = Path("output") / "cache" / "technical_swing_state.json"


@dataclass(frozen=True)
class SwingUniverseItem:
    symbol: str
    origin: str
    position: PortfolioPosition | None = None


@dataclass(frozen=True)
class SwingPivot:
    kind: str
    index: int
    price: float
    timestamp: datetime
    volume: float | None


@dataclass(frozen=True)
class SwingZone:
    kind: str
    lower: float
    upper: float
    score: int
    touches: int
    components: tuple[str, ...]


@dataclass(frozen=True)
class SwingAssessment:
    symbol: str
    origin: str
    identity: InstrumentIdentity
    current_price: float | None
    change_pct: float | None
    indicators: IndicatorSnapshot
    trend: str
    technical_status: str
    supports: tuple[SwingZone, ...]
    resistances: tuple[SwingZone, ...]
    invalidation_level: float | None
    volume_ratio: float | None
    volume_label: str
    volume_confirmation: str
    note: str
    data_source: str
    data_timestamp: str
    data_quality: str
    asset_class: str
    position_weight_pct: float | None = None
    average_cost_gbp: float | None = None
    unrealized_pnl_gbp: float | None = None
    unrealized_pnl_pct: float | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TechnicalSwingReport:
    generated_at: str
    assessments: tuple[SwingAssessment, ...] = ()
    warnings: tuple[str, ...] = ()
    summary: str = ""


def parse_ticker_list(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    parts = value.split(",") if isinstance(value, str) else value
    return tuple(
        dict.fromkeys(
            str(item).strip().upper()
            for item in parts
            if str(item).strip()
        )
    )


def resolve_swing_universe(
    holdings: Sequence[PortfolioPosition] | Sequence[str],
    watchlist: Sequence[str] | str | None,
    temporary_tickers: Sequence[str] | str | None,
) -> tuple[SwingUniverseItem, ...]:
    resolved: dict[str, SwingUniverseItem] = {}
    for holding in holdings:
        position = holding if isinstance(holding, PortfolioPosition) else None
        symbol = (holding.symbol if position else str(holding)).strip().upper()
        if symbol:
            resolved[symbol] = SwingUniverseItem(symbol, "holding", position)
    for origin, values in (
        ("watchlist", parse_ticker_list(watchlist)),
        ("temporary", parse_ticker_list(temporary_tickers)),
    ):
        for symbol in values:
            resolved.setdefault(symbol, SwingUniverseItem(symbol, origin))
    return tuple(resolved.values())


def detect_pivots(bars: Sequence[PriceBar]) -> tuple[SwingPivot, ...]:
    pivots: list[SwingPivot] = []
    for index in range(2, len(bars) - 2):
        current = bars[index]
        neighbours = (bars[index - 2], bars[index - 1], bars[index + 1], bars[index + 2])
        if all(current.low < item.low for item in neighbours):
            pivots.append(SwingPivot("support", index, current.low, current.timestamp, current.volume))
        if all(current.high > item.high for item in neighbours):
            pivots.append(SwingPivot("resistance", index, current.high, current.timestamp, current.volume))
    return tuple(pivots)


def cluster_pivots(
    pivots: Sequence[SwingPivot],
    *,
    kind: str,
    atr_value: float | None,
    current_price: float,
    bars_count: int,
) -> tuple[SwingZone, ...]:
    selected = sorted((pivot for pivot in pivots if pivot.kind == kind), key=lambda item: item.price)
    if not selected:
        return ()
    tolerance = min(atr_value or current_price * 0.02, current_price * 0.03)
    max_width = min((atr_value or current_price * 0.03) * 2, current_price * 0.06)
    clusters: list[list[SwingPivot]] = []
    for pivot in selected:
        if not clusters:
            clusters.append([pivot])
            continue
        center = sum(item.price for item in clusters[-1]) / len(clusters[-1])
        candidate_prices = [item.price for item in clusters[-1]] + [pivot.price]
        if abs(pivot.price - center) <= tolerance and max(candidate_prices) - min(candidate_prices) <= max_width:
            clusters[-1].append(pivot)
        else:
            clusters.append([pivot])
    zones = [
        _zone_from_cluster(cluster, kind, atr_value, current_price, bars_count)
        for cluster in clusters
    ]
    return tuple(sorted(zones, key=lambda zone: zone.score, reverse=True))


def _zone_from_cluster(
    cluster: Sequence[SwingPivot],
    kind: str,
    atr_value: float | None,
    current_price: float,
    bars_count: int,
) -> SwingZone:
    center = sum(item.price for item in cluster) / len(cluster)
    padding = min((atr_value or current_price * 0.02) * 0.5, current_price * 0.015)
    latest_index = max(item.index for item in cluster)
    recency = max(0, 25 - int((bars_count - 1 - latest_index) / max(bars_count, 1) * 25))
    touch_score = min(45, len(cluster) * 15)
    volume_values = [item.volume for item in cluster if item.volume is not None]
    volume_score = 10 if volume_values and max(volume_values) > sum(volume_values) / len(volume_values) else 0
    score = max(1, min(100, 20 + touch_score + recency + volume_score))
    components = (f"{len(cluster)}次触及", f"新近度+{recency}", f"成交量+{volume_score}")
    return SwingZone(kind, center - padding, center + padding, score, len(cluster), components)


def classify_trend(price: float, indicators: IndicatorSnapshot, asset_class: str = "equity") -> str:
    if asset_class == "cash_like":
        return "现金与短债结构"
    ema21, sma50, sma200 = indicators.ema21, indicators.sma50, indicators.sma200
    if None in (ema21, sma50, sma200):
        return "数据不足"
    if price > ema21 > sma50 > sma200:
        return "强势上行"
    if price < ema21 and ema21 > sma50 > sma200:
        return "上升趋势中的回调"
    if price < sma50 and ema21 < sma50 and sma50 > sma200:
        return "中期动能转弱"
    if price < ema21 < sma50 < sma200:
        return "空头结构"
    return "中性/混合"


def classify_volume(ratio: float | None) -> str:
    if ratio is None:
        return "成交量数据不足"
    if ratio < 0.7:
        return "低量"
    if ratio <= 1.2:
        return "正常"
    if ratio <= 1.5:
        return "小幅放量"
    if ratio <= 2:
        return "明显放量"
    return "异常放量"


def assess_swing(
    history: PriceHistory,
    *,
    origin: str,
    position: PortfolioPosition | None = None,
    asset_class: str = "equity",
) -> SwingAssessment:
    requested = history.identity.requested_symbol.upper()
    resolved = history.identity.resolved_symbol.upper()
    warnings = list(history.warnings)
    if requested != resolved:
        warnings.append(f"请求 ticker {requested} 与数据源返回 {resolved} 不一致，已停止技术判断。")
    bars = history.bars
    indicators = indicator_snapshot(bars)
    price = bars[-1].close
    previous = bars[-2].close if len(bars) >= 2 else None
    change_pct = ((price / previous) - 1) * 100 if previous else None
    volume_ratio = (
        bars[-1].volume / indicators.average_volume_20
        if bars[-1].volume is not None and indicators.average_volume_20
        else None
    )
    trend = classify_trend(price, indicators, asset_class)
    pivots = detect_pivots(bars)
    supports = cluster_pivots(
        pivots, kind="support", atr_value=indicators.atr14, current_price=price, bars_count=len(bars)
    )
    resistances = cluster_pivots(
        pivots, kind="resistance", atr_value=indicators.atr14, current_price=price, bars_count=len(bars)
    )
    nearest_support = _nearest_zone(supports, price, below=True)
    nearest_resistance = _nearest_zone(resistances, price, below=False)
    volume_label = classify_volume(volume_ratio)
    status = _classify_status(
        price,
        change_pct,
        nearest_support,
        nearest_resistance,
        supports,
        resistances,
        volume_ratio,
        trend,
        asset_class,
    )
    invalidation = (
        nearest_support.lower - 0.5 * indicators.atr14
        if nearest_support and indicators.atr14 is not None and asset_class != "cash_like"
        else None
    )
    confirmation = _volume_confirmation(change_pct, volume_ratio)
    note = _risk_note(asset_class, trend, status, nearest_support, nearest_resistance)
    if requested != resolved:
        status = "ticker身份待核验"
    return SwingAssessment(
        symbol=requested,
        origin=origin,
        identity=history.identity,
        current_price=price,
        change_pct=change_pct,
        indicators=indicators,
        trend=trend,
        technical_status=status,
        supports=tuple(zone for zone in supports if zone.upper <= price * 1.03)[:3],
        resistances=tuple(zone for zone in resistances if zone.lower >= price * 0.97)[:3],
        invalidation_level=invalidation,
        volume_ratio=volume_ratio,
        volume_label=volume_label,
        volume_confirmation=confirmation,
        note=note,
        data_source=history.source,
        data_timestamp=history.observation_at.isoformat() if history.observation_at else "",
        data_quality=history.quality,
        asset_class=asset_class,
        position_weight_pct=position.weight_pct if position else None,
        average_cost_gbp=position.average_cost_gbp if position else None,
        unrealized_pnl_gbp=position.unrealized_pnl_gbp if position else None,
        unrealized_pnl_pct=position.unrealized_pnl_pct if position else None,
        warnings=tuple(warnings),
    )


def build_technical_swing_report(
    positions: Sequence[PortfolioPosition],
    watchlist: Sequence[str] | str | None,
    temporary_tickers: Sequence[str] | str | None = None,
    *,
    fetcher: Callable[[str], PriceHistory] | None = None,
    asset_classes: dict[str, str] | None = None,
) -> TechnicalSwingReport:
    universe = resolve_swing_universe(positions, watchlist, temporary_tickers)
    fetch = fetcher or (lambda symbol: fetch_price_history(symbol, period="2y", interval="1d"))
    classes = {key.upper(): value for key, value in (asset_classes or {}).items()}
    assessments: list[SwingAssessment] = []
    warnings: list[str] = []
    for item in universe:
        try:
            asset_class = classes.get(item.symbol) or _infer_asset_class(item)
            assessment = assess_swing(
                fetch(item.symbol),
                origin=item.origin,
                position=item.position,
                asset_class=asset_class,
            )
            assessments.append(assessment)
            warnings.extend(assessment.warnings)
        except Exception as exc:
            warnings.append(f"{item.symbol} 技术分析暂不可用：{type(exc).__name__}: {exc}")
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = (
        f"已分析{len(assessments)}个标的，其中持仓"
        f"{sum(item.origin == 'holding' for item in assessments)}个、观察池"
        f"{sum(item.origin != 'holding' for item in assessments)}个。"
    )
    report = TechnicalSwingReport(generated_at, tuple(assessments), tuple(dict.fromkeys(warnings)), summary)
    save_technical_state(report)
    return report


def save_technical_state(report: TechnicalSwingReport, path: Path = TECHNICAL_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    public_state = {
        "generated_at": report.generated_at,
        "assessments": [
            {
                "symbol": item.symbol,
                "trend": item.trend,
                "technical_status": item.technical_status,
                "supports": [asdict(zone) for zone in item.supports],
                "resistances": [asdict(zone) for zone in item.resistances],
                "data_timestamp": item.data_timestamp,
            }
            for item in report.assessments
        ],
    }
    path.write_text(json.dumps(public_state, ensure_ascii=False, indent=2), encoding="utf-8")


def technical_swing_from_payload(raw: dict) -> TechnicalSwingReport:
    assessments = []
    for item in raw.get("assessments") or []:
        if not isinstance(item, dict):
            continue
        identity_raw = item.get("identity") or {}
        indicators_raw = item.get("indicators") or {}
        assessments.append(
            SwingAssessment(
                symbol=str(item.get("symbol") or ""),
                origin=str(item.get("origin") or "watchlist"),
                identity=InstrumentIdentity(
                    requested_symbol=str(identity_raw.get("requested_symbol") or item.get("symbol") or ""),
                    resolved_symbol=str(identity_raw.get("resolved_symbol") or item.get("symbol") or ""),
                    name=str(identity_raw.get("name") or item.get("symbol") or ""),
                    exchange=str(identity_raw.get("exchange") or ""),
                    currency=str(identity_raw.get("currency") or ""),
                    instrument_type=str(identity_raw.get("instrument_type") or ""),
                ),
                current_price=_optional_float(item.get("current_price")),
                change_pct=_optional_float(item.get("change_pct")),
                indicators=IndicatorSnapshot(
                    ema21=_optional_float(indicators_raw.get("ema21")),
                    sma50=_optional_float(indicators_raw.get("sma50")),
                    sma200=_optional_float(indicators_raw.get("sma200")),
                    atr14=_optional_float(indicators_raw.get("atr14")),
                    rsi14=_optional_float(indicators_raw.get("rsi14")),
                    average_volume_20=_optional_float(indicators_raw.get("average_volume_20")),
                ),
                trend=str(item.get("trend") or "数据不足"),
                technical_status=str(item.get("technical_status") or "中性"),
                supports=_zones_from_payload(item.get("supports")),
                resistances=_zones_from_payload(item.get("resistances")),
                invalidation_level=_optional_float(item.get("invalidation_level")),
                volume_ratio=_optional_float(item.get("volume_ratio")),
                volume_label=str(item.get("volume_label") or "成交量数据不足"),
                volume_confirmation=str(item.get("volume_confirmation") or "量价确认不足"),
                note=str(item.get("note") or ""),
                data_source=str(item.get("data_source") or ""),
                data_timestamp=str(item.get("data_timestamp") or ""),
                data_quality=str(item.get("data_quality") or "unknown"),
                asset_class=str(item.get("asset_class") or "equity"),
                position_weight_pct=_optional_float(item.get("position_weight_pct")),
                average_cost_gbp=_optional_float(item.get("average_cost_gbp")),
                unrealized_pnl_gbp=_optional_float(item.get("unrealized_pnl_gbp")),
                unrealized_pnl_pct=_optional_float(item.get("unrealized_pnl_pct")),
                warnings=tuple(str(value) for value in (item.get("warnings") or [])),
            )
        )
    return TechnicalSwingReport(
        generated_at=str(raw.get("generated_at") or datetime.now(timezone.utc).isoformat()),
        assessments=tuple(assessments),
        warnings=tuple(str(value) for value in (raw.get("warnings") or [])),
        summary=str(raw.get("summary") or ""),
    )


def render_technical_swing_html(report: TechnicalSwingReport) -> str:
    holding_cards = "".join(
        _standalone_card(item)
        for item in report.assessments
        if item.origin == "holding"
    ) or "<p>当前没有可分析的持仓。</p>"
    watch_cards = "".join(
        _standalone_card(item)
        for item in report.assessments
        if item.origin != "holding"
    ) or "<p>本次没有提供额外观察标的。</p>"
    warnings = "".join(f"<li>{escape(item)}</li>" for item in report.warnings[:20])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>技术波段观察</title>
</head>
<body style="margin:0;background:#0b1017;color:#e5e7eb;font-family:Arial,'Microsoft YaHei',sans-serif;">
  <main style="max-width:1080px;margin:0 auto;padding:28px 18px 48px;">
    <h1 style="margin:0 0 8px;color:#f8fafc;">技术波段观察</h1>
    <p style="color:#9ca3af;">{escape(report.summary)} 数据生成时间：{escape(report.generated_at)}</p>
    <p style="padding:12px;background:#111827;border:1px solid #334155;">本模块用于观察支撑、阻力、趋势确认与失效条件，不构成直接买卖指令。日线突破优先等待收盘与后续 2–3 个交易日确认。</p>
    <h2>持仓技术分析</h2>
    <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px;">{holding_cards}</section>
    <h2 style="margin-top:28px;">观察池技术分析</h2>
    <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px;">{watch_cards}</section>
    <h2 style="margin-top:28px;">数据质量与回退说明</h2>
    <ul>{warnings or "<li>未发现额外数据警告。</li>"}</ul>
  </main>
</body>
</html>"""


def render_technical_swing_email(
    report: TechnicalSwingReport,
) -> tuple[str, str, str]:
    report_date = report.generated_at[:10]
    subject = f"技术波段观察 - {report_date}"
    rows = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #334155;'><strong>{escape(item.symbol)}</strong></td>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;'>{escape(item.trend)}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;'>{escape(item.technical_status)}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;'>{escape(item.volume_label)}</td></tr>"
        for item in report.assessments
    )
    html = f"""<!doctype html><html lang="zh-CN"><body style="margin:0;background:#0b1017;color:#e5e7eb;font-family:Arial,'Microsoft YaHei',sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:720px;max-width:100%;background:#111827;border:1px solid #334155;">
<tr><td style="padding:20px;"><h1 style="margin:0 0 8px;color:#f8fafc;">技术波段观察</h1>
<p style="color:#9ca3af;">{escape(report.summary)}</p>
<table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:13px;">
<tr><th align="left" style="padding:8px;border-bottom:1px solid #64748b;">标的</th><th align="left">趋势</th><th align="left">状态</th><th align="left">量能</th></tr>{rows}</table>
<p style="color:#9ca3af;">完整技术分析已作为 HTML 附件提供；本模块仅用于风险观察和入场准备，不构成交易建议。</p>
</td></tr></table></td></tr></table></body></html>"""
    text = "\n".join(
        [subject, report.summary]
        + [
            f"- {item.symbol}: {item.trend}; {item.technical_status}; {item.volume_label}"
            for item in report.assessments
        ]
        + ["完整报告见 HTML 附件。"]
    )
    return subject, html, text


def write_technical_swing_report(
    report: TechnicalSwingReport, output_dir: Path
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_date = report.generated_at[:10]
    html_path = output_dir / f"technical-swing-report-{report_date}.html"
    json_path = output_dir / f"technical-swing-report-{report_date}.json"
    html_path.write_text(render_technical_swing_html(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return html_path, json_path


def _standalone_card(item: SwingAssessment) -> str:
    support = _nearest_zone(item.supports, item.current_price or 0, below=True)
    resistance = _nearest_zone(item.resistances, item.current_price or 0, below=False)
    support_text = _zone_text(support)
    resistance_text = _zone_text(resistance)
    price = f"{item.current_price:.2f}" if item.current_price is not None else "N/A"
    invalidation = (
        f"{item.invalidation_level:.2f}"
        if item.invalidation_level is not None
        else "不适用"
    )
    pnl = (
        f"<div>持仓盈亏：{item.unrealized_pnl_pct:+.2f}%</div>"
        if item.unrealized_pnl_pct is not None
        else ""
    )
    return f"""<article style="background:#111827;border:1px solid #334155;padding:14px;">
      <h3 style="margin:0 0 8px;color:#f8fafc;">{escape(item.symbol)} · {escape(item.technical_status)}</h3>
      <div>当前价格：{price} {escape(item.identity.currency)}</div>
      {pnl}
      <div>趋势：{escape(item.trend)}</div>
      <div>EMA21 / SMA50 / SMA200：{_fmt_optional(item.indicators.ema21)} / {_fmt_optional(item.indicators.sma50)} / {_fmt_optional(item.indicators.sma200)}</div>
      <div>ATR14 / RSI14：{_fmt_optional(item.indicators.atr14)} / {_fmt_optional(item.indicators.rsi14)}</div>
      <div>量能：{escape(item.volume_label)}；{escape(item.volume_confirmation)}</div>
      <div>最近支撑：{support_text}</div>
      <div>最近阻力：{resistance_text}</div>
      <div>ATR 失效参考：{invalidation}</div>
      <p style="color:#bfdbfe;">{escape(item.note)}</p>
      <div style="font-size:12px;color:#9ca3af;">{escape(item.data_source)} · {escape(item.data_timestamp)} · {escape(item.data_quality)}</div>
    </article>"""


def _zones_from_payload(raw: object) -> tuple[SwingZone, ...]:
    return tuple(
        SwingZone(
            kind=str(item.get("kind") or ""),
            lower=float(item.get("lower") or 0),
            upper=float(item.get("upper") or 0),
            score=int(item.get("score") or 0),
            touches=int(item.get("touches") or 0),
            components=tuple(str(value) for value in (item.get("components") or [])),
        )
        for item in (raw or [])
        if isinstance(item, dict)
    )


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_optional(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "N/A"


def _zone_text(zone: SwingZone | None) -> str:
    if zone is None:
        return "N/A"
    return f"{zone.lower:.2f}–{zone.upper:.2f}（{zone.score}/100）"


def _infer_asset_class(item: SwingUniverseItem) -> str:
    if item.symbol in {"ERNS.L"}:
        return "cash_like"
    return "equity"


def _nearest_zone(zones: Sequence[SwingZone], price: float, *, below: bool) -> SwingZone | None:
    candidates = [
        zone for zone in zones
        if (zone.lower <= price if below else zone.upper >= price)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda zone: abs(((zone.lower + zone.upper) / 2) - price))


def _classify_status(
    price: float,
    change_pct: float | None,
    support: SwingZone | None,
    resistance: SwingZone | None,
    supports: Sequence[SwingZone],
    resistances: Sequence[SwingZone],
    volume_ratio: float | None,
    trend: str,
    asset_class: str,
) -> str:
    if asset_class == "cash_like":
        return "收益率与净值路径观察"
    broken_resistance = max(
        (zone for zone in resistances if price > zone.upper),
        key=lambda zone: zone.upper,
        default=None,
    )
    broken_support = min(
        (zone for zone in supports if price < zone.lower),
        key=lambda zone: zone.lower,
        default=None,
    )
    if broken_resistance and (volume_ratio or 0) > 1:
        return "突破候选"
    if broken_support and (volume_ratio or 0) > 1:
        return "支撑失效"
    if support and abs(price - support.upper) / price <= 0.02:
        return "接近支撑"
    if resistance and abs(resistance.lower - price) / price <= 0.02:
        return "接近阻力"
    if trend == "上升趋势中的回调":
        return "趋势回踩"
    if trend in {"中期动能转弱", "空头结构"}:
        return "趋势修复观察"
    if change_pct is not None and abs(change_pct) >= 3:
        return "波动扩张观察"
    return "中性"


def _volume_confirmation(change_pct: float | None, ratio: float | None) -> str:
    if change_pct is None or ratio is None:
        return "量价确认不足"
    if change_pct > 0 and ratio > 1.2:
        return "上涨伴随放量，动能确认较强"
    if change_pct > 0 and ratio < 0.7:
        return "上涨但成交偏低，需防弱反弹"
    if change_pct < 0 and ratio > 1.2:
        return "下跌伴随放量，卖压确认较强"
    if change_pct < 0 and ratio < 0.7:
        return "缩量回调，暂未形成强卖压确认"
    return "成交量处于常态区间"


def _risk_note(
    asset_class: str,
    trend: str,
    status: str,
    support: SwingZone | None,
    resistance: SwingZone | None,
) -> str:
    if asset_class == "cash_like":
        return "超短债应重点观察收益率、久期、派息与净值回补，不使用权益趋势破坏语言。"
    if status == "支撑失效":
        return "日线收盘已跌破支撑区且量能扩张，需等待重新站回或形成新的稳定区间。"
    if status == "突破候选":
        return "当前仅为突破候选，优先观察2至3个交易日能否守住原阻力区。"
    if support:
        return f"最近支撑区强度{support.score}/100；结合趋势与量能观察是否形成有效承接。"
    if resistance:
        return f"最近阻力区强度{resistance.score}/100；未确认突破前不应把盘中刺穿视为趋势成立。"
    return f"当前为{trend}，历史枢轴不足时应降低技术结论置信度。"
