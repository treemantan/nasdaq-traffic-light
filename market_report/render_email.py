from __future__ import annotations

from html import escape

from .data_sources import MarketMetric
from .etf_monitor import ETFAssetMonitor, ETFMonitor, PortfolioPosition
from .news_monitor import NewsMonitor
from .scoring import IronCondorAssessment, ScoredMetric, ScoredReport


EMAIL_GROUPS = [
    ("权益风险偏好", ["nasdaq", "sp500", "russell2000"]),
    ("情绪、波动与压力", ["cnn_fear_greed", "naaim_exposure", "vix", "vvix", "move", "credit_spread_hy"]),
    ("利率与实际利率", ["treasury_2y", "treasury_10y", "curve_2s10s", "real_yield_10y", "inflation_expectation_10y"]),
    ("美元与商品", ["dxy", "gbpusd", "usdjpy", "gold", "oil"]),
    ("美元流动性", ["fed_balance_sheet", "rrp", "tga", "bank_reserves"]),
]


def render_email_report(report: ScoredReport) -> str:
    groups = "".join(_render_group(title, keys, report.metrics) for title, keys in EMAIL_GROUPS)
    knowns = "".join(f"<li>{escape(item)}</li>" for item in report.regime.knowns)
    unknowns = "".join(f"<li>{escape(item)}</li>" for item in report.regime.unknowns)
    risks = "".join(f"<li>{escape(item)}</li>" for item in report.risks)
    data_rows = "".join(_render_data_row(item.metric) for item in report.metrics.values())
    iron_condor = _render_iron_condor(report.iron_condor)
    news_monitor = _render_news_monitor(report.news_monitor)
    etf_monitor = _render_etf_monitor(report.etf_monitor, report.news_monitor)
    accent = report.light_color

    return f"""<!doctype html>
<html lang="zh-CN">
<body style="margin:0;padding:0;background:#0b1017;font-family:Arial,'Microsoft YaHei',sans-serif;color:#f3f4f6;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0b1017;width:100%;">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" width="760" cellspacing="0" cellpadding="0" style="width:760px;max-width:100%;background:#111827;border:1px solid #263244;border-radius:8px;">
          <tr>
            <td style="padding:22px 24px;border-bottom:1px solid #263244;">
              <div style="font-size:28px;line-height:1.2;font-weight:700;color:#f3f4f6;">Macro Regime Radar：宏观状态雷达</div>
              <div style="font-size:13px;color:#9ca3af;margin-top:6px;">{escape(report.report_date)} · Macro regime-aware cross-asset monitor</div>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 24px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td width="33%" valign="top" style="padding:12px;background:#151f2d;border:1px solid #263244;border-radius:8px;">
                    <div style="font-size:12px;color:#9ca3af;">综合宏观风险分</div>
                    <div style="font-size:56px;line-height:1;font-weight:700;color:{accent};">{report.overall_score}<span style="font-size:22px;color:#9ca3af;">/100</span></div>
                    <div style="font-size:14px;font-weight:700;color:#f3f4f6;margin-top:10px;">{escape(report.light_label)}：{escape(report.headline)}</div>
                  </td>
                  <td width="2%"></td>
                  <td width="65%" valign="top" style="padding:12px;background:#151f2d;border:1px solid #263244;border-radius:8px;">
                    <div style="font-size:12px;color:#9ca3af;">主导宏观框架</div>
                    <div style="font-size:24px;line-height:1.25;font-weight:700;color:#f3f4f6;margin-top:5px;">{escape(report.regime.label)}</div>
                    <div style="font-size:14px;color:#d1d5db;margin-top:8px;">{escape(report.summary)}</div>
                    <div style="font-size:13px;color:#bfdbfe;margin-top:10px;">Regime: {escape(report.regime.name)} · 流动性：{escape(report.regime.liquidity_regime)} · 收益率驱动：{escape(report.regime.yield_driver)}</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 24px 18px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#151f2d;border:1px solid #263244;border-radius:8px;">
                <tr>
                  <td style="padding:12px;">
                    <div style="font-size:12px;color:#9ca3af;">数据健康度</div>
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px;">
                      <tr>
                        <td style="padding:8px;border:1px solid #263244;color:#d1d5db;">状态<br><strong style="font-size:18px;color:#f3f4f6;">{escape(report.data_quality)}</strong></td>
                        <td style="padding:8px;border:1px solid #263244;color:#d1d5db;">置信度<br><strong style="font-size:18px;color:#f3f4f6;">{report.regime.confidence_score}/100</strong></td>
                        <td style="padding:8px;border:1px solid #263244;color:#d1d5db;">核心缓存<br><strong style="font-size:18px;color:#f3f4f6;">{report.data_health.get("core_cached", 0)}</strong></td>
                        <td style="padding:8px;border:1px solid #263244;color:#d1d5db;">辅助缺失<br><strong style="font-size:18px;color:#f3f4f6;">{report.data_health.get("aux_missing", 0)}</strong></td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          {iron_condor}
          {news_monitor}
          {etf_monitor}
          {groups}
          <tr>
            <td style="padding:0 24px 18px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td valign="top" width="33%" style="padding:12px;background:#151f2d;border:1px solid #263244;">
                    <div style="font-size:17px;font-weight:700;color:#f3f4f6;">市场已知信息</div>
                    <ul style="color:#d1d5db;padding-left:18px;margin:8px 0 0;font-size:13px;">{knowns}</ul>
                  </td>
                  <td valign="top" width="34%" style="padding:12px;background:#151f2d;border:1px solid #263244;">
                    <div style="font-size:17px;font-weight:700;color:#f3f4f6;">未决宏观变量</div>
                    <ul style="color:#d1d5db;padding-left:18px;margin:8px 0 0;font-size:13px;">{unknowns}</ul>
                  </td>
                  <td valign="top" width="33%" style="padding:12px;background:#151f2d;border:1px solid #263244;">
                    <div style="font-size:17px;font-weight:700;color:#f3f4f6;">风险与策略含义</div>
                    <ul style="color:#d1d5db;padding-left:18px;margin:8px 0 0;font-size:13px;">{risks}</ul>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 24px 22px;">
              <div style="font-size:17px;font-weight:700;color:#f3f4f6;margin-bottom:8px;">数据源、最近有效值与新鲜度</div>
              <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:12px;color:#d1d5db;">
                <tr>
                  <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">指标</th>
                  <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">Ticker</th>
                  <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">来源</th>
                  <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">最近有效值</th>
                  <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">状态</th>
                </tr>
                {data_rows}
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:14px 24px;border-top:1px solid #263244;color:#9ca3af;font-size:12px;">
              免责声明：本报告仅用于宏观市场监控与研究参考，不构成投资建议。完整网页版本已作为附件发送。
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _render_group(title: str, keys: list[str], metrics: dict[str, ScoredMetric]) -> str:
    cards = [metrics[key] for key in keys if key in metrics]
    if not cards:
        return ""
    rows = []
    for i in range(0, len(cards), 2):
        left = _render_metric_card(cards[i])
        right = _render_metric_card(cards[i + 1]) if i + 1 < len(cards) else "<td width='50%'>&nbsp;</td>"
        rows.append(f"<tr>{left}{right}</tr>")
    return f"""<tr>
      <td style="padding:0 24px 18px;">
        <div style="font-size:19px;font-weight:700;color:#f3f4f6;margin:8px 0 10px;">{escape(title)}</div>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0">{''.join(rows)}</table>
      </td>
    </tr>"""


def _render_iron_condor(assessment: IronCondorAssessment) -> str:
    positives = _render_assessment_items(assessment.positives)
    warnings = _render_assessment_items(assessment.warnings)
    blockers = _render_assessment_items(assessment.blockers)
    return f"""<tr>
      <td style="padding:0 24px 18px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#151f2d;border:1px solid {assessment.color};border-radius:8px;">
          <tr>
            <td style="padding:14px;">
              <div style="font-size:19px;font-weight:700;color:#f3f4f6;">Iron Condor环境过滤器</div>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px;">
                <tr>
                  <td width="22%" valign="top">
                    <div style="font-size:12px;color:#9ca3af;">区间型卖波动环境</div>
                    <div style="font-size:42px;line-height:1;font-weight:700;color:{assessment.color};">{assessment.score}<span style="font-size:18px;color:#9ca3af;">/100</span></div>
                  </td>
                  <td valign="top">
                    <div style="font-size:15px;font-weight:700;color:{assessment.color};">{escape(assessment.label)}</div>
                    <div style="font-size:14px;color:#d1d5db;margin-top:7px;">{escape(assessment.summary)}</div>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:12px;">
                <tr>
                  <td width="33%" valign="top" style="padding:8px;border:1px solid #263244;">
                    <div style="font-size:14px;font-weight:700;color:#f3f4f6;">支持因素</div>
                    <ul style="color:#d1d5db;padding-left:18px;margin:7px 0 0;font-size:12px;">{positives}</ul>
                  </td>
                  <td width="34%" valign="top" style="padding:8px;border:1px solid #263244;">
                    <div style="font-size:14px;font-weight:700;color:#f3f4f6;">风险提示</div>
                    <ul style="color:#d1d5db;padding-left:18px;margin:7px 0 0;font-size:12px;">{warnings}</ul>
                  </td>
                  <td width="33%" valign="top" style="padding:8px;border:1px solid #263244;">
                    <div style="font-size:14px;font-weight:700;color:#f3f4f6;">阻断项</div>
                    <ul style="color:#d1d5db;padding-left:18px;margin:7px 0 0;font-size:12px;">{blockers}</ul>
                  </td>
                </tr>
              </table>
              <div style="font-size:12px;color:#9ca3af;margin-top:10px;">本模块仅评估市场环境是否适合区间型卖波动策略，不构成期权交易建议。</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def _render_assessment_items(items: list[str]) -> str:
    if not items:
        return "<li>暂无明显信号。</li>"
    return "".join(f"<li>{escape(item)}</li>" for item in items)


