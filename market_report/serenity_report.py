from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SerenitySource:
    label: str
    url: str
    note: str = ""


@dataclass(frozen=True)
class SerenityFocusHolding:
    symbol: str
    weight_pct: float
    priority_reason: str
    framework_fit: str
    bottleneck_assessment: str
    current_state: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
    catalysts: list[str] = field(default_factory=list)
    falsification_conditions: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    sources: list[SerenitySource] = field(default_factory=list)


@dataclass(frozen=True)
class SerenityPortfolioReport:
    report_date: str
    title: str
    conclusion: str
    macro_context: str
    portfolio_value_gbp: float | None
    portfolio_observations: list[str]
    concentration_observations: list[str]
    focus_holdings: list[SerenityFocusHolding]
    review_note: str = "[自查复核，非独立实例]"
    disclaimer: str = "本报告仅用于研究与风险复核，属于非投资建议，不构成任何买卖指令。"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_AI_INFRA_SYMBOLS = {
    "NVDA",
    "AVGO",
    "AMD",
    "TSM",
    "ASML",
    "MU",
    "MRVL",
    "ANET",
    "LITE",
    "COHR",
    "AAOI",
    "MTSI",
    "MXL",
    "AXTI",
    "SEMI",
    "CHIP",
}

_FRAMEWORK_PROFILES = {
    "NVDA": (
        "较高",
        "位于AI算力加速器核心层，卡点判断应重点验证先进制程、HBM、封装、网络与客户资本开支能否继续共同支撑供给稀缺性。",
    ),
    "AVGO": (
        "较高",
        "位于定制计算与高速网络连接层，卡点判断应验证客户集中度、设计导入延续性及交换芯片和光互联需求。",
    ),
    "SEMI": (
        "中等",
        "半导体ETF覆盖多个供应链环节，能够分散单点风险，但组合层面的卡点纯度取决于底层持仓与权重。",
    ),
    "CHIP": (
        "中等",
        "半导体ETF覆盖多个供应链环节，能够分散单点风险，但组合层面的卡点纯度取决于底层持仓与权重。",
    ),
    "META": (
        "中等",
        "属于AI基础设施需求方而非上游卡点本身，重点观察资本开支、算力利用率与广告现金流能否形成闭环。",
    ),
    "RKLB": (
        "中等",
        "处于航天系统与发射服务链条，需验证制造能力、任务可靠性、积压订单质量和资本消耗。",
    ),
    "VUAG": (
        "有限",
        "宽基指数ETF不是单一供应链卡点标的，Serenity框架主要用于检查内部集中度、估值拉伸和共同宏观风险。",
    ),
    "VWRL": (
        "有限",
        "宽基指数ETF不是单一供应链卡点标的，Serenity框架主要用于检查内部集中度、估值拉伸和共同宏观风险。",
    ),
    "CNX1": (
        "有限",
        "指数ETF覆盖多个商业模式，无法用单一物理卡点解释；更适合观察盈利集中度、久期暴露和AI权重拥挤。",
    ),
    "ISF": (
        "有限",
        "宽基指数ETF不是单一供应链卡点标的，Serenity框架主要用于检查行业集中度和英国市场盈利结构。",
    ),
    "ERNS": (
        "有限",
        "现金与超短债工具不适用供应链卡点分析，应改看收益率曲线、久期、信用质量、分派和流动性。",
    ),
    "IGTM": (
        "有限",
        "债券ETF不适用供应链卡点分析，应改看久期、实际利率、信用质量与英镑对冲效果。",
    ),
}


