from __future__ import annotations

from datetime import datetime
from html import escape

from .data_sources import MarketMetric
from .etf_monitor import ETFAssetMonitor, ETFMonitor, PortfolioPosition
from .mag7_capital_network import AggregateCapitalDisclosure, CapitalRelation, Mag7CapitalNetwork
from .news_monitor import NewsEvent, NewsMonitor
from .portfolio_events import PortfolioEventMonitor
from .scoring import IronCondorAssessment, ScoreDriver, ScoredMetric, ScoredReport
from .shock_backtest import MarketShockBacktest, MarketShockSample
from .technical_swing import SwingAssessment, SwingZone, TechnicalSwingReport
from .time_utils import format_timestamp


DISPLAY_GROUPS = [
    ("权益风险偏好", ["nasdaq", "sp500", "russell2000"]),
    ("情绪、波动与压力", ["cnn_fear_greed", "naaim_exposure", "vix", "vvix", "move", "credit_spread_hy"]),
    ("利率与实际利率", ["treasury_2y", "treasury_10y", "curve_2s10s", "real_yield_10y", "inflation_expectation_10y"]),
    ("美元与商品", ["dxy", "gbpusd", "usdjpy", "gold", "oil"]),
    ("美元流动性", ["fed_balance_sheet", "rrp", "tga", "bank_reserves"]),
]