def _render_news_monitor(monitor: NewsMonitor | None) -> str:
    if monitor is None:
        return ""
    rows = "".join(
        f"""<tr>
          <td style="padding:8px;border-bottom:1px solid #263244;">
            <a href="{escape(event.url)}" style="color:#bfdbfe;text-decoration:none;">{escape(event.title)}</a>
            <div style="font-size:12px;color:#9ca3af;margin-top:4px;">{escape(event.channel)} · {escape(event.source)} · {escape(event.published_at)} · {escape(event.source_type)} · 影响：{escape(event.impact)}{f" · 相关Ticker：{escape('、'.join(event.tickers))}" if event.tickers else ""}{f" · 相关实体：{escape('、'.join(event.entities))}" if event.entities else ""}{' · 已自动翻译为英文' if event.original_title else ''}</div>
            <div style="font-size:12px;color:#d1d5db;margin-top:3px;">{escape(event.direction)} · {escape("、".join(event.themes))}</div>
          </td>
        </tr>"""
        for event in monitor.events[:5]
    )
    return f"""<tr>
      <td style="padding:0 24px 18px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#151f2d;border:1px solid #263244;border-radius:8px;">
          <tr><td style="padding:12px 12px 4px;font-size:17px;font-weight:700;color:#f3f4f6;">重要新闻与政策叙事监控</td></tr>
          <tr><td style="padding:0 12px 8px;font-size:13px;color:#d1d5db;">{escape(monitor.summary)}</td></tr>
          {rows or '<tr><td style="padding:8px 12px;color:#9ca3af;">暂无可核验的重要新闻事件。</td></tr>'}
          <tr><td style="padding:8px 12px;color:#9ca3af;font-size:12px;">新闻情绪仅用于辅助解释跨资产叙事，不直接改变量化评分。</td></tr>
        </table>
      </td>
    </tr>"""