def build_serenity_report(payload: dict[str, Any], focus_limit: int = 5) -> SerenityPortfolioReport:
    monitor = payload.get("etf_monitor") or {}
    positions = [
        item for item in (monitor.get("portfolio_positions") or []) if isinstance(item, dict)
    ]
    assets: dict[str, dict[str, Any]] = {}
    for item in (monitor.get("assets") or []):
        if not isinstance(item, dict) or not item.get("symbol"):
            continue
        symbol = str(item["symbol"]).upper()
        assets[symbol] = item
        assets.setdefault(_symbol_key(symbol), item)
    events = [
        item
        for item in ((payload.get("portfolio_event_monitor") or {}).get("events") or [])
        if isinstance(item, dict)
    ]
    news = [
        item
        for item in ((payload.get("news_monitor") or {}).get("events") or [])
        if isinstance(item, dict)
    ]

    ranked = sorted(
        positions,
        key=lambda item: (
            -_research_priority(item, assets.get(_symbol_key(item.get("symbol"))), events),
            -_number(item.get("weight_pct")),
            str(item.get("symbol") or ""),
        ),
    )
    limit = min(5, max(3, focus_limit))
    focus = [
        _build_focus_holding(item, assets, events, news)
        for item in ranked[: min(limit, len(ranked))]
    ]

    regime = payload.get("regime") or {}
    regime_label = str(regime.get("label") or "宏观状态待确认")
    regime_summary = str(regime.get("summary") or "")
    macro_context = f"{regime_label}。{regime_summary}".strip("。") + "。"
    warnings = [str(item) for item in (monitor.get("portfolio_warnings") or []) if item]
    summary = [str(item) for item in (monitor.get("portfolio_summary") or []) if item]
    exposures = [
        item for item in (monitor.get("portfolio_exposures") or []) if isinstance(item, dict)
    ]
    concentration = [
        f"{item.get('label') or item.get('symbol')}综合暴露约{_number(item.get('weight_pct')):.1f}%"
        for item in sorted(exposures, key=lambda row: -_number(row.get("weight_pct")))[:5]
    ]
    concentration.extend(
        str(item) for item in (monitor.get("portfolio_exposure_notes") or []) if item
    )
    red_count = sum(_is_red_alert(item) for item in positions)
    ai_count = sum(_is_ai_related(item, assets.get(_symbol_key(item.get("symbol")))) for item in positions)
    conclusion = (
        f"本周组合需要优先复核{red_count}个红色回撤或趋势破坏持仓；"
        f"另有{ai_count}个持仓与AI、半导体或相关资本开支链条存在直接或间接联系。"
        "重点不是预测下周涨跌，而是检查原有论点是否仍有证据支撑。"
    )

    return SerenityPortfolioReport(
        report_date=str(payload.get("report_date") or datetime.now().date().isoformat()),
        title="Serenity 私人持仓周报",
        conclusion=conclusion,
        macro_context=macro_context,
        portfolio_value_gbp=_optional_number(monitor.get("portfolio_total_value_gbp")),
        portfolio_observations=(warnings + summary)[:10],
        concentration_observations=concentration[:8],
        focus_holdings=focus,
    )