def render_html_report(report: ScoredReport, title: str) -> str:
    groups = "\n".join(_render_group(title, keys, report.metrics) for title, keys in DISPLAY_GROUPS)
    data_rows = "\n".join(_render_data_row(item.metric, report.fetched_timezone) for item in report.metrics.values())
    knowns = "\n".join(f"<li>{escape(item)}</li>" for item in report.regime.knowns)
    unknowns = "\n".join(f"<li>{escape(item)}</li>" for item in report.regime.unknowns)
    risks = "\n".join(f"<li>{escape(item)}</li>" for item in report.risks)
    weights = "\n".join(_render_weight_row(key, value, report.metrics) for key, value in report.weights.items())
    score_drivers = _render_score_drivers(report.score_drivers)
    health_notes = _render_health_notes(report)
    iron_condor = _render_iron_condor(report.iron_condor)
    market_shock_backtest = _render_market_shock_backtest(report.market_shock_backtest)
    news_monitor = _render_news_monitor(report.news_monitor)
    mag7_capital_network = _render_mag7_capital_network(report.mag7_capital_network)
    etf_monitor = _render_etf_monitor(report.etf_monitor, report.news_monitor, report.portfolio_event_monitor)
    technical_swing = _render_technical_swing(report.technical_swing)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} | {report.report_date}</title>
  <style>
    :root {{
      --bg: #0b1017;
      --panel: #111827;
      --panel-2: #151f2d;
      --line: #263244;
      --muted: #9ca3af;
      --text: #f3f4f6;
      --subtle: #d1d5db;
      --accent: {report.light_color};
      --green: #2f9e44;
      --amber: #b7791f;
      --red: #c92a2a;
      --blue: #2563eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      font-size: 15px;
      line-height: 1.55;
    }}
    .page {{ max-width: 1180px; margin: 0 auto; padding: 28px 18px 34px; }}
    .topbar {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 18px;
      align-items: start;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
      margin-bottom: 18px;
    }}
    h1 {{ margin: 0; font-size: 34px; line-height: 1.15; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; letter-spacing: 0; }}
    .subtitle, .muted {{ color: var(--muted); }}
    .datebox {{ text-align: right; color: var(--subtle); }}
    .datebox strong {{ display: block; color: var(--text); font-size: 22px; }}
    .hero {{ display: grid; grid-template-columns: 300px 1fr 300px; gap: 14px; margin-bottom: 14px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; min-width: 0; }}
    .kicker {{ color: var(--muted); font-size: 12px; letter-spacing: .04em; text-transform: uppercase; margin-bottom: 8px; }}
    .score {{ font-size: 64px; line-height: 1; color: var(--accent); font-weight: 760; }}
    .score span {{ color: var(--muted); font-size: 24px; font-weight: 500; }}
    .light {{
      display: inline-flex; align-items: center; gap: 8px; margin-top: 12px; padding: 7px 10px;
      border: 1px solid var(--line); border-radius: 6px; background: rgba(255,255,255,.03); font-weight: 650;
    }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--accent); }}
    .regime-title {{ font-size: 26px; line-height: 1.25; margin-bottom: 8px; font-weight: 760; }}
    .summary {{ color: var(--subtle); }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .chip {{ border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; color: var(--subtle); background: rgba(255,255,255,.025); font-size: 13px; }}
    .health-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .health-item {{ border: 1px solid var(--line); border-radius: 6px; padding: 8px; background: rgba(255,255,255,.025); }}
    .health-item strong {{ display: block; font-size: 18px; }}
    .health-notes {{ margin-top: 10px; color: var(--subtle); font-size: 13px; }}
    .strategy-filter {{ margin-bottom: 14px; border-color: {report.iron_condor.color}; }}
    .strategy-head {{ display: grid; grid-template-columns: 170px 1fr; gap: 16px; align-items: start; }}
    .strategy-score {{ font-size: 46px; line-height: 1; font-weight: 760; color: {report.iron_condor.color}; }}
    .strategy-score span {{ color: var(--muted); font-size: 18px; font-weight: 500; }}
    .strategy-label {{ display: inline-block; color: {report.iron_condor.color}; font-weight: 760; margin-bottom: 7px; }}
    .strategy-lists {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }}
    .strategy-list {{ background: rgba(255,255,255,.025); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
    .disclaimer {{ margin-top: 12px; color: var(--muted); font-size: 12px; }}
    .news-panel {{ margin-bottom: 14px; }}
    .news-head {{ display: grid; grid-template-columns: 1fr auto; gap: 14px; align-items: start; }}
    .news-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }}
    .news-item {{ border: 1px solid var(--line); border-radius: 6px; padding: 10px; background: rgba(255,255,255,.025); }}
    .news-item a {{ color: #bfdbfe; text-decoration: none; }}
    .news-meta {{ color: var(--muted); font-size: 12px; margin-top: 5px; }}
    .news-tags {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }}
    .capital-network {{ margin-bottom: 14px; }}
    .capital-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }}
    .capital-item {{ border: 1px solid var(--line); border-radius: 6px; padding: 10px; background: rgba(255,255,255,.025); }}
    .capital-item a {{ color: #bfdbfe; text-decoration: none; }}
    .capital-value {{ color: #f3f4f6; font-weight: 700; margin-top: 4px; }}
    .capital-note {{ color: var(--subtle); font-size: 13px; margin-top: 5px; }}
    .capital-subhead {{ color: var(--text); font-size: 15px; font-weight: 700; margin-top: 14px; }}
    .swing-panel {{ margin-bottom: 14px; }}
    .swing-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }}
    .swing-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: rgba(255,255,255,.025); min-width: 0; }}
    .swing-card-head {{ display: flex; justify-content: space-between; gap: 10px; align-items: start; }}
    .swing-card-title {{ font-weight: 760; font-size: 16px; }}
    .swing-status {{ color: #bfdbfe; font-weight: 650; text-align: right; }}
    .swing-values {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin-top: 10px; }}
    .swing-value {{ border-top: 1px solid var(--line); padding-top: 7px; color: var(--subtle); font-size: 12px; min-width: 0; }}
    .swing-value strong {{ display: block; color: var(--text); font-size: 13px; overflow-wrap: anywhere; }}
    .swing-note {{ color: var(--subtle); font-size: 12px; margin-top: 9px; }}
    .etf-summary {{ color: var(--subtle); margin-bottom: 12px; }}
    .portfolio-panel {{ margin: 12px 0; border: 1px solid var(--line); border-radius: 8px; background: rgba(255,255,255,.02); overflow: hidden; }}
    .portfolio-head {{ display: grid; grid-template-columns: 1fr auto; gap: 14px; padding: 14px; background: rgba(255,255,255,.025); }}
    .portfolio-title {{ font-size: 16px; font-weight: 760; }}
    .portfolio-total {{ text-align: right; }}
    .portfolio-total strong {{ display: block; font-size: 24px; }}
    .portfolio-notes {{ padding: 0 14px 12px; color: var(--subtle); font-size: 12px; }}
    .portfolio-event-grid {{ display: grid; gap: 8px; margin-top: 8px; }}
    .portfolio-event {{ padding: 10px; border: 1px solid var(--line); background: var(--panel-2); border-radius: 6px; }}
    .portfolio-exposure-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding: 12px 14px 4px; }}
    .portfolio-exposure {{ border: 1px solid var(--line); border-radius: 6px; padding: 9px; background: rgba(255,255,255,.025); }}
    .portfolio-exposure strong {{ display: block; font-size: 18px; }}
    .portfolio-table-scroll {{ max-width: 100%; overflow-x: auto; overflow-y: hidden; }}
    .portfolio-table {{ min-width: 1620px; }}
    .portfolio-table td, .portfolio-table th {{ white-space: nowrap; }}
    .portfolio-symbol {{ font-weight: 760; }}
    .portfolio-scope {{ color: var(--muted); font-size: 12px; }}
    .pnl-up {{ color: #4ade80; }}
    .pnl-down {{ color: #f87171; }}
    .sensitivity-panel {{ margin: 12px 0; border: 1px solid var(--line); border-radius: 8px; background: rgba(255,255,255,.02); overflow: hidden; }}
    .sensitivity-panel summary {{ cursor: pointer; padding: 12px 14px; background: rgba(255,255,255,.025); font-weight: 760; }}
    .sensitivity-table {{ min-width: 1120px; }}
    .etf-groups {{ display: grid; gap: 10px; }}
    .etf-group {{ border: 1px solid var(--line); border-left: 3px solid rgba(96,165,250,.48); border-radius: 8px; background: rgba(255,255,255,.02); overflow: hidden; }}
    .etf-group[open] {{ border-color: rgba(96,165,250,.52); background: rgba(15,23,42,.62); }}
    .etf-group summary {{ cursor: pointer; list-style: none; padding: 12px 14px; background: rgba(255,255,255,.025); }}
    .etf-group summary::-webkit-details-marker {{ display: none; }}
    .etf-group-head {{ display: flex; justify-content: space-between; gap: 14px; align-items: start; }}
    .etf-group-title {{ font-size: 16px; font-weight: 760; color: var(--text); }}
    .etf-group-meta {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .etf-group-stats {{ text-align: right; color: var(--subtle); font-size: 12px; min-width: 180px; }}
    .etf-group-body {{ padding: 12px; }}
    .etf-group-end {{ margin-top: 10px; padding-top: 8px; border-top: 1px dashed rgba(148,163,184,.28); color: var(--muted); font-size: 12px; }}
    .table-scroll {{ max-width: 100%; overflow-x: auto; overflow-y: hidden; }}
    .table-scroll table {{ min-width: 1580px; }}
    .shock-table-scroll {{ max-width: 100%; overflow-x: auto; overflow-y: hidden; }}
    .shock-table-scroll table {{ min-width: 980px; }}
    .etf-cards {{ display: none; }}
    .etf-card-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .etf-card {{ border: 1px solid var(--line); border-radius: 8px; background: rgba(255,255,255,.025); padding: 12px; min-width: 0; }}
    .etf-card-head {{ display: flex; justify-content: space-between; gap: 10px; align-items: start; margin-bottom: 8px; }}
    .etf-card-title {{ font-weight: 760; }}
    .etf-card-price {{ font-size: 20px; font-weight: 760; margin-top: 6px; }}
    .etf-card-meta {{ color: var(--subtle); font-size: 13px; margin-top: 7px; }}
    .etf-card-lines {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin-top: 10px; }}
    .etf-card-line {{ border-top: 1px solid var(--line); padding-top: 7px; color: var(--subtle); font-size: 12px; }}
    .etf-card-line strong {{ display: block; color: var(--text); font-size: 13px; }}
    .etf-table td, .etf-table th {{ white-space: nowrap; }}
    .etf-table td:nth-child(2), .etf-table th:nth-child(2) {{ white-space: normal; }}
    .etf-table td:nth-child(9), .etf-table th:nth-child(9) {{ min-width: 170px; max-width: 220px; white-space: normal; }}
    .etf-table td:nth-child(11), .etf-table th:nth-child(11) {{ min-width: 220px; max-width: 280px; white-space: normal; }}
    .entry-main {{ display: grid; gap: 4px; }}
    .entry-note {{ color: var(--subtle); font-size: 12px; }}
    .entry-details {{ margin-top: 6px; color: var(--muted); font-size: 12px; }}
    .entry-details summary {{ cursor: pointer; color: #bfdbfe; }}
    .entry-details div {{ margin-top: 5px; line-height: 1.45; }}
    .threshold-details {{ margin-top: 6px; color: var(--muted); }}
    .threshold-details summary {{ color: #9ca3af; }}
    .threshold-row {{ display: block; margin-top: 4px; }}
    .tail-case {{ margin-top: 8px; padding: 8px; border-left: 2px solid #d97706; background: rgba(217, 119, 6, 0.08); }}
    .tail-case ul {{ margin: 5px 0 0 18px; padding: 0; }}
    .tag {{ display: inline-block; border: 1px solid var(--line); border-radius: 6px; padding: 3px 6px; color: var(--subtle); background: rgba(255,255,255,.025); font-size: 12px; }}
    .tag-hot {{ color: #fca5a5; border-color: rgba(248,113,113,.45); }}
    .tag-cool {{ color: #86efac; border-color: rgba(134,239,172,.35); }}
    .tag-entry-good {{ color: #86efac; border-color: rgba(134,239,172,.40); }}
    .tag-entry-watch {{ color: #fcd34d; border-color: rgba(252,211,77,.42); }}
    .tag-entry-bad {{ color: #fca5a5; border-color: rgba(248,113,113,.45); }}
    .small-note {{ color: var(--muted); font-size: 12px; margin-top: 8px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .metric {{ background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-height: 148px; }}
    .metric-head {{ display: flex; justify-content: space-between; gap: 8px; align-items: start; margin-bottom: 10px; }}
    .metric-name {{ font-weight: 700; }}
    .symbol {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .metric-value {{ font-size: 24px; font-weight: 760; }}
    .change-up {{ color: #f87171; }}
    .change-down {{ color: #4ade80; }}
    .metric-note {{ color: var(--subtle); font-size: 13px; margin-top: 8px; }}
    .signal {{ display: inline-block; margin-top: 8px; color: #bfdbfe; font-size: 13px; }}
    .wide {{ grid-column: 1 / -1; }}
    .columns {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; margin-top: 14px; }}
    ul {{ margin: 0; padding-left: 19px; }}
    li {{ margin: 6px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px 6px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .status-ok {{ color: #86efac; }}
    .status-warn {{ color: #fcd34d; }}
    .status-bad {{ color: #fca5a5; }}
    .bar {{ height: 8px; background: #1f2937; border-radius: 999px; overflow: hidden; margin-top: 5px; }}
    .bar span {{ display: block; height: 100%; background: var(--blue); }}
    .driver-list {{ display: grid; gap: 8px; margin-top: 10px; }}
    .driver-row {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; border: 1px solid var(--line); border-radius: 6px; padding: 9px; background: rgba(255,255,255,.025); }}
    .driver-score {{ font-weight: 760; color: var(--text); }}
    .driver-meta {{ grid-column: 1 / -1; color: var(--muted); font-size: 12px; }}
    .footer {{ margin-top: 16px; color: var(--muted); font-size: 12px; display: flex; justify-content: space-between; gap: 12px; border-top: 1px solid var(--line); padding-top: 12px; }}
    @media (max-width: 980px) {{
      .hero, .grid, .columns, .strategy-head, .strategy-lists, .swing-grid {{ grid-template-columns: 1fr; }}
      .datebox {{ text-align: left; }}
      .etf-group-head {{ display: block; }}
      .etf-group-stats {{ text-align: left; margin-top: 7px; }}
      .portfolio-head {{ grid-template-columns: 1fr; }}
      .portfolio-total {{ text-align: left; }}
      .portfolio-exposure-grid {{ grid-template-columns: 1fr; }}
      .capital-grid {{ grid-template-columns: 1fr; }}
      .table-scroll {{ display: none; }}
      .etf-cards {{ display: block; }}
    }}
    @media (max-width: 620px) {{
      .topbar, .metric-grid {{ grid-template-columns: 1fr; }}
      .etf-card-grid, .etf-card-lines {{ grid-template-columns: 1fr; }}
      .swing-values {{ grid-template-columns: 1fr 1fr; }}
      .score {{ font-size: 52px; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="topbar">
      <div>
        <h1>{escape(title)}</h1>
        <div class="subtitle">Macro regime-aware cross-asset monitor | 中文机构版</div>
      </div>
      <div class="datebox">
        <strong>{report.report_date}</strong>
        <span>抓取时间（{escape(report.fetched_timezone)}）：{escape(report.fetched_at)}</span>
      </div>
    </section>

    <section class="hero">
      <div class="panel">
        <div class="kicker">综合宏观风险分</div>
        <div class="score">{report.overall_score}<span>/100</span></div>
        <div class="light"><span class="dot"></span>{escape(report.light_label)}：{escape(report.headline)}</div>
      </div>
      <div class="panel">
        <div class="kicker">主导宏观框架</div>
        <div class="regime-title">{escape(report.regime.label)}</div>
        <div class="summary">{escape(report.summary)}</div>
        <div class="chips">
          <span class="chip">Regime: {escape(report.regime.name)}</span>
          <span class="chip">流动性：{escape(report.regime.liquidity_regime)}</span>
          <span class="chip">收益率驱动：{escape(report.regime.yield_driver)}</span>
        </div>
      </div>
      <div class="panel">
        <div class="kicker">数据健康度</div>
        <div class="health-grid">
          <div class="health-item"><span class="muted">状态</span><strong>{escape(report.data_quality)}</strong></div>
          <div class="health-item"><span class="muted">置信度</span><strong>{report.regime.confidence_score}/100</strong></div>
          <div class="health-item"><span class="muted">核心缓存</span><strong>{report.data_health.get("core_cached", 0)}</strong></div>
          <div class="health-item"><span class="muted">辅助缺失</span><strong>{report.data_health.get("aux_missing", 0)}</strong></div>
        </div>
        <div class="health-notes">{health_notes}</div>
      </div>
    </section>

    {iron_condor}
    {market_shock_backtest}
    {news_monitor}
    {mag7_capital_network}
    {technical_swing}
    {etf_monitor}

    <section class="grid">{groups}</section>

    <section class="columns">
      <div class="panel">
        <h2>市场已知信息</h2>
        <ul>{knowns}</ul>
      </div>
      <div class="panel">
        <h2>未决宏观变量</h2>
        <ul>{unknowns}</ul>
      </div>
      <div class="panel">
        <h2>风险与策略含义</h2>
        <ul>{risks}</ul>
        <p>{escape(report.action)}</p>
      </div>
    </section>

    <section class="columns">
      <div class="panel">
        <h2>自适应权重</h2>
        {weights}
      </div>
      {score_drivers}
      <div class="panel wide">
        <h2>数据源、最近有效值与新鲜度</h2>
        <table>
          <thead>
            <tr><th>指标</th><th>Ticker</th><th>来源</th><th>最近有效值</th><th>抓取时间（{escape(report.fetched_timezone)}）</th><th>状态</th></tr>
          </thead>
          <tbody>{data_rows}</tbody>
        </table>
      </div>
    </section>

    <div class="footer">
      <span>免责声明：本报告仅用于宏观市场监控与研究参考，不构成投资建议。</span>
      <span>缓存、fallback、缺失与延迟状态均已显式标注；系统不会静默替代实时数据。</span>
    </div>
  </main>
</body>
</html>"""


def _render_technical_swing(report: TechnicalSwingReport | None) -> str:
    if report is None:
        return ""
    holdings = [item for item in report.assessments if item.origin == "holding"]
    watchlist = [item for item in report.assessments if item.origin != "holding"]
    warning_html = "".join(f"<li>{escape(item)}</li>" for item in report.warnings[:8])
    sections = []
    if holdings:
        sections.append(
            '<h3>持仓技术结构</h3><div class="swing-grid">'
            + "".join(_render_swing_card(item) for item in holdings)
            + "</div>"
        )
    if watchlist:
        sections.append(
            '<h3 style="margin-top:16px;">观察池与临时标的</h3><div class="swing-grid">'
            + "".join(_render_swing_card(item) for item in watchlist)
            + "</div>"
        )
    empty = '<div class="muted">当前没有持仓、固定观察池或临时 ticker 需要分析。</div>'
    return f"""<section class="panel swing-panel">
      <h2>技术波段观察</h2>
      <div class="summary">{escape(report.summary)}</div>
      {''.join(sections) or empty}
      {f'<details class="swing-note"><summary>数据质量与降级说明</summary><ul>{warning_html}</ul></details>' if warning_html else ''}
      <div class="disclaimer">本模块识别趋势、支撑阻力与量价确认，仅用于观察 setup 与失效条件，不构成买卖建议。</div>
    </section>"""


def _render_swing_card(item: SwingAssessment) -> str:
    indicators = item.indicators
    support = _nearest_swing_zone(item.supports, item.current_price)
    resistance = _nearest_swing_zone(item.resistances, item.current_price)
    holding = ""
    if item.origin == "holding":
        holding = (
            f'<div class="swing-value"><span>组合信息</span><strong>'
            f'权重 {_fmt_plain(item.position_weight_pct)}% · '
            f'未实现 {_fmt_signed_gbp(item.unrealized_pnl_gbp)}</strong></div>'
        )
    warning = f" · {escape('；'.join(item.warnings[:2]))}" if item.warnings else ""
    return f"""<article class="swing-card">
      <div class="swing-card-head">
        <div>
          <div class="swing-card-title">{escape(item.symbol)} · {escape(item.identity.name)}</div>
          <div class="muted">{escape(item.origin)} · {escape(item.identity.exchange)} · {escape(item.identity.currency)}</div>
        </div>
        <div class="swing-status">{escape(item.technical_status)}</div>
      </div>
      <div class="swing-values">
        <div class="swing-value"><span>价格 / 日变动</span><strong>{_fmt_plain(item.current_price)} / {_fmt_pct(item.change_pct)}</strong></div>
        <div class="swing-value"><span>趋势结构</span><strong>{escape(item.trend)}</strong></div>
        <div class="swing-value"><span>EMA21 / SMA50 / SMA200</span><strong>{_fmt_plain(indicators.ema21)} / {_fmt_plain(indicators.sma50)} / {_fmt_plain(indicators.sma200)}</strong></div>
        <div class="swing-value"><span>ATR14 / RSI14</span><strong>{_fmt_plain(indicators.atr14)} / {_fmt_plain(indicators.rsi14)}</strong></div>
        <div class="swing-value"><span>量能</span><strong>{escape(item.volume_label)} · {_fmt_plain(item.volume_ratio)}x</strong></div>
        <div class="swing-value"><span>最近支撑</span><strong>{_fmt_swing_zone(support)}</strong></div>
        <div class="swing-value"><span>最近阻力</span><strong>{_fmt_swing_zone(resistance)}</strong></div>
        <div class="swing-value"><span>ATR失效观察</span><strong>{_fmt_plain(item.invalidation_level)}</strong></div>
        {holding}
      </div>
      <div class="swing-note">{escape(item.volume_confirmation)}。{escape(item.note)}</div>
      <div class="swing-note">来源：{escape(item.data_source)} · 数据时间：{escape(item.data_timestamp)} · 状态：{escape(item.data_quality)}{warning}</div>
    </article>"""


def _nearest_swing_zone(zones: tuple[SwingZone, ...], price: float | None) -> SwingZone | None:
    if not zones or price is None:
        return None
    return min(zones, key=lambda zone: abs((zone.lower + zone.upper) / 2 - price))


def _fmt_swing_zone(zone: SwingZone | None) -> str:
    if zone is None:
        return "N/A"
    return f"{zone.lower:.2f}-{zone.upper:.2f} · 强度 {zone.score}/100"


def _render_health_notes(report: ScoredReport) -> str:
    notes: list[str] = []
    if report.data_health.get("core_missing", 0):
        notes.append("核心指标缺失，报告结论需复核。")
    if report.data_health.get("core_cached", 0):
        notes.append("部分核心指标使用缓存。")
    if report.data_health.get("aux_missing", 0):
        notes.append("辅助数据暂不可用，流动性判断基于可用市场价格推断。")
    if not notes:
        notes.append("核心数据源运行正常。")
    return escape(" ".join(notes))


def _render_score_drivers(drivers: list[ScoreDriver]) -> str:
    if not drivers:
        return ""
    rows = "".join(_render_score_driver_row(item) for item in drivers)
    return f"""<div class="panel">
        <h2>评分主要驱动</h2>
        <div class="summary">按“单项风险分 × 自适应权重”排序，用于解释综合风险分的主要来源。</div>
        <div class="driver-list">{rows}</div>
      </div>"""


def _render_score_driver_row(item: ScoreDriver) -> str:
    return f"""<div class="driver-row">
      <div><strong>{escape(item.label)}</strong><br><span class="muted">{escape(item.signal)}</span></div>
      <div class="driver-score">{item.metric_score}/100</div>
      <div class="driver-meta">权重 {item.weight:.0%} · 贡献 {item.weighted_score:.1f}</div>
    </div>"""


def _render_iron_condor(assessment: IronCondorAssessment) -> str:
    positives = _render_assessment_list(assessment.positives)
    warnings = _render_assessment_list(assessment.warnings)
    blockers = _render_assessment_list(assessment.blockers)
    return f"""<section class="panel strategy-filter">
      <h2>Iron Condor环境过滤器</h2>
      <div class="strategy-head">
        <div>
          <div class="kicker">区间型卖波动环境</div>
          <div class="strategy-score">{assessment.score}<span>/100</span></div>
        </div>
        <div>
          <div class="strategy-label">{escape(assessment.label)}</div>
          <div class="summary">{escape(assessment.summary)}</div>
        </div>
      </div>
      <div class="strategy-lists">
        <div class="strategy-list"><h2>支持因素</h2><ul>{positives}</ul></div>
        <div class="strategy-list"><h2>风险提示</h2><ul>{warnings}</ul></div>
        <div class="strategy-list"><h2>阻断项</h2><ul>{blockers}</ul></div>
      </div>
      <div class="disclaimer">本模块仅评估市场环境是否适合区间型卖波动策略，不构成期权交易建议。</div>
</section>"""


def _render_market_shock_backtest(backtest: MarketShockBacktest | None) -> str:
    if backtest is None or not backtest.triggered:
        return ""
    sample_rows = "\n".join(_render_market_shock_sample(sample) for sample in backtest.samples[:12])
    notes = "".join(f"<li>{escape(item)}</li>" for item in backtest.notes)
    tail = (
        f"{backtest.tail_phase_count}/{backtest.independent_phase_count}个独立阶段"
        if backtest.independent_phase_count
        else "样本不足"
    )
    return f"""<section class="panel news-panel">
      <div class="news-head">
        <div>
          <h2>市场冲击历史类比</h2>
          <div class="summary">当前冲击类型：{escape(backtest.shock_type)}。该模块只回答“过去类似冲击日之后怎么走”，不预测反弹或继续下跌。</div>
        </div>
        <span class="tag">{escape(backtest.reliability)}</span>
      </div>
      <div class="capital-grid">
        <div class="capital-item"><span class="muted">样本 / 独立阶段</span><div class="capital-value">{backtest.sample_count} / {backtest.independent_phase_count}</div></div>
        <div class="capital-item"><span class="muted">平均距离</span><div class="capital-value">{_fmt_distance(backtest.avg_distance)}</div></div>
        <div class="capital-item"><span class="muted">之后1D / 5D / 20D</span><div class="capital-value">{_fmt_pct(backtest.forward_1d_avg)} / {_fmt_pct(backtest.forward_5d_avg)} / {_fmt_pct(backtest.forward_20d_avg)}</div></div>
        <div class="capital-item"><span class="muted">5D胜率 / 20D回撤</span><div class="capital-value">{_fmt_pct(backtest.hit_rate_5d)} / {_fmt_pct(backtest.drawdown_20d_avg)}</div></div>
        <div class="capital-item"><span class="muted">尾部路径占比</span><div class="capital-value">{escape(tail)} · {_fmt_pct(backtest.tail_phase_rate)}</div></div>
      </div>
      <div class="shock-table-scroll" style="margin-top:12px;">
        <table>
          <thead>
            <tr><th>样本日</th><th>阶段</th><th>距离</th><th>NDX</th><th>S&P</th><th>VIX</th><th>VVIX</th><th>DXY</th><th>之后1D</th><th>之后5D</th><th>之后20D</th><th>20D回撤</th></tr>
          </thead>
          <tbody>{sample_rows}</tbody>
        </table>
      </div>
      <ul class="small-note">{notes}</ul>
    </section>"""


def _render_market_shock_sample(sample: MarketShockSample) -> str:
    representative = " · 代表样本" if sample.phase_representative else ""
    return f"""<tr>
      <td>{escape(sample.as_of)}</td>
      <td>{escape(sample.phase_id)}{representative}</td>
      <td>{sample.distance:.2f}</td>
      <td>{_fmt_pct(sample.nasdaq_change_pct)}</td>
      <td>{_fmt_pct(sample.sp500_change_pct)}</td>
      <td>{_fmt_pct(sample.vix_change_pct)}</td>
      <td>{_fmt_pct(sample.vvix_change_pct)}</td>
      <td>{_fmt_pct(sample.dxy_change_pct)}</td>
      <td>{_fmt_pct(sample.forward_1d)}</td>
      <td>{_fmt_pct(sample.forward_5d)}</td>
      <td>{_fmt_pct(sample.forward_20d)}</td>
      <td>{_fmt_pct(sample.drawdown_20d)}</td>
    </tr>"""


def _render_news_monitor(monitor: NewsMonitor | None) -> str:
    if monitor is None:
        return ""
    events = "\n".join(_render_news_event(event) for event in monitor.events)
    warnings = "".join(f"<li>{escape(item)}</li>" for item in monitor.warnings)
    cache_note = " · 使用缓存" if monitor.used_cache else ""
    return f"""<section class="panel news-panel">
  <div class="news-head">
    <div>
      <h2>重要新闻与政策叙事监控</h2>
      <div class="summary">{escape(monitor.summary)}</div>
    </div>
    <span class="tag">{escape(monitor.status)}{cache_note}</span>
  </div>
  <div class="news-grid">{events or '<div class="muted">暂无可核验的重要新闻事件。</div>'}</div>
  {f'<ul class="small-note">{warnings}</ul>' if warnings else ''}
  <div class="disclaimer">新闻情绪来自规则化主题识别与来源分级，仅用于辅助解释跨资产叙事，不构成交易建议。政治表态需结合后续政策文本与市场价格验证。</div>
</section>"""


def _render_news_event(event: NewsEvent) -> str:
    tags = "".join(f'<span class="tag">{escape(theme)}</span>' for theme in event.themes)
    tickers = f" · 相关Ticker：{escape('、'.join(event.tickers))}" if event.tickers else ""
    entities = f" · 相关实体：{escape('、'.join(event.entities))}" if event.entities else ""
    original_title = (
        f'<details class="news-meta"><summary>查看原始标题</summary>{escape(event.original_title)}</details>'
        if event.original_title
        else ""
    )
    return f"""<article class="news-item">
  <a href="{escape(event.url)}" target="_blank" rel="noopener noreferrer">{escape(event.title)}</a>
  <div class="news-meta">{escape(event.channel)} · {escape(event.source)} · {escape(event.published_at)} · {escape(event.source_type)} · 影响：{escape(event.impact)} · 置信度：{escape(event.confidence)}{tickers}{entities}</div>
  <div class="news-meta">{escape(event.direction)}</div>
  <div class="news-tags">{tags}</div>
  {original_title}
</article>"""


def _render_assessment_list(items: list[str]) -> str:
    if not items:
        return "<li>暂无明显信号。</li>"
    return "".join(f"<li>{escape(item)}</li>" for item in items)


def _render_mag7_capital_network(network: Mag7CapitalNetwork | None) -> str:
    if network is None:
        return ""
    relations = "\n".join(_render_capital_relation(item) for item in network.relations)
    aggregates = "\n".join(_render_aggregate_capital_disclosure(item) for item in network.aggregate_disclosures)
    warnings = "".join(f"<li>{escape(item)}</li>" for item in network.warnings)
    aggregate_panel = (
        f'<div class="capital-subhead">聚合披露：底层名单不可见</div><div class="capital-grid">{aggregates}</div>'
        if aggregates
        else ""
    )
    return f"""<section class="panel capital-network">
      <h2>MAG7企业资本关系图谱</h2>
      <div class="summary">{escape(network.summary)}</div>
      <div class="small-note">以下记录来自公司公告或监管披露，按关系类型区分股权投资、投资权利、云合作与聚合披露。该板块与“你的组合 MAG7 暴露”是两个不同视角。</div>
      <div class="capital-grid">{relations}</div>
      {aggregate_panel}
      <div class="capital-subhead">使用边界</div>
      <ul class="small-note">{warnings}</ul>
    </section>"""


def _render_capital_relation(item: CapitalRelation) -> str:
    themes = "".join(f'<span class="tag">{escape(theme)}</span>' for theme in item.themes)
    return f"""<article class="capital-item">
      <a href="{escape(item.source_url)}"><strong>{escape(item.investor)} · {escape(item.investor_ticker)}</strong> → {escape(item.target)} · {escape(item.target_ticker)}</a>
      <div class="news-meta">{escape(item.relation_type)} · 披露日期 {escape(item.disclosed_at)} · 置信度 {escape(item.confidence)}</div>
      <div class="capital-value">{escape(item.disclosed_value)}</div>
      <div class="capital-note">{escape(item.note)}</div>
      <div class="news-tags">{themes}</div>
      <div class="news-meta">来源：{escape(item.source)}</div>
    </article>"""


def _render_aggregate_capital_disclosure(item: AggregateCapitalDisclosure) -> str:
    return f"""<article class="capital-item">
      <a href="{escape(item.source_url)}"><strong>{escape(item.investor)} · {escape(item.investor_ticker)}</strong></a>
      <div class="news-meta">{escape(item.category)} · 披露日期 {escape(item.disclosed_at)}</div>
      <div class="capital-value">{escape(item.disclosed_value)}</div>
      <div class="capital-note">{escape(item.note)}</div>
      <div class="news-meta">来源：{escape(item.source)}</div>
    </article>"""


def _render_etf_monitor(
    monitor: ETFMonitor | None,
    news_monitor: NewsMonitor | None = None,
    portfolio_event_monitor: PortfolioEventMonitor | None = None,
) -> str:
    if monitor is None:
        return ""
    groups = "\n".join(_render_etf_group(group, index) for index, group in enumerate(_group_etf_assets(monitor.assets)))
    warnings = ""
    if monitor.warnings:
        warnings = "<div class=\"small-note\">数据提示：" + escape(_summarize_etf_warnings(monitor.warnings)) + "</div>"
    changes = _render_etf_notes("今日ETF变动摘要", monitor.change_summary)
    portfolio = _render_portfolio_panel(monitor, news_monitor, portfolio_event_monitor)
    sensitivities = _render_sensitivity_panel(monitor)
    return f"""<section class="panel">
      <h2>UK ETF估值、趋势与拥挤度监控器</h2>
      <div class="etf-summary">{escape(monitor.summary)}</div>
      {changes}
      {portfolio}
      {sensitivities}
      <div class="etf-groups">{groups}</div>
      <div class="small-note">PE衡量底层持仓组合的盈利估值，Forward PE基于未来盈利预期；组合P/B衡量底层持仓市值相对账面净资产的加权估值，并非ETF自身资产负债表指标。组合估值按发行商披露节奏更新，不等同于实时行情。PE位置优先显示本地历史分位；样本不足时显示“当前PE/近一年缓存最高PE”的近似比例。σ200使用63/126/252日窗口去极值后的稳健趋势波动率。持仓重叠度基于可获得的前十大持仓近似计算，并非完整穿透。估值源若标记为proxy，表示使用高度相关的同类ETF作近似参考。黄金、现金、短债和固定收益类产品不适用PE/PB，应观察实际利率、久期、收益率和流动性。</div>
      {warnings}
    </section>"""


def _render_portfolio_panel(
    monitor: ETFMonitor,
    news_monitor: NewsMonitor | None = None,
    portfolio_event_monitor: PortfolioEventMonitor | None = None,
) -> str:
    if not monitor.portfolio_positions:
        return _render_etf_notes("实际组合视角", monitor.portfolio_summary + monitor.portfolio_warnings)
    rows = "\n".join(_render_portfolio_row(position) for position in monitor.portfolio_positions)
    notes = monitor.portfolio_summary + monitor.portfolio_warnings
    note_html = "".join(f"<li>{escape(item)}</li>" for item in notes + monitor.portfolio_exposure_notes)
    exposures = "".join(
        f"""<div class="portfolio-exposure">
          <span class="muted">{escape(item.label)} · {escape(item.symbol)}</span>
          <strong>{item.weight_pct:.2f}%</strong>
          <span class="portfolio-scope">直接 {item.direct_weight_pct:.2f}% · ETF间接 {item.etf_weight_pct:.2f}%</span>
        </div>"""
        for item in monitor.portfolio_exposures
    )
    exposure_panel = (
        f'<div class="portfolio-notes"><strong>AI算力、平台与存储链穿透（可识别下限）</strong></div>'
        f'<div class="portfolio-exposure-grid">{exposures}</div>'
        if exposures
        else ""
    )
    mag7_exposures = "".join(
        f"""<div class="portfolio-exposure">
          <span class="muted">{escape(item.label)} · {escape(item.symbol)}</span>
          <strong>{item.weight_pct:.2f}%</strong>
          <span class="portfolio-scope">直接 {item.direct_weight_pct:.2f}% · ETF间接 {item.etf_weight_pct:.2f}%</span>
        </div>"""
        for item in monitor.portfolio_mag7_exposures
    )
    mag7_panel = (
        f'<div class="portfolio-notes"><strong>MAG7暴露穿透（可识别下限）</strong></div>'
        f'<div class="portfolio-exposure-grid">{mag7_exposures}</div>'
        f'<div class="portfolio-notes"><ul>{"".join(f"<li>{escape(item)}</li>" for item in monitor.portfolio_mag7_notes)}</ul></div>'
        if mag7_exposures
        else ""
    )
    performance_panel = _render_portfolio_performance(monitor)
    event_panel = _render_portfolio_event_calendar(portfolio_event_monitor)
    event_panel += _render_portfolio_event_review(monitor.portfolio_positions, news_monitor)
    total = _fmt_gbp(monitor.portfolio_total_value_gbp)
    return f"""<div class="portfolio-panel">
      <div class="portfolio-head">
        <div>
          <div class="portfolio-title">实际组合持仓（Revolut statement 估算）</div>
          <div class="small-note">基于导出的交易 statement 重建持仓，并使用 Yahoo 最近价格估算。仅覆盖本次导出账户范围，不等同于券商实时账户净值。</div>
        </div>
        <div class="portfolio-total"><span class="muted">持仓估算市值</span><strong>{escape(total)}</strong></div>
      </div>
      <div class="portfolio-table-scroll">
        <table class="portfolio-table">
          <thead>
            <tr>
              <th>资产</th><th>数量</th><th>平均成本GBP</th><th>当前价格Native</th><th>Native市值</th><th>GBP参考市值</th>
              <th>FX参考</th><th>收益拆分GBP</th><th>未实现盈亏%</th><th>日变化</th><th>距年内高点</th><th>组合占比</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      {performance_panel}
      {exposure_panel}
      {mag7_panel}
      {event_panel}
      <div class="portfolio-notes"><ul>{note_html}</ul></div>
    </div>"""


def _render_portfolio_performance(monitor: ETFMonitor) -> str:
    performance = monitor.portfolio_performance
    if performance is None:
        return ""
    cards = (
        ("扣费后可识别总收益", performance.total_return_gbp),
        ("未实现盈亏", performance.unrealized_pnl_gbp),
        ("已实现交易盈亏（净额）", performance.realized_pnl_gbp),
        ("股息收入", performance.dividend_income_gbp),
        ("隐含交易成本", -performance.implied_trading_cost_gbp),
    )
    rendered = "".join(
        f'<div class="portfolio-exposure"><span class="muted">{escape(label)}</span>'
        f'<strong class="{_pnl_class(value)}">{escape(_fmt_signed_gbp(value))}</strong></div>'
        for label, value in cards
    )
    return (
        '<div class="portfolio-notes"><strong>收益归因（statement 导出窗口内，可识别口径）</strong></div>'
        f'<div class="portfolio-exposure-grid">{rendered}</div>'
        '<div class="small-note">Revolut 隐含交易成本按 Total Amount 与 股数×成交价 的差额估算，可能包含佣金、税费、FX/执行价差与四舍五入；总收益已使用实际现金流口径，避免把费用当作利润。</div>'
        f'{_render_unmatched_sell_breakdown(performance)}'
        f'{_render_closed_trade_breakdown(performance)}'
        f'{_render_transaction_cost_breakdown(performance)}'
    )


def _render_unmatched_sell_breakdown(performance) -> str:
    if not performance.unmatched_sells:
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{escape(item.broker or 'N/A')}</td>"
        f"<td>{escape(item.symbol)}</td>"
        f"<td>{escape(item.date or 'N/A')}</td>"
        f"<td>{escape(_fmt_quantity(item.sell_quantity))}</td>"
        f"<td>{escape(_fmt_quantity(item.unmatched_quantity))}</td>"
        f"<td>{escape(_unmatched_proceeds(item))}</td>"
        "</tr>"
        for item in performance.unmatched_sells
    )
    return f"""<details class="portfolio-notes" open>
      <summary>成本基础不完整的卖出明细</summary>
      <div class="small-note">这些记录来自 SELL 交易行，不是现金转账。对应买入批次缺失时，不计入已实现盈亏。</div>
      <div class="portfolio-table-scroll">
        <table class="portfolio-table">
          <thead><tr><th>来源</th><th>资产</th><th>日期</th><th>卖出数量</th><th>未匹配数量</th><th>净卖出额</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </details>"""


def _unmatched_proceeds(item) -> str:
    if item.net_proceeds_gbp is not None:
        return f"£{item.net_proceeds_gbp:,.2f}"
    if item.net_proceeds_native is not None:
        return f"{item.currency} {item.net_proceeds_native:,.2f}"
    return "N/A"


def _render_closed_trade_breakdown(performance) -> str:
    if not performance.closed_trades:
        return ""
    rows = "".join(_render_closed_trade_group(symbol, trades) for symbol, trades in _closed_trade_groups(performance.closed_trades))
    return f"""<details class="portfolio-notes">
      <summary>已平仓交易归因（FIFO近似）</summary>
      <div class="small-note">用于解释 statement 窗口内已实现盈亏来源；先按 ticker 聚合，展开后显示所有 FIFO 买入批次，0天表示同日买卖。</div>
      <div class="portfolio-table-scroll">
        <table class="portfolio-table">
          <thead><tr><th>资产</th><th>清算窗口</th><th>数量</th><th>成本基础</th><th>净卖出额</th><th>已实现盈亏</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </details>"""


def _closed_trade_groups(trades) -> list[tuple[str, list]]:
    grouped: dict[str, list] = {}
    for trade in trades:
        grouped.setdefault(trade.symbol, []).append(trade)
    return sorted(
        grouped.items(),
        key=lambda item: (
            max((trade.closed_at or "") for trade in item[1]),
            abs(sum(trade.realized_pnl_gbp for trade in item[1])),
            item[0],
        ),
        reverse=True,
    )


def _render_closed_trade_group(symbol: str, trades: list) -> str:
    trades = sorted(trades, key=lambda trade: (trade.closed_at or "", trade.opened_at or ""), reverse=True)
    quantity = sum(trade.quantity for trade in trades)
    cost_basis = sum(trade.cost_basis_gbp for trade in trades)
    gross_proceeds = sum(trade.gross_proceeds_gbp for trade in trades)
    net_proceeds = sum(trade.net_proceeds_gbp for trade in trades)
    implied_cost = sum(trade.implied_trading_cost_gbp for trade in trades)
    realized_pnl = sum(trade.realized_pnl_gbp for trade in trades)
    opened_dates = [trade.opened_at for trade in trades if trade.opened_at]
    closed_dates = [trade.closed_at for trade in trades if trade.closed_at]
    window = f"{min(opened_dates) if opened_dates else 'N/A'} → {max(closed_dates) if closed_dates else 'N/A'}"
    details = "".join(
        f"<li>{escape(trade.opened_at or 'N/A')} → {escape(trade.closed_at or 'N/A')} · "
        f"{escape(_fmt_holding_days(trade.holding_days))} · "
        f"数量 {escape(_fmt_quantity(trade.quantity))} · 成本 {escape(_fmt_gbp(trade.cost_basis_gbp))} · "
        f"净卖出 {escape(_fmt_gbp(trade.net_proceeds_gbp))} · "
        f"<span class=\"{_pnl_class(trade.realized_pnl_gbp)}\">{escape(_fmt_signed_gbp(trade.realized_pnl_gbp))}</span></li>"
        for trade in trades
    )
    return f"""<tr>
      <td>{escape(symbol)}<br><span class="portfolio-scope">{len(trades)}个买入批次</span></td>
      <td>{escape(window)}<br><details><summary class="portfolio-scope">查看批次明细</summary><ul class="portfolio-scope">{details}</ul></details></td>
      <td>{escape(_fmt_quantity(quantity))}</td>
      <td>{escape(_fmt_gbp(cost_basis))}</td>
      <td>{escape(_fmt_gbp(net_proceeds))}<br><span class="portfolio-scope">毛额 {escape(_fmt_gbp(gross_proceeds))} · 成本 {escape(_fmt_gbp(implied_cost))}</span></td>
      <td class="{_pnl_class(realized_pnl)}">{escape(_fmt_signed_gbp(realized_pnl))}</td>
    </tr>"""


def _fmt_holding_days(value: int | None) -> str:
    if value is None:
        return "持有期不可识别"
    return f"持有 {value} 天"


def _render_transaction_cost_breakdown(performance) -> str:
    if not performance.transaction_costs:
        return ""
    rows = "".join(
        _render_transaction_cost_group(symbol, events)
        for symbol, events in _transaction_cost_groups(performance.transaction_costs)
    )
    return f"""<details class="portfolio-notes">
      <summary>隐含交易成本归因（估算）</summary>
      <div class="small-note">按 statement 中 Total Amount 与成交名义金额的差额估算；差额可能包含佣金、税费、FX/执行价差与四舍五入。Premium 账户每月 5 次免费交易若覆盖当月交易，实际隐含成本可能接近 0。</div>
      {_render_trade_allowance_summary(performance.transaction_costs)}
      <div class="portfolio-table-scroll">
        <table class="portfolio-table">
          <thead><tr><th>资产</th><th>交易次数</th><th>买入成本</th><th>卖出成本</th><th>历史卖出成本率</th><th>逐笔明细</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </details>"""


def _transaction_cost_groups(events) -> list[tuple[str, list]]:
    grouped: dict[str, list] = {}
    for event in events:
        grouped.setdefault(event.symbol, []).append(event)
    return sorted(
        grouped.items(),
        key=lambda item: (sum(event.implied_trading_cost_gbp for event in item[1]), item[0]),
        reverse=True,
    )


def _render_transaction_cost_group(symbol: str, events: list) -> str:
    events = sorted(events, key=lambda event: (event.date or "", event.side), reverse=True)
    buy_cost = sum(event.implied_trading_cost_gbp for event in events if event.side == "BUY")
    sell_cost = sum(event.implied_trading_cost_gbp for event in events if event.side == "SELL")
    sell_gross = sum(event.gross_value_gbp for event in events if event.side == "SELL")
    sell_rate = sell_cost / sell_gross * 100 if sell_gross else None
    details = "".join(
        f"<li>{escape(event.date or 'N/A')} · {escape(event.side)} · "
        f"数量 {escape(_fmt_quantity(event.quantity))} · 名义 {escape(_fmt_gbp(event.gross_value_gbp))} · "
        f"现金 {escape(_fmt_gbp(event.cash_amount_gbp))} · 成本 {escape(_fmt_gbp(event.implied_trading_cost_gbp))} · "
        f"费率 {event.cost_rate_pct:.4f}%</li>"
        for event in events
    )
    return f"""<tr>
      <td><strong>{escape(symbol)}</strong></td>
      <td>{len(events)}</td>
      <td>{escape(_fmt_gbp(buy_cost))}</td>
      <td>{escape(_fmt_gbp(sell_cost))}</td>
      <td>{escape(_fmt_pct(sell_rate))}</td>
      <td><details><summary class="portfolio-scope">查看逐笔成本</summary><ul class="portfolio-scope">{details}</ul></details></td>
    </tr>"""


def _render_trade_allowance_summary(events) -> str:
    monthly: dict[str, int] = {}
    for event in events:
        if event.date:
            monthly[event.date[:7]] = monthly.get(event.date[:7], 0) + 1
    if not monthly:
        return ""
    rows = "".join(
        f"<li>{escape(month)}：{count}笔；Premium 5次额度后超出 {max(count - 5, 0)} 笔；10次额度后超出 {max(count - 10, 0)} 笔。</li>"
        for month, count in sorted(monthly.items(), reverse=True)[:12]
    )
    return (
        '<div class="small-note"><strong>账户额度观察：</strong>用于判断 Premium 每月 5 次免费交易是否足够，'
        f'以及更高账户每月 10 次免费交易是否可能有节省价值。<ul>{rows}</ul></div>'
    )


def _render_portfolio_event_calendar(monitor: PortfolioEventMonitor | None) -> str:
    if monitor is None or (not monitor.events and not monitor.review_required_symbols):
        return ""
    rows = "".join(
        f"""<article class="portfolio-event">
          <div><strong>{escape(event.title)}</strong> <span class="status">{escape(event.alert_level)}</span></div>
          <div class="portfolio-scope">{escape(" / ".join(event.symbols))} · {escape(event.scope)} · {escape(event.status)} · {escape(event.event_time_label)}</div>
          <div>{escape(event.note)}</div>
          <div class="portfolio-scope">关注：{escape("；".join(event.watch_items))}</div>
          <div class="portfolio-scope"><a href="{escape(event.source_url)}" target="_blank" rel="noopener noreferrer">{escape(event.source_label)}</a>
          · <a href="{escape(event.progress_source_url)}" target="_blank" rel="noopener noreferrer">查看进展：{escape(event.progress_source_label)}</a></div>
        </article>"""
        for event in monitor.events
    )
    gaps = ""
    if monitor.review_required_symbols:
        gaps = (
            '<div class="small-note" style="color:var(--amber);">红色预警待补充事件来源：'
            + escape("、".join(monitor.review_required_symbols))
            + "。请人工复核公司IR、SEC披露及行业监管进展。</div>"
        )
    return f"""<div class="portfolio-notes">
      <strong>持仓事件复核日历</strong>
      <div class="small-note">{escape(monitor.summary)} 事件来源用于跟踪进展；预计日期会明确标记，不视为公司已确认日程。</div>
      {gaps}
      <div class="portfolio-event-grid">{rows}</div>
    </div>"""


def _render_portfolio_event_review(
    positions: list[PortfolioPosition], news_monitor: NewsMonitor | None
) -> str:
    events = _portfolio_news_matches(positions, news_monitor)
    if not events:
        return """<div class="portfolio-notes"><strong>基本面事件复核</strong><br>
        <span class="muted">暂未匹配到直接持仓 ticker 的重要新闻。ETF 仍需结合底层持仓与新闻面板复核；没有匹配不代表没有事件风险。</span></div>"""
    rows = "".join(
        f'<li><a href="{escape(event.url)}" target="_blank" rel="noopener noreferrer">{escape(event.title)}</a>'
        f' <span class="muted">· {escape("、".join(event.tickers))} · {escape(event.impact)}</span></li>'
        for event in events
    )
    return f"""<div class="portfolio-notes"><strong>基本面事件复核（直接 ticker 匹配）</strong>
      <ul>{rows}</ul>
      <span class="muted">事件层用于复核回撤性质，不直接覆盖技术判断，也不构成机械加减仓信号。</span>
    </div>"""


def _portfolio_news_matches(
    positions: list[PortfolioPosition], news_monitor: NewsMonitor | None
) -> list[NewsEvent]:
    if news_monitor is None:
        return []
    symbols = {position.symbol.upper().split(".")[0] for position in positions}
    return [
        event
        for event in news_monitor.events
        if symbols.intersection(ticker.upper().split(".")[0] for ticker in event.tickers)
    ][:5]


def _render_portfolio_row(position: PortfolioPosition) -> str:
    pnl_class = _pnl_class(position.unrealized_pnl_gbp)
    day_class = _pnl_class(position.day_change_pct)
    scope = "ETF观察池" if position.monitor_status == "covered" else "待穿透分析"
    return f"""<tr>
      <td><span class="portfolio-symbol">{escape(position.symbol)}</span><br><span class="portfolio-scope">{scope}<br>{escape(position.price_source or "行情来源待确认")}</span></td>
      <td>{escape(_fmt_quantity(position.quantity))}</td>
      <td>{escape(_fmt_gbp(position.average_cost_gbp))}</td>
      <td>{escape(_fmt_native(position.current_price_native, position.native_currency))}</td>
      <td>{escape(_fmt_native(position.market_value_native, position.native_currency))}</td>
      <td>{escape(_fmt_gbp(position.market_value_gbp))}</td>
      <td>{escape(_fmt_fx(position))}</td>
      <td class="{pnl_class}">未实现 {escape(_fmt_signed_gbp(position.unrealized_pnl_gbp))}<br>
        <span class="portfolio-scope">已实现净额 {escape(_fmt_signed_gbp(position.realized_pnl_gbp))} · 股息 {escape(_fmt_signed_gbp(position.dividend_income_gbp))} · 隐含成本 {escape(_fmt_gbp(position.implied_trading_cost_gbp))} · 合计 {escape(_fmt_signed_gbp(position.total_return_gbp))}</span><br>
        <span class="portfolio-scope">卖出不亏平衡价 {escape(_fmt_breakeven(position))}</span></td>
      <td class="{pnl_class}">{escape(_fmt_pct(position.unrealized_pnl_pct))}</td>
      <td class="{day_class}">{escape(_fmt_pct(position.day_change_pct))}</td>
      <td>{escape(_fmt_peak_watch(position))}</td>
      <td>{position.weight_pct:.2f}%</td>
    </tr>"""


def _render_sensitivity_panel(monitor: ETFMonitor) -> str:
    rows = "\n".join(_render_sensitivity_row(asset) for asset in monitor.assets if asset.status != "missing")
    return f"""<details class="sensitivity-panel">
      <summary>相关性与Beta面板（滚动60日）</summary>
      <div class="small-note" style="padding:0 14px 8px;">用于观察ETF是否正在转化为其他宏观代理变量。相关性范围为 -1 至 +1；Beta表示因子变化一个单位时ETF日收益的历史敏感度。10年期收益率Beta按每上行10bp计。</div>
      <div class="portfolio-table-scroll">
        <table class="sensitivity-table">
          <thead><tr><th>ETF</th><th>主题</th><th>Nasdaq 100</th><th>DXY</th><th>10Y yield</th><th>Gold</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </details>"""


def _render_sensitivity_row(asset: ETFAssetMonitor) -> str:
    sensitivity_map = {item.factor: item for item in asset.sensitivities}
    return f"""<tr>
      <td><strong>{escape(asset.symbol)}</strong></td>
      <td>{escape(asset.theme)}</td>
      <td>{escape(_fmt_sensitivity(sensitivity_map.get("qqq")))}</td>
      <td>{escape(_fmt_sensitivity(sensitivity_map.get("dxy")))}</td>
      <td>{escape(_fmt_sensitivity(sensitivity_map.get("tnx")))}</td>
      <td>{escape(_fmt_sensitivity(sensitivity_map.get("gold")))}</td>
    </tr>"""


def _render_etf_group(group: tuple[str, str, list[ETFAssetMonitor]], index: int = 0) -> str:
    title, description, assets = group
    rows = "\n".join(_render_etf_row(asset) for asset in assets)
    cards = "\n".join(_render_etf_card(asset) for asset in assets)
    symbols = "、".join(asset.symbol for asset in assets)
    stats = _etf_group_stats(assets)
    comparison = _etf_group_comparison(assets)
    open_attr = " open" if index == 0 else ""
    return f"""<details class="etf-group"{open_attr}>
      <summary>
        <div class="etf-group-head">
          <div>
            <div class="etf-group-title">{escape(title)}</div>
            <div class="etf-group-meta">{escape(description)} · {escape(symbols)}</div>
          </div>
          <div class="etf-group-stats">{escape(stats)}</div>
        </div>
      </summary>
      <div class="etf-group-body">
        <div class="small-note">{escape(comparison)}</div>
        <div class="table-scroll">
      <table class="etf-table">
        <thead>
          <tr>
            <th>ETF</th>
            <th>主题</th>
            <th>价格</th>
            <th>1D / 日波动σ</th>
            <th>1M</th>
            <th>RSI14</th>
            <th>SMA13/200</th>
            <th>估值/资产属性</th>
            <th>规模/流动性</th>
            <th>PE位置</th>
            <th>新增仓位环境</th>
            <th>拥挤度</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
        </div>
        <div class="etf-cards">
          <div class="etf-card-grid">{cards}</div>
        </div>
        <div class="etf-group-end">本组结束：{escape(title)} · 共{len(assets)}只</div>
      </div>
    </details>"""


def _summarize_etf_warnings(warnings: list[str]) -> str:
    cached = [item for item in warnings if "使用本地ETF缓存" in item]
    network_blocked = any("WinError 10013" in item for item in warnings)
    remaining = [item for item in warnings if item not in cached]
    parts: list[str] = []
    if cached:
        parts.append(f"{len(cached)}只ETF使用本地缓存")
    if network_blocked:
        parts.append("本机网络权限阻止Yahoo实时抓取；该降级并非由非交易日直接触发")
    if remaining:
        parts.append("；".join(remaining[:3]))
    return "；".join(parts) + "。"


def _group_etf_assets(assets: list[ETFAssetMonitor]) -> list[tuple[str, str, list[ETFAssetMonitor]]]:
    definitions = [
        ("宽基与核心资产", "组合底仓与主要指数风险暴露", {"Global Equity", "S&P 500", "UK Large Cap", "Nasdaq 100"}),
        ("AI、科技与软件链", "AI基础设施、信息技术、云软件、网络安全与自动化", {"US Technology", "AI Infrastructure", "Artificial Intelligence", "Cloud Software", "Cybersecurity", "Robotics & Automation"}),
        ("光通信与Photonics", "光模块、激光器、光学元件与AI数据中心互连产业链", {"Optical Technology & Photonics"}),
        ("半导体", "全球半导体周期与AI算力核心上游", {"Semiconductor"}),
        ("量子计算", "高beta前沿主题，适合单独观察热度与波动", {"Quantum Computing"}),
        ("韩国权益与存储链", "Samsung Electronics、SK hynix及韩国科技/工业周期暴露", {"South Korea Equity"}),
        ("军工与防务", "全球/欧洲防务、网络防务与防务创新", {"Defence", "European Defence", "Defence Innovation"}),
        ("现金与短债", "现金替代、超短债、货币市场与短久期防守仓", {"GBP Ultrashort Bond / Cash-like", "Cash-like", "Money Market", "Short Duration Bond"}),
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


def _render_etf_notes(title: str, items: list[str]) -> str:
    if not items:
        return ""
    rows = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f'<div class="strategy-list"><strong>{escape(title)}</strong><ul>{rows}</ul></div>'


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


def _render_etf_row(asset: ETFAssetMonitor) -> str:
    crowding_status = _crowding_status_class(asset.crowding_score)
    entry_status = _entry_status_class(asset.entry_score)
    price = _fmt_price(asset.value, asset.currency)
    one_day = _fmt_pct(asset.change_pct)
    sigma = _fmt_sigma(asset.daily_sigma)
    one_month = _fmt_pct(asset.momentum_1m)
    rsi = "N/A" if asset.rsi14 is None else f"{asset.rsi14:.1f}"
    trend_main, trend_detail = _fmt_trend_cell(asset)
    valuation, valuation_detail, pe_position = _fmt_valuation_block(asset)
    valuation_source = _fmt_valuation_source(asset)
    liquidity = _fmt_liquidity(asset)
    symbol = f"{escape(asset.symbol)} · {escape(asset.provider)}"
    cost = f"TER {escape(_fmt_ter(asset.ter))} · {escape(_ter_label(asset.ter))}"
    entry_cell = _render_entry_cell(asset, entry_status, compact=False)
    return f"""<tr>
      <td><strong>{symbol}</strong><br><span class="muted">{escape(asset.label)}</span><br><span class="muted">{cost}</span><br><span class="muted">审计：{escape(asset.metadata_status)}</span></td>
      <td>{escape(asset.theme)}<br><span class="muted">{escape(asset.trend_label)}</span></td>
      <td>{escape(price)}</td>
      <td>{escape(one_day)}<br><span class="muted">{escape(sigma)} · {escape(asset.sigma_label)}</span></td>
      <td>{escape(one_month)}</td>
      <td>{escape(rsi)}<br><span class="muted">{escape(asset.momentum_label)}</span></td>
      <td>{escape(trend_main)}<br><span class="muted">{escape(trend_detail)}</span></td>
      <td>{escape(valuation)}<br><span class="muted">{escape(valuation_detail)}</span><br><span class="muted">{escape(valuation_source)}</span></td>
      <td>{escape(asset.liquidity_label)}<br><span class="muted">{escape(liquidity)}</span></td>
      <td>{escape(pe_position)}</td>
      <td>{entry_cell}</td>
      <td><span class="tag {crowding_status}">{asset.crowding_score}/100</span><br><span class="muted">{escape(asset.crowding_label)}</span></td>
    </tr>"""


def _render_etf_card(asset: ETFAssetMonitor) -> str:
    crowding_status = _crowding_status_class(asset.crowding_score)
    entry_status = _entry_status_class(asset.entry_score)
    price = _fmt_price(asset.value, asset.currency)
    one_day = _fmt_pct(asset.change_pct)
    one_month = _fmt_pct(asset.momentum_1m)
    rsi = "N/A" if asset.rsi14 is None else f"{asset.rsi14:.1f}"
    valuation, valuation_detail, _ = _fmt_valuation_block(asset)
    valuation_source = _fmt_valuation_source(asset)
    liquidity = _fmt_liquidity(asset)
    trend_line, trend_detail = _fmt_trend_cell(asset)
    cost_line = f"TER {_fmt_ter(asset.ter)} · {_ter_label(asset.ter)}"
    entry_cell = _render_entry_cell(asset, entry_status, compact=True)
    return f"""<article class="etf-card">
      <div class="etf-card-head">
        <div>
          <div class="etf-card-title">{escape(asset.symbol)} · {escape(asset.provider)}</div>
          <div class="muted">{escape(asset.label)}</div>
        </div>
        <span class="tag {crowding_status}">{asset.crowding_score}/100</span>
      </div>
      <div class="etf-card-price">{escape(price)}</div>
      <div class="etf-card-meta">{escape(asset.theme)} · {escape(asset.trend_label)} · {escape(cost_line)}</div>
      <div class="etf-card-lines">
        <div class="etf-card-line"><strong>1D / 1M</strong>{escape(one_day)} / {escape(one_month)}<br>{escape(_fmt_sigma(asset.daily_sigma))}</div>
        <div class="etf-card-line"><strong>RSI14</strong>{escape(rsi)}<br>{escape(asset.momentum_label)}</div>
        <div class="etf-card-line"><strong>趋势/稳定性</strong>{escape(trend_line)}<br>{escape(trend_detail)}</div>
        <div class="etf-card-line"><strong>估值/资产属性</strong>{escape(valuation)}<br>{escape(valuation_detail)} · {escape(valuation_source)}</div>
        <div class="etf-card-line"><strong>规模/流动性</strong>{escape(asset.liquidity_label)}<br>{escape(liquidity)}</div>
        <div class="etf-card-line">{entry_cell}</div>
      </div>
    </article>"""


def _fmt_valuation_source(asset: ETFAssetMonitor) -> str:
    if asset.theme == "Gold":
        return "资产属性：实物黄金ETC"
    if not asset.equity_like:
        return "资产属性：非权益ETF"
    if asset.valuation_source == "unavailable":
        return "估值源：暂无"
    as_of = f" · 最近披露：{asset.valuation_as_of}" if asset.valuation_as_of else ""
    return f"估值源：{asset.valuation_source}{as_of}"


def _fmt_trend_cell(asset: ETFAssetMonitor) -> tuple[str, str]:
    if asset.theme == "GBP Ultrashort Bond / Cash-like":
        main = "稳定性/短端利率敏感"
        detail = f"1M {_fmt_pct(asset.momentum_1m)} / 日波动 {_fmt_sigma(asset.daily_sigma)} · {asset.trend_stretch_label}"
        return main, detail
    main = f"{_fmt_price(asset.sma13, asset.currency)} / {_fmt_price(asset.sma200, asset.currency)}"
    detail = f"距200日线 {_fmt_pct(asset.distance_sma200)} / {_fmt_sigma_200d(asset.trend_sigma_200d)} · {asset.trend_stretch_label}"
    return main, detail


def _render_entry_cell(asset: ETFAssetMonitor, status_class: str, compact: bool) -> str:
    note = asset.risk_management_note if compact else asset.entry_note
    return (
        f'<div class="entry-main">'
        f'<span class="tag {status_class}">{asset.entry_score}/100</span>'
        f'<strong>{escape(asset.entry_label)}</strong>'
        f'<span class="entry-note">{escape(note)}</span>'
        f'</div>'
        f'<details class="entry-details">'
        f'<summary>相似环境与模型质检</summary>'
        f'{_render_backtest_details(asset)}'
        f'</details>'
    )


def _render_backtest_details(asset: ETFAssetMonitor) -> str:
    backtest = asset.backtest
    if backtest is None:
        return "<div>当前相似市场环境：暂无。</div>"
    if backtest.sample_size <= 0:
        return f"<div>当前相似市场环境：{escape(backtest.reliability)}。</div>"
    similar_path = " / ".join(
        [
            _fmt_pct(backtest.similar_forward_1m),
            _fmt_pct(backtest.similar_forward_3m),
            _fmt_pct(backtest.similar_forward_6m),
        ]
    )
    threshold_path = " / ".join(
        [
            _fmt_pct(backtest.good_forward_1m),
            _fmt_pct(backtest.good_forward_3m),
            _fmt_pct(backtest.good_forward_6m),
        ]
    )
    threshold_summary = (
        f"阈值质检：{backtest.reliability}；"
        f"≥{backtest.threshold}且拥挤<{backtest.crowding_ceiling}样本 {backtest.good_count}/{backtest.sample_size}，"
        f"1/3/6M {threshold_path}。"
    )
    rows = _threshold_calibration_rows(asset)
    calibration = (
        f'<details class="threshold-details"><summary>查看60/70/75阈值校准</summary>'
        f'<div>{escape(backtest.best_threshold_label)}</div>'
        + "".join(f'<span class="threshold-row">{escape(row)}</span>' for row in rows)
        + "</details>"
        if rows
        else ""
    )
    phase_count = backtest.similar_phase_count or backtest.similar_count
    tail_summary = _fmt_tail_phase_summary(backtest)
    sample_rows = "".join(
        f"<tr><td>{escape(item.phase_id or '旧缓存')}</td><td>{'是' if item.phase_representative else ''}</td>"
        f"<td>{escape(item.as_of)}</td><td>{item.distance:.2f}</td><td>{escape(_fmt_rate(item.feature_coverage_pct))}</td>"
        f"<td>{escape(_fmt_pct(item.forward_1m))}</td><td>{escape(_fmt_pct(item.forward_3m))}</td>"
        f"<td>{escape(_fmt_pct(item.forward_6m))}</td><td>{escape(_fmt_pct(item.drawdown_3m))}</td></tr>"
        for item in backtest.similar_samples
    )
    tail_cases = "".join(
        f'<div class="tail-case"><strong>尾部案例：{escape(item.as_of)} · {escape(item.phase_id)}</strong>'
        f'<div>起点脆弱性：{escape(item.start_state)}</div>'
        f'<div>之后1/3/6M：{escape(_fmt_pct(item.forward_1m))} / {escape(_fmt_pct(item.forward_3m))} / '
        f'{escape(_fmt_pct(item.forward_6m))}；3M回撤 {escape(_fmt_pct(item.drawdown_3m))}</div>'
        f'<ul>{"".join(f"<li>{escape(note)}</li>" for note in item.driver_notes)}</ul></div>'
        for item in backtest.similar_samples
        if item.phase_representative and item.tail_case
    )
    tail_panel = (
        f'<details class="threshold-details"><summary>查看历史尾部案例与事件线索</summary>'
        f'<div>以下案例用于识别脆弱起点与后续催化剂，不表示当前市场会机械重复历史路径。</div>'
        f'{tail_cases}</details>'
        if tail_cases
        else ""
    )
    samples = (
        f'<details class="threshold-details"><summary>查看walk-forward相似样本日期与路径</summary>'
        f'<div>原始相似样本 {backtest.similar_count} 个，按相邻行情窗口聚合为 {phase_count} 个独立历史阶段。'
        f'统计值基于各阶段最相似的代表样本。</div>'
        f'<div>独立阶段代表样本3M路径分布 P25 / 中位数 / P75：{escape(_fmt_pct(backtest.similar_forward_3m_p25))} / '
        f'{escape(_fmt_pct(backtest.similar_forward_3m_p50))} / {escape(_fmt_pct(backtest.similar_forward_3m_p75))}</div>'
        f'<div class="portfolio-table-scroll"><table><thead><tr><th>阶段</th><th>代表</th><th>样本日期</th><th>距离</th><th>特征覆盖</th><th>1M</th><th>3M</th><th>6M</th><th>3M回撤</th></tr></thead>'
        f'<tbody>{sample_rows}</tbody></table></div></details>'
        if sample_rows
        else ""
    )
    return (
        f"<div>当前相似市场环境：{backtest.similar_count}个历史样本，聚合为{phase_count}个独立历史阶段；"
        f"之后1/3/6M {escape(similar_path)}，3M胜率 {escape(_fmt_rate(backtest.similar_hit_rate_3m))}，"
        f"3M回撤 {escape(_fmt_pct(backtest.similar_max_drawdown_3m))}。</div>"
        f"<div>相似度可信度：{escape(backtest.similarity_confidence)}；代表样本平均特征覆盖率 "
        f"{escape(_fmt_rate(backtest.similar_avg_feature_coverage_pct))}。</div>"
        f"<div>{escape(tail_summary)}</div>"
        f"<div>{escape(threshold_summary)}</div>"
        f"{samples}"
        f"{tail_panel}"
        f"{calibration}"
    )


def _crowding_status_class(score: int) -> str:
    if score >= 70:
        return "tag-hot"
    if score <= 35:
        return "tag-cool"
    return ""


def _entry_status_class(score: int) -> str:
    if score >= 70:
        return "tag-entry-good"
    if score >= 55:
        return "tag-entry-watch"
    return "tag-entry-bad"


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


def _fmt_pe_position(asset: ETFAssetMonitor) -> str:
    if asset.theme == "Gold":
        return "不适用"
    if not asset.equity_like:
        return "不适用"
    if asset.pe_percentile is not None:
        return f"分位 {asset.pe_percentile:.0f}%"
    if asset.pe_high_1y_ratio is not None:
        return f"约{asset.pe_high_1y_ratio:.0f}% / 1Y高点"
    return "样本不足"


def _fmt_valuation_block(asset: ETFAssetMonitor) -> tuple[str, str, str]:
    if asset.theme == "Gold":
        return "不适用：实物黄金ETC", "观察实际利率、美元与金价趋势", "不适用"
    if not asset.equity_like:
        return "不适用：久期/收益率/利率风险", "观察久期、收益率曲线、利率风险与流动性", "不适用"
    valuation = f"{_fmt_plain(asset.pe)} / {_fmt_plain(asset.forward_pe)} / {_fmt_plain(asset.pb)}"
    return valuation, asset.valuation_label, _fmt_pe_position(asset)


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
    phase_count = backtest.similar_phase_count or backtest.similar_count
    return (
        f"当前相似市场环境：{backtest.similar_count}个历史样本，聚合为{phase_count}个独立历史阶段；"
        f"之后1/3/6M {similar_path}，3M胜率 {_fmt_rate(backtest.similar_hit_rate_3m)}，"
        f"3M回撤 {_fmt_pct(backtest.similar_max_drawdown_3m)}。"
        f"相似度可信度：{backtest.similarity_confidence}，特征覆盖率{_fmt_rate(backtest.similar_avg_feature_coverage_pct)}。"
        f"{_fmt_tail_phase_summary(backtest)}"
        f"阈值质检：{backtest.reliability}；{backtest.best_threshold_label}。"
    )


def _fmt_tail_phase_summary(backtest: ETFBacktestStats) -> str:
    phase_count = backtest.similar_phase_count or backtest.similar_count
    if phase_count <= 0:
        return "尾部路径观察：暂无足够的独立历史阶段。"
    if backtest.similar_tail_phase_count <= 0:
        return "尾部路径观察：相似独立阶段中暂未出现显著负收益或较大回撤案例。"
    distance = (
        f"{backtest.similar_closest_tail_distance:.2f}"
        if backtest.similar_closest_tail_distance is not None
        else "N/A"
    )
    return (
        f"尾部路径观察：{backtest.similar_tail_phase_count}/{phase_count}个独立阶段出现负收益或较大回撤，"
        f"占比{_fmt_rate(backtest.similar_tail_phase_rate)}；最接近尾部案例距离{distance}。"
        "这反映当前起点与历史脆弱窗口的接近程度，不是回撤概率预测。"
    )


def _fmt_threshold_calibration(asset: ETFAssetMonitor) -> str:
    backtest = asset.backtest
    if backtest is None or not backtest.threshold_calibrations:
        return "阈值校准：暂无"
    return f"阈值校准：{backtest.best_threshold_label}；" + " | ".join(_threshold_calibration_rows(asset))


def _threshold_calibration_rows(asset: ETFAssetMonitor) -> list[str]:
    backtest = asset.backtest
    if backtest is None or not backtest.threshold_calibrations:
        return []
    rows = []
    for item in backtest.threshold_calibrations:
        path = " / ".join([_fmt_pct(item.forward_1m), _fmt_pct(item.forward_3m), _fmt_pct(item.forward_6m)])
        rows.append(
            f"≥{item.threshold}且拥挤<{item.crowding_ceiling} {item.label}：{item.sample_count}样本，1/3/6M {path}，"
            f"胜率{_fmt_rate(item.hit_rate_3m)}，回撤{_fmt_pct(item.max_drawdown_3m)}"
        )
    return rows


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def _render_group(title: str, keys: list[str], metrics: dict[str, ScoredMetric]) -> str:
    cards = [metrics[key] for key in keys if key in metrics]
    if not cards:
        return ""
    rendered = "\n".join(_render_metric_card(item) for item in cards)
    return f"""<section class="panel">
      <h2>{escape(title)}</h2>
      <div class="metric-grid">{rendered}</div>
    </section>"""


def _render_metric_card(item: ScoredMetric) -> str:
    metric = item.metric
    change_text, change_class = _change_text(metric)
    status_class = _status_class(metric)
    return f"""<article class="metric">
      <div class="metric-head">
        <div>
          <div class="metric-name">{escape(metric.label)}</div>
          <div class="symbol">{escape(metric.symbol)} · {escape(metric.source)}</div>
        </div>
        <div class="{status_class}">{escape(_status_label(metric))}</div>
      </div>
      <div class="metric-value">{escape(_fmt(metric.value, metric.unit))}</div>
      <div class="{change_class}">{escape(change_text)}</div>
      <div class="signal">{escape(item.signal)} · 风险分 {item.score}</div>
      <div class="metric-note">{escape(item.note)}</div>
    </article>"""


def _render_data_row(metric: MarketMetric, timezone_name: str = "America/New_York") -> str:
    status_class = _status_class(metric)
    date_text = metric.as_of.isoformat() if metric.as_of else "无有效值"
    fetched = _format_metric_time(metric.fetched_at, timezone_name)
    return f"""<tr>
      <td>{escape(metric.label)}</td>
      <td>{escape(metric.symbol)}</td>
      <td>{escape(metric.source)}</td>
      <td>{escape(date_text)}</td>
      <td>{escape(fetched)}</td>
      <td class="{status_class}">{escape(_status_label(metric))}</td>
    </tr>"""


def _format_metric_time(timestamp: datetime, timezone_name: str) -> str:
    return format_timestamp(timestamp, timezone_name)


def _render_weight_row(key: str, value: float, metrics: dict[str, ScoredMetric]) -> str:
    label = metrics[key].metric.label if key in metrics else key
    return f"""<div>
      <div>{escape(label)} <strong>{value:.0%}</strong></div>
      <div class="bar"><span style="width:{value * 100:.1f}%"></span></div>
    </div>"""


def _change_text(metric: MarketMetric) -> tuple[str, str]:
    if metric.change is None or metric.change_pct is None:
        return "变化：N/A", "summary"
    sign = "+" if metric.change >= 0 else ""
    text = f"{sign}{_fmt(metric.change, metric.unit)} / {sign}{metric.change_pct:.2f}%"
    css = "change-up" if metric.change >= 0 else "change-down"
    return text, css


def _status_label(metric: MarketMetric) -> str:
    if metric.status == "ok" and metric.freshness == "live":
        return "实时/收盘"
    if metric.status == "ok" and metric.freshness == "recent-valid":
        return "最近有效值"
    if metric.status == "ok" and metric.freshness == "cache":
        return "使用缓存"
    if metric.status == "ok" and metric.freshness == "derived":
        return "估算/派生"
    if metric.status == "stale":
        return "滞后"
    if metric.status == "suspicious":
        return "数据异常"
    return "缺失"


def _status_class(metric: MarketMetric) -> str:
    if metric.status == "ok" and metric.freshness in {"live", "recent-valid", "derived"}:
        return "status-ok"
    if metric.status == "ok" and metric.freshness == "cache":
        return "status-warn"
    if metric.status in {"suspicious", "stale"}:
        return "status-warn"
    return "status-bad"


def _fmt_price(value: float | None, currency: str) -> str:
    if value is None:
        return "N/A"
    if currency == "GBP":
        return f"£{value:.2f}"
    if currency == "USD":
        return f"${value:.2f}"
    if currency == "EUR":
        return f"€{value:.2f}"
    return f"{value:.2f}"


def _fmt_native(value: float | None, currency: str) -> str:
    return _fmt_price(value, currency) if currency else ("N/A" if value is None else f"{value:,.2f}")


def _fmt_fx(position) -> str:
    if not position.fx_pair:
        return "GBP"
    if position.fx_rate is None:
        return f"{position.fx_pair} N/A"
    return f"{position.fx_pair} {position.fx_rate:.4f}"


def _fmt_breakeven(position: PortfolioPosition) -> str:
    if position.breakeven_price_gbp is None:
        return "N/A"
    rate = (
        f"；估算卖出成本率 {position.estimated_exit_cost_rate_pct:.4f}%"
        if position.estimated_exit_cost_rate_pct is not None
        else ""
    )
    if position.native_currency and position.native_currency != "GBP":
        native = _fmt_native(position.breakeven_price_native, position.native_currency)
        return f"{native} / {_fmt_gbp(position.breakeven_price_gbp)}{rate}"
    return f"{_fmt_gbp(position.breakeven_price_gbp)}{rate}"


def _fmt_peak_watch(position: PortfolioPosition) -> str:
    if position.drawdown_from_year_peak_pct is None:
        return "N/A"
    peak = _fmt_native(position.year_peak_price_native, position.native_currency)
    if "现金/短债" in position.drawdown_regime:
        sigma = f" · 回撤约{_fmt_plain(position.pullback_sigma_1m)}σ(1M)" if position.pullback_sigma_1m is not None else ""
        return (
            f"{_fmt_pct(position.drawdown_from_year_peak_pct)} · 峰值 {peak}"
            f"（{position.year_peak_date or '日期待确认'}）{sigma} · {position.drawdown_regime}"
        )
    sma = (
        f" · SMA200 {_fmt_native(position.sma200_native, position.native_currency)}"
        f" / {_fmt_pct(position.distance_sma200_pct)}"
        if position.sma200_native is not None
        else ""
    )
    sigma = f" · 回撤约 {_fmt_plain(position.pullback_sigma_1m)}σ(1M)" if position.pullback_sigma_1m is not None else ""
    label = position.drawdown_regime or position.peak_watch or "回撤观察"
    return f"{_fmt_pct(position.drawdown_from_year_peak_pct)} · 峰值 {peak}（{position.year_peak_date or '日期待确认'}）{sma}{sigma} · {label}"


def _fmt_sensitivity(item) -> str:
    if item is None or item.correlation is None or item.beta is None:
        return "N/A"
    return f"ρ {item.correlation:+.2f} / β {item.beta:+.2f}（{item.beta_unit}）"


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


def _fmt_distance(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _fmt_gbp(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"£{value:,.2f}"


def _fmt_signed_gbp(value: float | None) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else "-"
    return f"{sign}£{abs(value):,.2f}"


def _fmt_quantity(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def _pnl_class(value: float | None) -> str:
    if value is None:
        return ""
    return "pnl-up" if value >= 0 else "pnl-down"


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