def _render_etf_monitor(monitor: ETFMonitor | None, news_monitor: NewsMonitor | None = None) -> str:
    if monitor is None:
        return ""
    grouped_rows = "".join(_render_etf_email_group(group) for group in _group_etf_assets(monitor.assets))
    changes = _render_email_notes("今日ETF变动摘要", monitor.change_summary)
    portfolio = _render_portfolio_email(monitor, news_monitor)
    return f"""<tr>
      <td style="padding:0 24px 18px;">
        <div style="font-size:19px;font-weight:700;color:#f3f4f6;margin:8px 0 8px;">UK ETF估值、趋势与拥挤度监控器</div>
        <div style="font-size:13px;color:#d1d5db;margin-bottom:8px;">{escape(monitor.summary)}</div>
        {changes}
        {portfolio}
        {grouped_rows}
        <div style="font-size:12px;color:#9ca3af;margin-top:8px;">PE与组合P/B均为底层持仓组合估值，不是ETF自身资产负债表指标。组合估值按发行商披露节奏更新，不等同于实时行情。PE位置优先显示本地历史分位；样本不足时显示当前PE/近一年缓存最高PE的近似比例。σ200使用去极值后的稳健趋势波动率，避免少数极端日收益掩盖趋势拉伸。proxy 表示使用同类ETF作近似估值参考；黄金ETC不适用PE/PB。</div>
      </td>
    </tr>"""