def render_serenity_html(report: SerenityPortfolioReport) -> str:
    focus_html = "".join(_render_holding(item) for item in report.focus_holdings)
    value = (
        f"£{report.portfolio_value_gbp:,.2f}"
        if report.portfolio_value_gbp is not None
        else "N/A"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{escape(report.title)} - {escape(report.report_date)}</title>
</head>
<body style="margin:0;background:#0b1017;color:#e5e7eb;font-family:Arial,'Microsoft YaHei',sans-serif;">
  <div style="max-width:980px;margin:0 auto;padding:28px 18px 40px;">
    <header style="border-bottom:1px solid #334155;padding-bottom:18px;margin-bottom:18px;">
      <div style="font-size:13px;color:#93a4b8;">Macro Regime Radar · 私人周度研究</div>
      <h1 style="font-size:30px;margin:7px 0 6px;color:#f8fafc;">{escape(report.title)}</h1>
      <div style="color:#9ca3af;">{escape(report.report_date)} · 组合参考市值 {escape(value)}</div>
    </header>
    {_panel("本周结论", f"<p>{escape(report.conclusion)}</p><p><strong>宏观背景：</strong>{escape(report.macro_context)}</p>")}
    {_panel("组合层面风险", _list_html(report.portfolio_observations))}
    {_panel("集中度与共同驱动", _list_html(report.concentration_observations))}
    <h2 style="font-size:22px;margin:28px 0 12px;color:#f8fafc;">重点持仓复核</h2>
    {focus_html}
    {_panel("复核说明", f"<p>{escape(report.review_note)}</p><p>{escape(report.disclaimer)}</p>")}
  </div>
</body>
</html>"""


def render_serenity_email(report: SerenityPortfolioReport) -> tuple[str, str, str]:
    subject = f"Serenity Portfolio Weekly - {report.report_date}"
    focus_rows = "".join(
        "<tr>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;color:#f8fafc;font-weight:700;'>{escape(item.symbol)}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;'>{item.weight_pct:.1f}%</td>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;'>{escape(item.priority_reason)}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #334155;'>{escape(item.framework_fit)}</td>"
        "</tr>"
        for item in report.focus_holdings
    )
    html = f"""<!doctype html>
<html lang="zh-CN"><body style="margin:0;background:#0b1017;color:#e5e7eb;font-family:Arial,'Microsoft YaHei',sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:720px;max-width:100%;background:#111827;border:1px solid #334155;">
<tr><td style="padding:20px;">
<h1 style="font-size:24px;margin:0 0 8px;color:#f8fafc;">{escape(report.title)}</h1>
<p style="color:#9ca3af;margin:0 0 16px;">{escape(report.report_date)} · 私人持仓周度复核</p>
<p style="line-height:1.6;"><strong>本周结论：</strong>{escape(report.conclusion)}</p>
<p style="line-height:1.6;"><strong>宏观背景：</strong>{escape(report.macro_context)}</p>
<table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:13px;">
<tr><th align="left" style="padding:8px;border-bottom:1px solid #64748b;">标的</th>
<th align="left" style="padding:8px;border-bottom:1px solid #64748b;">权重</th>
<th align="left" style="padding:8px;border-bottom:1px solid #64748b;">入选原因</th>
<th align="left" style="padding:8px;border-bottom:1px solid #64748b;">框架适用性</th></tr>
{focus_rows}</table>
<p style="color:#9ca3af;margin-top:18px;">完整报告已作为HTML附件提供，包含风险、支持证据、催化剂、证伪条件和来源链接。</p>
<p style="color:#9ca3af;">{escape(report.disclaimer)}</p>
</td></tr></table></td></tr></table></body></html>"""
    text_lines = [
        subject,
        report.conclusion,
        f"宏观背景：{report.macro_context}",
        "重点持仓：",
    ]
    text_lines.extend(
        f"- {item.symbol} ({item.weight_pct:.1f}%): {item.priority_reason}"
        for item in report.focus_holdings
    )
    text_lines.extend(["完整报告见HTML附件。", report.disclaimer])
    return subject, html, "\n".join(text_lines)


def write_serenity_report(
    report: SerenityPortfolioReport, output_dir: Path
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"serenity-report-{report.report_date}.html"
    json_path = output_dir / f"serenity-report-{report.report_date}.json"
    html_path.write_text(render_serenity_html(report), encoding="utf-8")
    import json

    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return html_path, json_path


def _build_focus_holding(
    position: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
    news: list[dict[str, Any]],
) -> SerenityFocusHolding:
    symbol = str(position.get("symbol") or "N/A").upper()
    key = _symbol_key(symbol)
    asset = assets.get(symbol) or assets.get(key) or {}
    related_events = [item for item in events if key in _event_symbols(item)]
    related_news = [item for item in news if key in _event_symbols(item)]
    framework_fit, bottleneck = _framework_profile(key, asset)
    risks = _holding_risks(position, asset)
    support = _holding_support(position, asset)
    catalysts = _holding_catalysts(related_events, related_news)
    sources = _holding_sources(related_events, related_news)
    gaps = []
    if not sources:
        gaps.append("本周结构化数据未提供该标的的一手公司事件来源，需人工复核IR、监管披露和财报电话会。")
    if framework_fit == "有限":
        gaps.append("该标的不宜强行套用单一供应链卡点叙事，应以资产属性和组合角色为主。")
    if any("cache:" in str(position.get("price_source") or "").lower() for _ in [0]):
        gaps.append("价格使用最近有效缓存，周报结论不应被视为实时行情判断。")
    return SerenityFocusHolding(
        symbol=symbol,
        weight_pct=_number(position.get("weight_pct")),
        priority_reason=_priority_reason(position, asset, related_events),
        framework_fit=framework_fit,
        bottleneck_assessment=bottleneck,
        current_state=_holding_state(position, asset),
        risks=risks or ["暂未发现明确结构性红旗，但仍需检查数据完整性与仓位集中度。"],
        supporting_evidence=support or ["现有结构化数据不足以确认明确的正向卡点优势。"],
        catalysts=catalysts or ["本周未识别到已登记的直接催化剂。"],
        falsification_conditions=_falsification_conditions(key, position, asset, framework_fit),
        evidence_gaps=gaps,
        sources=sources,
    )


def _research_priority(
    position: dict[str, Any],
    asset: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> float:
    score = _number(position.get("weight_pct"))
    key = _symbol_key(position.get("symbol"))
    if _is_red_alert(position):
        score += 120
    elif _number(position.get("drawdown_from_year_peak_pct")) <= -_number(
        position.get("yellow_drawdown_threshold_pct"), 5
    ):
        score += 45
    if "趋势破坏" in str(position.get("drawdown_regime") or ""):
        score += 50
    if _is_ai_related(position, asset):
        score += 28
    if any(key in _event_symbols(item) for item in events):
        score += 25
    if asset and _number(asset.get("crowding_score")) >= 70:
        score += 12
    return score


def _is_red_alert(position: dict[str, Any]) -> bool:
    drawdown = _optional_number(position.get("drawdown_from_year_peak_pct"))
    threshold = _number(position.get("red_drawdown_threshold_pct"), 10)
    return (
        (drawdown is not None and drawdown <= -threshold)
        or "趋势破坏" in str(position.get("drawdown_regime") or "")
    )


def _is_ai_related(position: dict[str, Any], asset: dict[str, Any] | None) -> bool:
    key = _symbol_key(position.get("symbol"))
    theme = str((asset or {}).get("theme") or "").lower()
    return key in _AI_INFRA_SYMBOLS or any(
        token in theme for token in ("semiconductor", "artificial intelligence", "ai ", "cloud")
    )


def _framework_profile(key: str, asset: dict[str, Any]) -> tuple[str, str]:
    if key in _FRAMEWORK_PROFILES:
        return _FRAMEWORK_PROFILES[key]
    theme = str(asset.get("theme") or "")
    lowered = theme.lower()
    if any(token in lowered for token in ("semiconductor", "photon", "ai infrastructure")):
        return (
            "中等",
            f"{theme or '该主题'}与AI基础设施供应链相关，但需要穿透底层持仓后才能判断真正的卡点纯度。",
        )
    return (
        "有限",
        "现有数据不足以确认该标的是物理供应链卡点；应先验证商业模式、客户依赖、替代路径和资本约束。",
    )


def _holding_state(position: dict[str, Any], asset: dict[str, Any]) -> list[str]:
    items = [
        f"组合权重约{_number(position.get('weight_pct')):.1f}%，未实现收益率{_fmt_pct(position.get('unrealized_pnl_pct'))}。",
        f"距年内高点{_fmt_pct(position.get('drawdown_from_year_peak_pct'))}，距SMA200 {_fmt_pct(position.get('distance_sma200_pct'))}。",
    ]
    if asset:
        items.append(
            f"新增仓位环境{int(_number(asset.get('entry_score'), 50))}/100，"
            f"拥挤度{int(_number(asset.get('crowding_score'), 50))}/100。"
        )
    return items


def _holding_risks(position: dict[str, Any], asset: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    drawdown = _optional_number(position.get("drawdown_from_year_peak_pct"))
    red = _number(position.get("red_drawdown_threshold_pct"), 10)
    if drawdown is not None and drawdown <= -red:
        risks.append(f"回撤{drawdown:.1f}%已越过自适应红色阈值-{red:.1f}%，需先解释价格为何偏离原有论点。")
    if _number(position.get("distance_sma200_pct")) < 0:
        risks.append("价格位于SMA200下方，趋势确认不足，反弹不等于基本面已经修复。")
    crowding = _optional_number(asset.get("crowding_score"))
    if crowding is not None and crowding >= 70:
        risks.append(f"拥挤度{crowding:.0f}/100，正向叙事可能已被较充分定价。")
    if asset.get("valuation_label"):
        risks.append(str(asset["valuation_label"]))
    risks.extend(str(item) for item in (asset.get("warnings") or [])[:2] if item)
    return risks[:6]


def _holding_support(position: dict[str, Any], asset: dict[str, Any]) -> list[str]:
    support: list[str] = []
    if _number(position.get("unrealized_pnl_pct")) > 0:
        support.append(f"当前未实现收益率仍为{_fmt_pct(position.get('unrealized_pnl_pct'))}，持仓尚有成本缓冲。")
    if _number(position.get("distance_sma200_pct")) > 0:
        support.append(f"价格仍高于SMA200 {_fmt_pct(position.get('distance_sma200_pct'))}，中期趋势尚未失守。")
    if _number(asset.get("entry_score")) >= 70:
        support.append(str(asset.get("entry_label") or "当前趋势结构仍相对完整。"))
    if asset.get("risk_management_note"):
        support.append(str(asset["risk_management_note"]))
    return support[:5]


def _holding_catalysts(
    events: list[dict[str, Any]], news: list[dict[str, Any]]
) -> list[str]:
    catalysts = []
    for item in events[:3]:
        timing = item.get("event_time_label") or item.get("event_at") or "时间待确认"
        catalysts.append(f"{item.get('title', '事件待确认')}（{timing}；{item.get('status', '状态待确认')}）")
    for item in news[:2]:
        catalysts.append(
            f"{item.get('title', '相关新闻')}（方向：{item.get('direction', '待确认')}；可信度：{item.get('confidence', '待确认')}）"
        )
    return catalysts[:5]


def _holding_sources(
    events: list[dict[str, Any]], news: list[dict[str, Any]]
) -> list[SerenitySource]:
    sources: list[SerenitySource] = []
    seen = set()
    for item in events:
        url = str(item.get("source_url") or "")
        if url and url not in seen:
            seen.add(url)
            sources.append(
                SerenitySource(
                    label=str(item.get("source_label") or item.get("title") or "事件来源"),
                    url=url,
                    note=str(item.get("status") or ""),
                )
            )
    for item in news:
        url = str(item.get("url") or "")
        if url and url not in seen:
            seen.add(url)
            sources.append(
                SerenitySource(
                    label=str(item.get("source") or item.get("title") or "新闻来源"),
                    url=url,
                    note=str(item.get("title") or ""),
                )
            )
    return sources[:6]


def _falsification_conditions(
    key: str,
    position: dict[str, Any],
    asset: dict[str, Any],
    framework_fit: str,
) -> list[str]:
    conditions = []
    if framework_fit in {"较高", "中等"}:
        conditions.extend(
            [
                "下游资本开支或订单增长持续放缓，且供应紧张未再转化为定价权。",
                "替代技术、第二供应商或客户自研显著降低该环节的不可替代性。",
            ]
        )
    else:
        conditions.append("盈利广度、现金流或资产属性不再支持其在组合中的既定角色。")
    if _number(position.get("distance_sma200_pct")) >= 0:
        conditions.append("价格跌破长期趋势后无法修复，同时基本面预期继续下调。")
    else:
        conditions.append("价格持续位于长期趋势下方，且后续事件没有带来盈利或现金流预期修复。")
    if _number(asset.get("crowding_score")) >= 70:
        conditions.append("拥挤交易解除时，估值压缩速度快于盈利兑现速度。")
    return conditions[:4]


def _priority_reason(
    position: dict[str, Any],
    asset: dict[str, Any],
    events: list[dict[str, Any]],
) -> str:
    reasons = []
    if _is_red_alert(position):
        reasons.append("红色回撤/趋势破坏")
    if _is_ai_related(position, asset):
        reasons.append("AI或半导体链")
    if events:
        reasons.append("临近事件窗口")
    if _number(position.get("weight_pct")) >= 10:
        reasons.append("组合核心仓位")
    if _number(asset.get("crowding_score")) >= 70:
        reasons.append("拥挤度偏高")
    return "、".join(reasons) or "组合权重与风险贡献"


def _event_symbols(item: dict[str, Any]) -> set[str]:
    values = item.get("symbols")
    if not isinstance(values, list):
        values = item.get("tickers")
    if not isinstance(values, list):
        values = []
    return {_symbol_key(value) for value in values}


def _symbol_key(value: object) -> str:
    return str(value or "").upper().split(".", 1)[0]


def _number(value: object, default: float = 0.0) -> float:
    result = _optional_number(value)
    return default if result is None else result


def _optional_number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: object) -> str:
    number = _optional_number(value)
    return "N/A" if number is None else f"{number:+.1f}%"


def _list_html(items: list[str]) -> str:
    if not items:
        items = ["暂未识别到明确项目。"]
    return "<ul style='margin:0;padding-left:20px;'>" + "".join(
        f"<li style='margin:6px 0;'>{escape(str(item))}</li>" for item in items
    ) + "</ul>"


def _panel(title: str, body: str) -> str:
    return (
        "<section style='border:1px solid #334155;background:#111827;padding:16px;"
        "margin:12px 0;border-radius:6px;'>"
        f"<h2 style='font-size:18px;margin:0 0 10px;color:#f8fafc;'>{escape(title)}</h2>"
        f"{body}</section>"
    )


def _render_holding(item: SerenityFocusHolding) -> str:
    source_html = (
        "<ul style='margin:0;padding-left:20px;'>"
        + "".join(
            f"<li style='margin:5px 0;'><a style='color:#7dd3fc;' href='{escape(source.url, quote=True)}'>"
            f"{escape(source.label)}</a>{' · ' + escape(source.note) if source.note else ''}</li>"
            for source in item.sources
        )
        + "</ul>"
        if item.sources
        else "<p style='color:#fbbf24;'>暂无结构化来源链接，需人工补充一手材料。</p>"
    )
    return f"""<article style="border:1px solid #334155;background:#111827;margin:14px 0;padding:18px;border-radius:6px;">
      <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start;">
        <div><h3 style="font-size:20px;margin:0;color:#f8fafc;">{escape(item.symbol)}</h3>
        <div style="color:#9ca3af;margin-top:4px;">权重 {item.weight_pct:.1f}% · {escape(item.priority_reason)}</div></div>
        <div style="color:#93c5fd;">卡点框架适用性：{escape(item.framework_fit)}</div>
      </div>
      <p style="line-height:1.6;"><strong>卡点定位：</strong>{escape(item.bottleneck_assessment)}</p>
      <h4 style="color:#fca5a5;margin-bottom:6px;">主要风险与反证</h4>{_list_html(item.risks)}
      <h4 style="color:#86efac;margin-bottom:6px;">支持逻辑与观察线索</h4>{_list_html(item.supporting_evidence)}
      <h4 style="margin-bottom:6px;">当前状态</h4>{_list_html(item.current_state)}
      <h4 style="margin-bottom:6px;">未来催化剂与复核窗口</h4>{_list_html(item.catalysts)}
      <h4 style="color:#fbbf24;margin-bottom:6px;">什么会证伪当前判断</h4>{_list_html(item.falsification_conditions)}
      <h4 style="margin-bottom:6px;">证据缺口</h4>{_list_html(item.evidence_gaps)}
      <h4 style="margin-bottom:6px;">来源</h4>{source_html}
    </article>"""