def _render_portfolio_email(monitor: ETFMonitor, news_monitor: NewsMonitor | None = None) -> str:
    if not monitor.portfolio_positions:
        return _render_email_notes("实际组合视角", monitor.portfolio_summary + monitor.portfolio_warnings)
    rows = "".join(_render_portfolio_email_row(position) for position in monitor.portfolio_positions)
    notes = "".join(
        f"<li>{escape(item)}</li>"
        for item in monitor.portfolio_summary + monitor.portfolio_warnings + monitor.portfolio_exposure_notes
    )
    exposures = "".join(
        f"""<td valign="top" style="padding:8px;border:1px solid #263244;">
          <span style="font-size:12px;color:#9ca3af;">{escape(item.label)} · {escape(item.symbol)}</span><br>
          <strong style="font-size:17px;color:#f3f4f6;">{item.weight_pct:.2f}%</strong><br>
          <span style="font-size:11px;color:#9ca3af;">直接 {item.direct_weight_pct:.2f}% · ETF间接 {item.etf_weight_pct:.2f}%</span>
        </td>"""
        for item in monitor.portfolio_exposures
    )
    exposure_panel = (
        '<div style="font-size:12px;font-weight:700;color:#f3f4f6;margin:8px 0 4px;">AI算力、平台与存储链穿透（可识别下限）</div>'
        f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:6px;"><tr>{exposures}</tr></table>'
        if exposures
        else ""
    )
    event_panel = _render_portfolio_event_review_email(monitor.portfolio_positions, news_monitor)
    return f"""
        <div style="font-size:15px;font-weight:700;color:#f3f4f6;margin:14px 0 4px;">实际组合持仓（Revolut statement 估算）</div>
        <div style="font-size:12px;color:#9ca3af;margin-bottom:6px;">持仓估算市值 {_fmt_gbp(monitor.portfolio_total_value_gbp)}。基于导出的 statement 与 Yahoo 最近价格估算，不等同于券商实时账户净值。</div>
        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:12px;color:#d1d5db;margin-bottom:6px;">
          <tr>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">资产</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">Native / GBP参考市值</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">未实现盈亏</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">日变化</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">距年内高点</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">占比</th>
          </tr>
          {rows}
        </table>
        {exposure_panel}
        {event_panel}
        <ul style="color:#9ca3af;padding-left:18px;margin:5px 0 10px;font-size:12px;">{notes}</ul>"""


def _render_portfolio_event_review_email(
    positions: list[PortfolioPosition], news_monitor: NewsMonitor | None
) -> str:
    events = _portfolio_news_matches(positions, news_monitor)
    if not events:
        return '<div style="font-size:12px;color:#9ca3af;margin:6px 0;">基本面事件复核：暂未匹配到直接持仓 ticker 的重要新闻；ETF 仍需结合底层持仓与新闻面板复核。</div>'
    rows = "".join(
        f'<li><a href="{escape(event.url)}" style="color:#bfdbfe;">{escape(event.title)}</a>'
        f' <span style="color:#9ca3af;">· {escape("、".join(event.tickers))} · {escape(event.impact)}</span></li>'
        for event in events
    )
    return f'<div style="font-size:12px;color:#d1d5db;margin:6px 0;"><strong>基本面事件复核（直接 ticker 匹配）</strong><ul style="padding-left:18px;">{rows}</ul></div>'


def _portfolio_news_matches(positions: list[PortfolioPosition], news_monitor: NewsMonitor | None):
    if news_monitor is None:
        return []
    symbols = {position.symbol.upper().split(".")[0] for position in positions}
    return [
        event
        for event in news_monitor.events
        if symbols.intersection(ticker.upper().split(".")[0] for ticker in event.tickers)
    ][:5]


def _render_portfolio_email_row(position: PortfolioPosition) -> str:
    pnl_color = _pnl_color(position.unrealized_pnl_gbp)
    day_color = _pnl_color(position.day_change_pct)
    scope = "ETF观察池" if position.monitor_status == "covered" else "待穿透"
    return f"""<tr>
      <td style="padding:7px;border-bottom:1px solid #263244;"><strong>{escape(position.symbol)}</strong><br><span style="color:#9ca3af;">{scope}<br>{escape(position.price_source or "行情来源待确认")}</span></td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(_fmt_native(position.market_value_native, position.native_currency))}<br><span style="color:#9ca3af;">{escape(_fmt_gbp(position.market_value_gbp))} · {escape(_fmt_fx(position))}</span></td>
      <td style="padding:7px;border-bottom:1px solid #263244;color:{pnl_color};">{escape(_fmt_signed_gbp(position.unrealized_pnl_gbp))}<br>{escape(_fmt_pct(position.unrealized_pnl_pct))}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;color:{day_color};">{escape(_fmt_pct(position.day_change_pct))}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(_fmt_peak_watch(position))}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{position.weight_pct:.2f}%</td>
    </tr>"""


def _render_etf_email_group(group: tuple[str, str, list[ETFAssetMonitor]]) -> str:
    title, description, assets = group
    rows = "".join(_render_etf_row(asset) for asset in assets)
    return f"""
        <div style="font-size:15px;font-weight:700;color:#f3f4f6;margin:14px 0 4px;">{escape(title)}</div>
        <div style="font-size:12px;color:#9ca3af;margin-bottom:6px;">{escape(description)} · {escape(_etf_group_stats(assets))}</div>
        <div style="font-size:12px;color:#9ca3af;margin-bottom:6px;">{escape(_etf_group_comparison(assets))}</div>
        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:12px;color:#d1d5db;margin-bottom:8px;">
          <tr>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">ETF</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">主题</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">1Dσ / 1M / RSI</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">组合PE / Fwd / 组合P/B</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">规模/流动性</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">PE位置</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">新增仓位环境</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">拥挤度</th>
          </tr>
          {rows}
        </table>"""


def _render_etf_row(asset: ETFAssetMonitor) -> str:
    valuation_source = _fmt_email_valuation_source(asset)
    liquidity = _fmt_liquidity(asset)
    return f"""<tr>
      <td style="padding:7px;border-bottom:1px solid #263244;"><strong>{escape(asset.symbol)}</strong><br>{escape(asset.provider)}<br><span style="color:#9ca3af;">TER {escape(_fmt_ter(asset.ter))} · {escape(_ter_label(asset.ter))}<br>审计：{escape(asset.metadata_status)}</span></td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(asset.theme)}<br>{escape(_fmt_sigma_200d(asset.trend_sigma_200d))} · {escape(asset.trend_stretch_label)}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(_fmt_sigma(asset.daily_sigma))} / {escape(_fmt_pct(asset.momentum_1m))} / {escape(_fmt_plain(asset.rsi14))}<br>{escape(asset.sigma_label)}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(_fmt_plain(asset.pe))} / {escape(_fmt_plain(asset.forward_pe))} / {escape(_fmt_plain(asset.pb))}<br>{escape(asset.valuation_label)}<br><span style="color:#9ca3af;">{escape(valuation_source)}</span></td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(asset.liquidity_label)}<br><span style="color:#9ca3af;">{escape(liquidity)}</span></td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(_fmt_pe_position(asset))}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{asset.entry_score}/100<br>{escape(asset.entry_label)}<br><span style="color:#9ca3af;">{escape(_fmt_backtest(asset))}</span></td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{asset.crowding_score}/100<br>{escape(asset.crowding_label)}</td>
    </tr>"""


def _fmt_email_valuation_source(asset: ETFAssetMonitor) -> str:
    if asset.valuation_source == "unavailable":
        return "估值源：暂无"
    as_of = f" · 最近披露：{asset.valuation_as_of}" if asset.valuation_as_of else ""
    return f"估值源：{asset.valuation_source}{as_of}"


def _group_etf_assets(assets: list[ETFAssetMonitor]) -> list[tuple[str, str, list[ETFAssetMonitor]]]:
    definitions = [
        ("宽基与核心资产", "组合底仓与主要指数风险暴露", {"Global Equity", "S&P 500", "UK Large Cap", "Nasdaq 100"}),
        ("AI、科技与软件链", "AI基础设施、信息技术、云软件、网络安全与自动化", {"US Technology", "AI Infrastructure", "Artificial Intelligence", "Cloud Software", "Cybersecurity", "Robotics & Automation"}),
        ("光通信与Photonics", "光模块、激光器、光学元件与AI数据中心互连产业链", {"Optical Technology & Photonics"}),
        ("半导体", "全球半导体周期与AI算力核心上游", {"Semiconductor"}),
        ("量子计算", "高beta前沿主题，适合单独观察热度与波动", {"Quantum Computing"}),
        ("韩国权益与存储链", "Samsung Electronics、SK hynix及韩国科技/工业周期暴露", {"South Korea Equity"}),
        ("军工与防务", "全球/欧洲防务、网络防务与防务创新", {"Defence", "European Defence", "Defence Innovation"}),
        ("固定收益与久期", "利率、久期与债券波动环境观察", {"US Treasury 7-10Y GBP Hedged"}),
        ("黄金与实物资产", "实际利率、美元与避险需求的交叉验证", {"Gold"}),
    ]
    remaining = list(assets)
    groups: list[tuple[str, str, list[ETFAssetMonitor]]] = []
    for title, description, themes in definitions:
        members = [asset for asset in remaining if asset.theme in themes]
        if not members:
            continue
        groups.append((title, description, members))
        remaining = [asset for asset in remaining if asset not in members]
    if remaining:
        groups.append(("其他观察池", "暂未归入主线主题的补充观察标的", remaining))
    return groups


def _etf_group_stats(assets: list[ETFAssetMonitor]) -> str:
    count = len(assets)
    avg_entry = _avg_number(asset.entry_score for asset in assets)
    avg_crowding = _avg_number(asset.crowding_score for asset in assets)
    avg_ter = _avg_number(asset.ter for asset in assets if asset.ter is not None)
    hot = [asset.symbol for asset in assets if asset.crowding_score >= 70]
    strong = [asset.symbol for asset in assets if asset.entry_score >= 70]
    parts = [f"{count}只", f"新增环境均值 {avg_entry:.0f}/100", f"拥挤度均值 {avg_crowding:.0f}/100"]
    if avg_ter:
        parts.append(f"平均TER {avg_ter:.2f}%")
    if strong:
        parts.append("环境较好：" + "、".join(strong[:3]))
    if hot:
        parts.append("拥挤偏高：" + "、".join(hot[:3]))
    return "；".join(parts)


def _avg_number(values) -> float:
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    return sum(clean) / len(clean) if clean else 0.0


def _render_email_notes(title: str, items: list[str]) -> str:
    if not items:
        return ""
    rows = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f'<div style="font-size:13px;color:#d1d5db;margin:8px 0;"><strong>{escape(title)}</strong><ul>{rows}</ul></div>'


def _etf_group_comparison(assets: list[ETFAssetMonitor]) -> str:
    parts = []
    ter_assets = [asset for asset in assets if asset.ter is not None]
    if ter_assets:
        cheapest = min(ter_assets, key=lambda asset: asset.ter or 0)
        parts.append(f"成本最低：{cheapest.symbol} TER {cheapest.ter:.2f}%")
    aum_assets = [asset for asset in assets if asset.aum is not None]
    if aum_assets:
        largest = max(aum_assets, key=lambda asset: asset.aum or 0)
        parts.append(f"规模最大：{largest.symbol} AUM {_fmt_money_short(largest.aum)}")
    liquid_assets = [asset for asset in assets if asset.avg_traded_value_20d is not None]
    if liquid_assets:
        most_liquid = max(liquid_assets, key=lambda asset: asset.avg_traded_value_20d or 0)
        parts.append(f"成交最活跃：{most_liquid.symbol} 20日均成交额 {_fmt_money_short(most_liquid.avg_traded_value_20d)}")
    overlap = _max_holdings_overlap(assets)
    if overlap:
        left, right, score = overlap
        parts.append(f"前十大持仓近似重叠最高：{left} / {right} {score:.0f}%")
    return "；".join(parts) + "。"


def _max_holdings_overlap(assets: list[ETFAssetMonitor]) -> tuple[str, str, float] | None:
    best = None
    for index, left in enumerate(assets):
        for right in assets[index + 1 :]:
            left_weights = {_holding_key(item): item.weight for item in left.holdings}
            right_weights = {_holding_key(item): item.weight for item in right.holdings}
            if not left_weights or not right_weights:
                continue
            overlap = sum(min(weight, right_weights.get(key, 0)) for key, weight in left_weights.items())
            if best is None or overlap > best[2]:
                best = (left.symbol, right.symbol, overlap)
    return best


def _holding_key(holding) -> str:
    return (holding.symbol or holding.name).lower().replace(" ", "")


def _fmt_pe_position(asset: ETFAssetMonitor) -> str:
    if asset.pe_percentile is not None:
        return f"分位 {asset.pe_percentile:.0f}%"
    if asset.pe_high_1y_ratio is not None:
        return f"约{asset.pe_high_1y_ratio:.0f}% / 1Y高点"
    return "样本不足"


def _fmt_backtest(asset: ETFAssetMonitor) -> str:
    backtest = asset.backtest
    if backtest is None:
        return "历史检验：暂无"
    if backtest.sample_size <= 0:
        return f"历史检验：{backtest.reliability}"
    similar_path = " / ".join(
        [
            _fmt_pct(backtest.similar_forward_1m),
            _fmt_pct(backtest.similar_forward_3m),
            _fmt_pct(backtest.similar_forward_6m),
        ]
    )
    return (
        f"相似市场环境：{backtest.similar_count}个样本，{backtest.similarity_confidence}，"
        f"特征覆盖率{_fmt_rate(backtest.similar_avg_feature_coverage_pct)}；之后1/3/6M {similar_path}，"
        f"3M胜率{_fmt_rate(backtest.similar_hit_rate_3m)}，回撤{_fmt_pct(backtest.similar_max_drawdown_3m)}；"
        f"阈值质检：{backtest.reliability}，{backtest.best_threshold_label}"
    )


def _fmt_threshold_calibration(asset: ETFAssetMonitor) -> str:
    backtest = asset.backtest
    if backtest is None or not backtest.threshold_calibrations:
        return "阈值校准：暂无"
    best = backtest.best_threshold_label
    compact = []
    for item in backtest.threshold_calibrations:
        compact.append(
            f"≥{item.threshold}&拥挤<{item.crowding_ceiling}:{item.sample_count}样本/"
            f"3M{_fmt_pct(item.forward_3m)}/6M{_fmt_pct(item.forward_6m)}/胜率{_fmt_rate(item.hit_rate_3m)}/回撤{_fmt_pct(item.max_drawdown_3m)}"
        )
    return f"阈值校准：{best}；" + " | ".join(compact)


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def _fmt_ter(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def _ter_label(value: float | None) -> str:
    if value is None:
        return "费率待确认"
    if value <= 0.15:
        return "低成本"
    if value <= 0.35:
        return "成本适中"
    if value <= 0.50:
        return "主题费率偏高"
    return "高费率"


def _fmt_liquidity(asset: ETFAssetMonitor) -> str:
    parts = []
    if asset.aum is not None:
        parts.append(f"AUM {_fmt_money_short(asset.aum)}")
    if asset.avg_traded_value_20d is not None:
        parts.append(f"20日均成交额 {_fmt_money_short(asset.avg_traded_value_20d)}")
    if asset.bid_ask_spread_pct is not None:
        parts.append(f"价差 {asset.bid_ask_spread_pct:.2f}%")
    else:
        parts.append("价差待确认")
    if not parts:
        parts.append(asset.liquidity_note)
    return "；".join(parts)


def _fmt_money_short(value: float | None) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


def _render_metric_card(item: ScoredMetric) -> str:
    metric = item.metric
    change_text, change_color = _change_text(metric)
    status = _status_label(metric)
    return f"""<td width="50%" valign="top" style="padding:8px;background:#151f2d;border:1px solid #263244;">
      <div style="font-size:14px;font-weight:700;color:#f3f4f6;">{escape(metric.label)} <span style="font-size:12px;color:#86efac;">{escape(status)}</span></div>
      <div style="font-size:12px;color:#9ca3af;">{escape(metric.symbol)} · {escape(metric.source)}</div>
      <div style="font-size:25px;font-weight:700;color:#f3f4f6;margin-top:8px;">{escape(_fmt(metric.value, metric.unit))}</div>
      <div style="font-size:13px;color:{change_color};">{escape(change_text)}</div>
      <div style="font-size:13px;color:#bfdbfe;margin-top:7px;">{escape(item.signal)} · 风险分 {item.score}</div>
      <div style="font-size:13px;color:#d1d5db;margin-top:6px;">{escape(item.note)}</div>
    </td>"""


def _render_data_row(metric: MarketMetric) -> str:
    date_text = metric.as_of.isoformat() if metric.as_of else "无有效值"
    return f"""<tr>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(metric.label)}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(metric.symbol)}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(metric.source)}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(date_text)}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(_status_label(metric))}</td>
    </tr>"""


def _change_text(metric: MarketMetric) -> tuple[str, str]:
    if metric.change is None or metric.change_pct is None:
        return "变化：N/A", "#9ca3af"
    sign = "+" if metric.change >= 0 else ""
    color = "#f87171" if metric.change >= 0 else "#4ade80"
    return f"{sign}{_fmt(metric.change, metric.unit)} / {sign}{metric.change_pct:.2f}%", color


def _status_label(metric: MarketMetric) -> str:
    if metric.status == "ok" and metric.freshness == "live":
        return "实时/收盘"
    if metric.status == "ok" and metric.freshness == "recent-valid":
        return "最近有效值"
    if metric.status == "ok" and metric.freshness == "cache":
        return "使用缓存"
    if metric.status == "ok" and metric.freshness == "derived":
        return "估算/派生"
    if metric.status == "suspicious":
        return "数据异常"
    if metric.status == "stale":
        return "滞后"
    return "缺失"


def _fmt_plain(value: float | None) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _fmt_native(value: float | None, currency: str) -> str:
    if value is None:
        return "N/A"
    if currency == "GBP":
        return f"£{value:,.2f}"
    if currency == "USD":
        return f"${value:,.2f}"
    if currency == "EUR":
        return f"€{value:,.2f}"
    return f"{value:,.2f} {currency}".strip()


def _fmt_fx(position) -> str:
    if not position.fx_pair:
        return "GBP"
    if position.fx_rate is None:
        return f"{position.fx_pair} N/A"
    return f"{position.fx_pair} {position.fx_rate:.4f}"


def _fmt_peak_watch(position: PortfolioPosition) -> str:
    if position.drawdown_from_year_peak_pct is None:
        return "N/A"
    sma = f" · 距SMA200 {_fmt_pct(position.distance_sma200_pct)}" if position.distance_sma200_pct is not None else ""
    sigma = f" · 约{_fmt_plain(position.pullback_sigma_1m)}σ(1M)" if position.pullback_sigma_1m is not None else ""
    return f"{_fmt_pct(position.drawdown_from_year_peak_pct)}{sma}{sigma} · {position.drawdown_regime or position.peak_watch or '回撤观察'}"


def _fmt_gbp(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"£{value:,.2f}"


def _fmt_signed_gbp(value: float | None) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else "-"
    return f"{sign}£{abs(value):,.2f}"


def _pnl_color(value: float | None) -> str:
    if value is None:
        return "#9ca3af"
    return "#4ade80" if value >= 0 else "#f87171"


def _fmt_sigma(value: float | None) -> str:
    if value is None:
        return "N/Aσ"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}σ"


def _fmt_sigma_200d(value: float | None) -> str:
    if value is None:
        return "N/Aσ200"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}σ200"


def _fmt(value: float | None, unit: str = "") -> str:
    if value is None:
        return "N/A"
    if unit == "%":
        return f"{value:.3f}%"
    if unit == "bp":
        return f"{value:.0f}bp"
    if unit == "USD bn":
        return f"{value:,.0f}B"
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.4f}".rstrip("0").rstrip(".")
