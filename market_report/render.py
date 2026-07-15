from __future__ import annotations

import json
from dataclasses import fields
from datetime import datetime
from html import escape

from .data_sources import MarketMetric
from .event_risk_ledger import EventRiskLedger, EventRiskLedgerEntry
from .etf_monitor import ETFAssetMonitor, ETFMonitor, PortfolioPosition
from .mag7_capital_network import AggregateCapitalDisclosure, CapitalRelation, Mag7CapitalNetwork
from .macro_brief import MacroDailyBrief, build_macro_daily_brief
from .news_monitor import NewsEvent, NewsMonitor
from .option_portfolio import option_closeout_snapshot_from_groups
from .options_gamma import OptionGammaAssessment, OptionsGammaMonitor
from .options_sentiment import OptionsSentimentMonitor, TickerShortPremiumContext
from .policy_risk_monitor import PolicyRiskFactor, PolicyRiskMonitor
from .portfolio_events import PortfolioEventMonitor
from .scoring import IronCondorAssessment, ScoreDriver, ScoredMetric, ScoredReport
from .shock_backtest import MarketShockBacktest, MarketShockSample
from .technical_indicators import MacdSnapshot
from .technical_swing import SwingAssessment, SwingZone, TechnicalScorecard, TechnicalSwingReport
from .time_utils import format_timestamp


DISPLAY_GROUPS = [
    ("权益风险偏好", ["nasdaq", "sp500", "russell2000"]),
    ("情绪、波动与压力", ["cnn_fear_greed", "naaim_exposure", "vix9d", "vix", "vix3m", "vix_future_1", "vix_future_2", "vix_future_3", "vvix", "vixeq", "cor1m", "move", "credit_spread_hy"]),
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
    policy_risk_monitor = _render_policy_risk_monitor(report.policy_risk_monitor)
    event_risk_ledger = _render_event_risk_ledger(report.event_risk_ledger)
    news_monitor = _render_news_monitor(report.news_monitor)
    mag7_capital_network = _render_mag7_capital_network(report.mag7_capital_network)
    etf_monitor = _render_etf_monitor(
        report.etf_monitor,
        report.news_monitor,
        report.portfolio_event_monitor,
        report.metric_history,
    )
    technical_swing = _render_technical_swing(report.technical_swing)
    options_sentiment = _render_options_sentiment(report.options_sentiment)
    options_gamma = _render_options_gamma(report.options_gamma)
    macro_brief = _render_macro_daily_brief(build_macro_daily_brief(report))

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
    .decision-brief {{ margin: 4px 0 18px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
    .decision-brief-head {{ display: flex; justify-content: space-between; gap: 16px; padding: 14px 2px 10px; align-items: end; }}
    .decision-brief-title {{ font-size: 20px; font-weight: 760; }}
    .decision-posture {{ color: var(--accent); font-size: 18px; font-weight: 760; }}
    .decision-grid {{ display: grid; grid-template-columns: 1.05fr 1.2fr 1.35fr 1.2fr; border-top: 1px solid var(--line); }}
    .decision-cell {{ padding: 13px 14px 14px 0; min-width: 0; }}
    .decision-cell + .decision-cell {{ border-left: 1px solid var(--line); padding-left: 14px; }}
    .decision-cell h2 {{ font-size: 13px; color: var(--muted); margin-bottom: 7px; }}
    .decision-cell ul {{ padding-left: 17px; color: var(--subtle); }}
    .decision-cell li {{ margin: 5px 0; }}
    .decision-signal {{ margin: 6px 0; }}
    .decision-signal strong {{ display: block; }}
    .decision-signal span {{ color: var(--muted); font-size: 12px; }}
    .report-layer {{ margin: 16px 0; }}
    .report-layer > summary {{ cursor: pointer; list-style: none; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 13px 2px; }}
    .report-layer > summary::-webkit-details-marker {{ display: none; }}
    .layer-title {{ font-size: 18px; font-weight: 760; }}
    .layer-note {{ color: var(--muted); font-size: 13px; margin-top: 3px; }}
    .layer-body {{ padding-top: 14px; }}
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
    .swing-zone-details {{ margin-top: 8px; color: var(--subtle); font-size: 12px; }}
    .swing-zone-details summary {{ cursor: pointer; color: #bfdbfe; }}
    .swing-zone-details ul {{ margin: 6px 0 0 18px; padding: 0; }}
    .gamma-panel {{ margin-bottom: 14px; }}
    .gamma-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }}
    .gamma-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: rgba(255,255,255,.025); min-width: 0; }}
    .gamma-card-head {{ display: flex; justify-content: space-between; gap: 10px; align-items: start; }}
    .gamma-title {{ font-weight: 760; font-size: 16px; }}
    .gamma-regime {{ color: #bfdbfe; font-weight: 700; text-align: right; }}
    .gamma-values {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin-top: 10px; }}
    .gamma-value {{ border-top: 1px solid var(--line); padding-top: 7px; color: var(--subtle); font-size: 12px; min-width: 0; }}
    .gamma-value strong {{ display: block; color: var(--text); font-size: 13px; overflow-wrap: anywhere; }}
    .gamma-note {{ color: var(--subtle); font-size: 12px; margin-top: 9px; }}
    .gamma-warning {{ color: #fcd34d; font-size: 12px; margin-top: 7px; }}
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
      .hero, .grid, .columns, .strategy-head, .strategy-lists, .swing-grid, .gamma-grid, .decision-grid {{ grid-template-columns: 1fr; }}
      .datebox {{ text-align: left; }}
      .etf-group-head {{ display: block; }}
      .etf-group-stats {{ text-align: left; margin-top: 7px; }}
      .portfolio-head {{ grid-template-columns: 1fr; }}
      .portfolio-total {{ text-align: left; }}
      .portfolio-exposure-grid {{ grid-template-columns: 1fr; }}
      .capital-grid {{ grid-template-columns: 1fr; }}
      .decision-cell + .decision-cell {{ border-left: 0; border-top: 1px solid var(--line); padding-left: 0; }}
      .table-scroll {{ display: none; }}
      .etf-cards {{ display: block; }}
    }}
    @media (max-width: 620px) {{
      .topbar, .metric-grid {{ grid-template-columns: 1fr; }}
      .etf-card-grid, .etf-card-lines {{ grid-template-columns: 1fr; }}
      .swing-values {{ grid-template-columns: 1fr 1fr; }}
      .gamma-values {{ grid-template-columns: 1fr 1fr; }}
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

    {macro_brief}

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

    <details class="report-layer" open>
      <summary><div class="layer-title">Layer 2 · Macro Workbench</div><div class="layer-note">Cross-asset confirmation, policy risk, volatility context, and unresolved macro variables.</div></summary>
      <div class="layer-body">
        {iron_condor}
        {market_shock_backtest}
        {policy_risk_monitor}
        {event_risk_ledger}
        {options_sentiment}
        <section class="grid">{groups}</section>
        <section class="columns">
          <div class="panel"><h2>市场已知信息</h2><ul>{knowns}</ul></div>
          <div class="panel"><h2>未决宏观变量</h2><ul>{unknowns}</ul></div>
          <div class="panel"><h2>风险与策略含义</h2><ul>{risks}</ul><p>{escape(report.action)}</p></div>
        </section>
      </div>
    </details>

    <details class="report-layer">
      <summary><div class="layer-title">Layer 3 · Evidence & Deep Dive</div><div class="layer-note">Open when a signal needs verification: news, holdings, technicals, options detail, ETF research, weights, and source audit.</div></summary>
      <div class="layer-body">
        {news_monitor}
        {mag7_capital_network}
        {technical_swing}
        {options_gamma}
        {etf_monitor}
        <section class="columns">
          <div class="panel"><h2>自适应权重</h2>{weights}</div>
          {score_drivers}
          <div class="panel wide">
            <h2>数据源、最近有效值与新鲜度</h2>
            <table><thead><tr><th>指标</th><th>Ticker</th><th>来源</th><th>最近有效值</th><th>抓取时间（{escape(report.fetched_timezone)}）</th><th>状态</th></tr></thead><tbody>{data_rows}</tbody></table>
          </div>
        </section>
      </div>
    </details>

    <div class="footer">
      <span>免责声明：本报告仅用于宏观市场监控与研究参考，不构成投资建议。</span>
      <span>缓存、fallback、缺失与延迟状态均已显式标注；系统不会静默替代实时数据。</span>
    </div>
  </main>
</body>
</html>"""


def _render_macro_daily_brief(brief: MacroDailyBrief) -> str:
    signals = "".join(
        f'<div class="decision-signal"><strong>{escape(item.label)} · {escape(item.value)}</strong>'
        f'<span>{escape(item.interpretation)}</span></div>'
        for item in brief.signals
    ) or '<div class="muted">No material daily move available.</div>'
    actions = "".join(f"<li>{escape(item)}</li>" for item in brief.actions)
    invalidations = "".join(f"<li>{escape(item)}</li>" for item in brief.invalidations)
    return f"""<section class="decision-brief">
      <div class="decision-brief-head">
        <div><div class="kicker">Layer 1 · Daily Decision Brief</div><div class="decision-brief-title">Close-to-next-session macro posture</div></div>
        <div class="decision-posture">{escape(brief.posture)}</div>
      </div>
      <div class="decision-grid">
        <div class="decision-cell"><h2>STATE CHANGE</h2><div>{escape(brief.posture_note)}</div><div class="muted" style="margin-top:7px;">{escape(brief.score_change)}</div><div class="muted" style="margin-top:5px;">{escape(brief.transition)}</div><div style="margin-top:9px;">{escape(brief.liquidity_summary)}</div><div style="margin-top:9px;">{escape(brief.volatility_summary)}</div></div>
        <div class="decision-cell"><h2>ANOMALY MOVES</h2>{signals}<div class="muted" style="margin-top:7px;">{escape(brief.anomaly_method)}</div></div>
        <div class="decision-cell"><h2>PORTFOLIO & ACTION EVENT</h2><div>{escape(brief.exposure_change)}</div><div style="margin-top:9px;"><strong>{escape(brief.action_event)}</strong></div></div>
        <div class="decision-cell"><h2>PLAYBOOK & INVALIDATION</h2><ul>{actions}</ul><div class="muted" style="margin-top:8px;">结论失效条件</div><ul>{invalidations}</ul></div>
      </div>
    </section>"""


def _render_options_gamma(monitor: OptionsGammaMonitor | dict | None) -> str:
    monitor = _coerce_options_gamma_monitor(monitor)
    if monitor is None:
        return ""
    available = [item for item in monitor.assessments if item.data_status != "insufficient"]
    unavailable = [item for item in monitor.assessments if item.data_status == "insufficient"]
    warning_block = _render_options_gamma_unavailable(unavailable, monitor.warnings)
    if not available:
        return f"""<section class="panel gamma-panel gamma-panel-compact">
      <h2>Options Gamma / Dealer Hedging</h2>
      <div class="summary">{escape(monitor.summary)}</div>
      <div class="data-note">当前没有可用的免费期权链可用于 Gamma 估算；数据不足、UK/LSE 标的无可用期权链，或 Yahoo endpoint 被拒绝时仅合并显示原因。</div>
      {warning_block}
      <div class="disclaimer">Dealer gamma estimates are inferred from option-chain data, open interest, and trade-location heuristics. They are not direct observations of dealer books.</div>
    </section>"""

    cards = "".join(_render_options_gamma_card(item) for item in available)
    return f"""<section class="panel gamma-panel">
      <h2>Options Gamma / Dealer Hedging</h2>
      <div class="summary">{escape(monitor.summary)}</div>
      <div class="gamma-grid">{cards}</div>
      {warning_block}
      <div class="disclaimer">Dealer gamma estimates are inferred from option-chain data, open interest, and trade-location heuristics. They are not direct observations of dealer books.</div>
    </section>"""


def _coerce_options_gamma_monitor(monitor: OptionsGammaMonitor | dict | None) -> OptionsGammaMonitor | None:
    if monitor is None or isinstance(monitor, OptionsGammaMonitor):
        return monitor
    if not isinstance(monitor, dict):
        return None

    assessment_fields = {field.name for field in fields(OptionGammaAssessment)}
    assessments: list[OptionGammaAssessment] = []
    for item in monitor.get("assessments", []) or []:
        if isinstance(item, OptionGammaAssessment):
            assessments.append(item)
        elif isinstance(item, dict):
            payload = {key: value for key, value in item.items() if key in assessment_fields}
            payload.setdefault("warnings", [])
            try:
                assessments.append(OptionGammaAssessment(**payload))
            except TypeError:
                continue

    warnings = monitor.get("warnings", []) or []
    return OptionsGammaMonitor(
        generated_at=str(monitor.get("generated_at", "")),
        summary=str(monitor.get("summary", "")),
        assessments=assessments,
        warnings=list(warnings) if isinstance(warnings, list) else [str(warnings)],
    )


def _render_options_gamma_unavailable(
    unavailable: list[OptionGammaAssessment],
    monitor_warnings: list[str],
) -> str:
    if not unavailable and not monitor_warnings:
        return ""

    uk_symbols: list[str] = []
    unauthorized_symbols: list[str] = []
    other_items: list[str] = []
    covered_symbols: set[str] = set()

    for item in unavailable:
        symbol = item.symbol
        warning_text = " ".join(item.warnings)
        covered_symbols.add(symbol)
        if symbol.upper().endswith(".L"):
            uk_symbols.append(symbol)
        elif ("401" in warning_text or "Unauthorized" in warning_text) and "Alpha Vantage" not in warning_text:
            unauthorized_symbols.append(symbol)
        else:
            reason = warning_text or item.notable_flow or "期权链数据不足"
            other_items.append(f"{symbol}: {reason}")

    list_items: list[str] = []
    if uk_symbols:
        list_items.append(
            "UK/LSE UCITS 标的通常没有 Yahoo 可用期权链，保留在覆盖范围内但不展开 Gamma 卡片："
            f"{escape(_compact_symbol_list(uk_symbols))}"
        )
    if unauthorized_symbols:
        list_items.append(
            "Yahoo 免费期权链接口返回 401，暂不生成逐项 N/A 卡片："
            f"{escape(_compact_symbol_list(unauthorized_symbols))}"
        )
    if other_items:
        list_items.append("其他数据不足：" + escape("; ".join(other_items[:6])))

    extra_warnings = []
    for warning in monitor_warnings:
        if any(f"{symbol}:" in warning for symbol in covered_symbols):
            continue
        if warning not in extra_warnings:
            extra_warnings.append(warning)
    if extra_warnings:
        list_items.append("补充提示：" + escape("; ".join(extra_warnings[:3])))

    if not list_items:
        return ""

    bullets = "".join(f"<li>{item}</li>" for item in list_items)
    return f"""<div class="gamma-warning">
      <strong>数据不足与跳过项：</strong>
      <ul>{bullets}</ul>
    </div>"""


def _compact_symbol_list(symbols: list[str], limit: int = 12) -> str:
    unique = list(dict.fromkeys(symbols))
    if len(unique) <= limit:
        return ", ".join(unique)
    return ", ".join(unique[:limit]) + f" 等{len(unique)}个"


def _render_options_gamma_card(item: OptionGammaAssessment) -> str:
    warning_text = "；".join(item.warnings[:3])
    warning_html = f'<div class="gamma-warning">{escape(warning_text)}</div>' if warning_text else ""
    return f"""<article class="gamma-card">
      <div class="gamma-card-head">
        <div>
          <div class="gamma-title">{escape(item.symbol)}</div>
          <div class="muted">{escape(item.origin)} · {escape(item.data_status)}</div>
        </div>
        <div class="gamma-regime">{escape(item.regime_label)}</div>
      </div>
      <div class="gamma-values">
        <div class="gamma-value"><span>Spot / expiry</span><strong>{_fmt_plain(item.spot_price)} / {escape(item.nearest_expiry)}</strong></div>
        <div class="gamma-value"><span>Call wall</span><strong>{_fmt_gamma_level(item.call_wall)}</strong></div>
        <div class="gamma-value"><span>Put wall</span><strong>{_fmt_gamma_level(item.put_wall)}</strong></div>
        <div class="gamma-value"><span>近 spot 高OI</span><strong>{_fmt_gamma_level(item.near_spot_oi_strike)}</strong></div>
        <div class="gamma-value"><span>最大Gamma strike</span><strong>{_fmt_gamma_level(item.largest_gamma_strike)}</strong></div>
        <div class="gamma-value"><span>Pin观察</span><strong>{_fmt_gamma_level(item.pin_strike)}</strong></div>
        <div class="gamma-value"><span>Call gamma</span><strong>{_fmt_gamma_exposure(item.gross_call_gamma)}</strong></div>
        <div class="gamma-value"><span>Put gamma</span><strong>{_fmt_gamma_exposure(item.gross_put_gamma)}</strong></div>
        <div class="gamma-value"><span>来源</span><strong>Yahoo option chain</strong></div>
      </div>
      <div class="gamma-note">{escape(item.notable_flow)}</div>
      <div class="gamma-note">{escape(item.interpretation)}</div>
      {warning_html}
    </article>"""


def _fmt_gamma_level(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _fmt_gamma_exposure(value: float | None) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.2f}K"
    return f"{value:.2f}"


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
    zone_details = _render_swing_zone_details("支撑", support, item.current_price)
    zone_details += _render_swing_zone_details("阻力", resistance, item.current_price)
    scorecard_details = _render_swing_scorecard(item.scorecard)
    raw_data = _render_swing_raw_data(item)
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
        <div class="swing-value"><span>技术评分</span><strong>{_fmt_scorecard(item.scorecard)}</strong></div>
        <div class="swing-value"><span>量能</span><strong>{escape(item.volume_label)} · {_fmt_plain(item.volume_ratio)}x</strong></div>
        <div class="swing-value"><span>最近支撑</span><strong>{_fmt_swing_zone(support)}</strong></div>
        <div class="swing-value"><span>最近阻力</span><strong>{_fmt_swing_zone(resistance)}</strong></div>
        <div class="swing-value"><span>ATR失效观察</span><strong>{_fmt_plain(item.invalidation_level)}</strong></div>
        {holding}
      </div>
      {raw_data}
      {zone_details}
      {scorecard_details}
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


def _fmt_scorecard(scorecard: TechnicalScorecard | None) -> str:
    if scorecard is None:
        return "N/A"
    return f"{scorecard.total_score}/20 · {scorecard.interpretation}"


def _render_swing_raw_data(item: SwingAssessment) -> str:
    indicators = item.indicators
    benchmark = item.scorecard.benchmark_return_20d if item.scorecard else None
    relative = item.scorecard.relative_strength_20d if item.scorecard else None
    rows = (
        ("EMA5 / EMA10 / EMA21", f"{_fmt_raw_number(indicators.ema5)} / {_fmt_raw_number(indicators.ema10)} / {_fmt_raw_number(indicators.ema21)}"),
        ("SMA50 / SMA200", f"{_fmt_raw_number(indicators.sma50)} / {_fmt_raw_number(indicators.sma200)}"),
        ("ATR14 / RSI14", f"{_fmt_raw_number(indicators.atr14)} / {_fmt_raw_number(indicators.rsi14)}"),
        ("MACD(10,23,8)", _fmt_macd_snapshot(indicators.macd)),
        ("20D / 60D / vs QQQ 20D", f"{_fmt_pct(indicators.return_20d)} / {_fmt_pct(indicators.return_60d)} / {_fmt_pct(relative)}"),
        ("QQQ 20D基准", _fmt_pct(benchmark)),
        ("成交量比 / 20日均量", f"{_fmt_plain(item.volume_ratio)}x / {_fmt_volume(indicators.average_volume_20)}"),
    )
    items = "".join(
        f'<div class="swing-value"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in rows
    )
    return f"""<details class="swing-zone-details" open>
        <summary>Raw Technical Data</summary>
        <div class="swing-values">{items}</div>
      </details>"""


def _fmt_volume(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.0f}"


def _fmt_raw_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _fmt_macd_snapshot(snapshot: MacdSnapshot | None) -> str:
    if snapshot is None:
        return "N/A"
    cross = f"{snapshot.cross} cross" if snapshot.cross != "none" else snapshot.position
    streak = f" {snapshot.histogram_streak}D" if snapshot.histogram_streak else ""
    return f"Hist {snapshot.histogram:+.2f} {snapshot.histogram_trend}{streak} / {cross}"


def _scorecard_flag(value: bool | None) -> str:
    if value is True:
        return "站上"
    if value is False:
        return "跌破"
    return "N/A"


def _render_swing_scorecard(scorecard: TechnicalScorecard | None) -> str:
    if scorecard is None:
        return ""
    components = "".join(f"<li>{escape(component)}</li>" for component in scorecard.components)
    if not components:
        components = "<li>评分拆解暂不可用</li>"
    flags = (
        f"EMA5 {_scorecard_flag(scorecard.above_ema5)} · "
        f"EMA10 {_scorecard_flag(scorecard.above_ema10)} · "
        f"EMA21 {_scorecard_flag(scorecard.above_ema21)} · "
        f"SMA50 {_scorecard_flag(scorecard.above_sma50)} · "
        f"SMA200 {_scorecard_flag(scorecard.above_sma200)}"
    )
    return f"""<details class="swing-zone-details">
        <summary>多周期技术评分拆解</summary>
        <ul>
          <li>总分：{scorecard.total_score}/20；{escape(scorecard.interpretation)}</li>
          <li>结构：{escape(scorecard.regime)}</li>
          <li>{escape(flags)}</li>
          <li>趋势/动量/突破：{scorecard.trend_score}/5 · {scorecard.momentum_score}/5 · {scorecard.breakout_score}/5</li>
          <li>20D相对基准：{_fmt_pct(scorecard.relative_strength_20d)}</li>
          {components}
        </ul>
      </details>"""


def _render_swing_zone_details(label: str, zone: SwingZone | None, current_price: float | None) -> str:
    if zone is None:
        return ""
    components = "".join(f"<li>{escape(component)}</li>" for component in zone.components)
    if not components:
        components = "<li>组成项暂无明细</li>"
    distance = _swing_zone_distance_text(zone, current_price)
    return f"""<details class="swing-zone-details">
        <summary>{escape(label)}强度拆解</summary>
        <ul>
          <li>区间：{zone.lower:.2f}-{zone.upper:.2f}</li>
          <li>强度：{zone.score}/100</li>
          <li>触及次数：{zone.touches}</li>
          <li>距现价 {escape(distance)}</li>
          {components}
          <li>该强度用于衡量历史结构重要性，不是上涨概率、目标价或交易胜率。</li>
        </ul>
      </details>"""


def _swing_zone_distance_text(zone: SwingZone, current_price: float | None) -> str:
    if current_price in (None, 0):
        return "N/A"
    if zone.lower <= current_price <= zone.upper:
        return "0.00%（现价位于区间内）"
    reference = zone.upper if current_price > zone.upper else zone.lower
    distance_pct = (reference / current_price - 1) * 100
    return f"{distance_pct:+.2f}%"


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
      <h2>Short Premium Environment Filter</h2>
      <div class="strategy-head">
        <div>
          <div class="kicker">Cash-secured puts / spreads / condors</div>
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
      <div class="disclaimer">This module evaluates the broad short-premium environment. Ticker-level put-call context appears below; nothing here is options trading advice.</div>
</section>"""


def _render_options_sentiment(monitor: OptionsSentimentMonitor | dict | None) -> str:
    monitor = _coerce_options_sentiment_monitor(monitor)
    if monitor is None:
        return ""
    rows = "".join(_render_options_sentiment_card(item) for item in monitor.contexts)
    warning_html = "".join(f"<li>{escape(item)}</li>" for item in monitor.warnings)
    warnings = (
        f'<details class="swing-note"><summary>数据质量与降级说明</summary><ul>{warning_html}</ul></details>'
        if warning_html
        else ""
    )
    if not rows:
        return f"""<section class="panel gamma-panel">
      <h2>Options Sentiment / Short Premium Context</h2>
      <div class="summary">{escape(monitor.summary)}</div>
      {warnings}
      <div class="disclaimer">Put-call ratio is ticker-level context for premium-selling structures; it is not a trade instruction.</div>
</section>"""
    return f"""<section class="panel gamma-panel">
      <h2>Options Sentiment / Short Premium Context</h2>
      <div class="summary">{escape(monitor.summary)}</div>
      <div class="gamma-grid">{rows}</div>
      {warnings}
      <div class="disclaimer">This panel supports cash-secured puts, bull put spreads, bear call spreads, and iron condors by ticker. It does not replace strike selection, earnings/event checks, or risk limits.</div>
</section>"""


def _coerce_options_sentiment_monitor(monitor: OptionsSentimentMonitor | dict | None) -> OptionsSentimentMonitor | None:
    if monitor is None or isinstance(monitor, OptionsSentimentMonitor):
        return monitor
    if not isinstance(monitor, dict):
        return None
    contexts = []
    for raw in monitor.get("contexts") or []:
        if not isinstance(raw, dict):
            continue
        contexts.append(
            TickerShortPremiumContext(
                symbol=str(raw.get("symbol", "")),
                origin=str(raw.get("origin", "")),
                put_call_ratio=_coerce_float(raw.get("put_call_ratio")),
                nearest_expiry=str(raw.get("nearest_expiry", "N/A")),
                nearest_expiry_put_call_ratio=_coerce_float(raw.get("nearest_expiry_put_call_ratio")),
                bias=str(raw.get("bias", "")),
                interpretation=str(raw.get("interpretation", "")),
                expiration_ratios=[],
                warnings=[str(item) for item in (raw.get("warnings") or [])],
            )
        )
    return OptionsSentimentMonitor(
        generated_at=str(monitor.get("generated_at", "")),
        summary=str(monitor.get("summary", "")),
        contexts=contexts,
        warnings=[str(item) for item in (monitor.get("warnings") or [])],
    )


def _coerce_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _render_options_sentiment_card(item: TickerShortPremiumContext) -> str:
    warnings = "".join(f'<div class="gamma-warning">{escape(warning)}</div>' for warning in item.warnings)
    return f"""<article class="gamma-card">
      <div class="gamma-card-head">
        <div>
          <div class="gamma-title">{escape(item.symbol)}</div>
          <div class="symbol">{escape(item.origin)}</div>
        </div>
        <div class="gamma-regime">{escape(item.bias)}</div>
      </div>
      <div class="gamma-values">
        <div class="gamma-value"><span>Full-chain PCR</span><strong>{escape(_fmt_plain(item.put_call_ratio))}</strong></div>
        <div class="gamma-value"><span>Nearest expiry</span><strong>{escape(item.nearest_expiry)}</strong></div>
        <div class="gamma-value"><span>Nearest PCR</span><strong>{escape(_fmt_plain(item.nearest_expiry_put_call_ratio))}</strong></div>
      </div>
      <div class="gamma-note">{escape(item.interpretation)}</div>
      {warnings}
    </article>"""


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


def _render_policy_risk_monitor(monitor: PolicyRiskMonitor | None) -> str:
    if monitor is None:
        return ""
    if monitor.status == "no_data" or not monitor.factors:
        return f"""<section class="panel news-panel">
  <div class="news-head">
    <div>
      <h2>政策与地缘事件风险雷达</h2>
      <div class="summary">{escape(monitor.summary)}</div>
    </div>
    <span class="tag">{escape(monitor.label)}</span>
  </div>
  <div class="muted">当前没有足够新闻证据形成可解释的政策风险聚合判断。</div>
</section>"""
    factors = "\n".join(_render_policy_risk_factor(factor) for factor in monitor.factors[:5])
    warnings = "".join(f"<li>{escape(item)}</li>" for item in monitor.warnings)
    return f"""<section class="panel news-panel">
  <div class="news-head">
    <div>
      <h2>政策与地缘事件风险雷达</h2>
      <div class="summary">{escape(monitor.summary)}</div>
    </div>
    <span class="tag">{monitor.overall_score}/100 · {escape(monitor.label)}</span>
  </div>
  <div class="capital-grid">{factors}</div>
  {f'<ul class="small-note">{warnings}</ul>' if warnings else ''}
  <div class="disclaimer">本模块基于新闻标题、来源、主题和影响方向进行规则化聚合，用于把定性新闻转成可复核的政策风险线索；不代表对政策路径、领导人表态或资产价格的确定性预测。</div>
</section>"""


def _render_policy_risk_factor(factor: PolicyRiskFactor) -> str:
    assets = "、".join(factor.affected_assets) if factor.affected_assets else "未映射"
    tickers = "、".join(factor.affected_tickers[:8]) if factor.affected_tickers else "未映射"
    evidence = "".join(
        f'<li><a href="{escape(item.url)}" target="_blank" rel="noopener noreferrer">{escape(item.title)}</a> '
        f'<span class="muted">({escape(item.source)} · {escape(item.published_at)} · {escape(item.direction)})</span></li>'
        for item in factor.evidence[:3]
    )
    return f"""<article class="capital-item">
  <div class="capital-line"><strong>{escape(factor.label)}</strong><span>{factor.score}/100</span></div>
  <div class="news-meta">{escape(factor.direction)} · 置信度 {escape(factor.confidence)} · 证据 {factor.event_count} 条</div>
  <p>{escape(factor.summary)}</p>
  <div class="news-meta">影响资产：{escape(assets)}</div>
  <div class="news-meta">相关Ticker：{escape(tickers)}</div>
  <details class="news-meta"><summary>查看证据新闻</summary><ul>{evidence or '<li>暂无可展开证据。</li>'}</ul></details>
</article>"""


def _render_event_risk_ledger(ledger: EventRiskLedger | None) -> str:
    if ledger is None:
        return ""
    if ledger.status == "no_data" or not ledger.entries:
        return f"""<section class="panel news-panel">
  <div class="news-head">
    <div>
      <h2>事件风险追踪</h2>
      <div class="summary">{escape(ledger.summary)}</div>
    </div>
    <span class="tag">{escape(ledger.status)}</span>
  </div>
  <div class="muted">当前没有足够事件簇形成组合暴露映射。</div>
</section>"""
    entries = "\n".join(_render_event_risk_entry(entry) for entry in ledger.entries[:6])
    warnings = "".join(f"<li>{escape(item)}</li>" for item in ledger.warnings[:4])
    return f"""<section class="panel news-panel">
  <div class="news-head">
    <div>
      <h2>事件风险追踪</h2>
      <div class="summary">{escape(ledger.summary)}</div>
    </div>
    <span class="tag">{escape(ledger.status)} · {len(ledger.entries)}个事件簇</span>
  </div>
  <div class="capital-grid">{entries}</div>
  {f'<ul class="small-note">{warnings}</ul>' if warnings else ''}
  <div class="disclaimer">事件风险追踪基于新闻事件簇、规则化政策风险因子和当前持仓映射生成。它用于把定性事件转化为可复核的风险线索，不代表确定性预测；价格确认与因果验证仍需人工复核。</div>
</section>"""


def _render_event_risk_entry(entry: EventRiskLedgerEntry) -> str:
    portfolio = (
        f"{'、'.join(entry.portfolio_symbols[:8])} · 约{entry.portfolio_weight_pct:.1f}%"
        if entry.portfolio_symbols
        else "暂无直接持仓映射"
    )
    links = "".join(
        f'<li><a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(url)}</a></li>'
        for url in entry.source_urls[:3]
    )
    latest = f" · 最新证据 {escape(entry.latest_published_at)}" if entry.latest_published_at else ""
    return f"""<article class="capital-item">
  <div class="capital-line"><strong>{escape(entry.label)}</strong><span>{escape(entry.lifecycle)}</span></div>
  <div class="news-meta">事件ID {escape(entry.event_id)} · 证据 {entry.evidence_count}条{latest}</div>
  <p>{escape(entry.synthesis)}</p>
  <div class="news-meta">组合暴露：{escape(portfolio)}</div>
  <div class="news-meta">市场确认：{escape(entry.market_confirmation)} · {escape(entry.validation_note)}</div>
  <details class="news-meta"><summary>查看来源链接</summary><ul>{links or '<li>暂无可展开来源链接。</li>'}</ul></details>
</article>"""


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
    option_history: list[dict] | None = None,
) -> str:
    if monitor is None:
        return ""
    groups = "\n".join(_render_etf_group(group, index) for index, group in enumerate(_group_etf_assets(monitor.assets)))
    warnings = ""
    if monitor.warnings:
        warnings = "<div class=\"small-note\">数据提示：" + escape(_summarize_etf_warnings(monitor.warnings)) + "</div>"
    changes = _render_etf_notes("今日ETF变动摘要", monitor.change_summary)
    core_plan = _render_core_etf_plan(monitor.core_etf_plan)
    portfolio = _render_portfolio_panel(monitor, news_monitor, portfolio_event_monitor, option_history)
    sensitivities = _render_sensitivity_panel(monitor)
    return f"""<section class="panel">
      <h2>UK ETF估值、趋势与拥挤度监控器</h2>
      <div class="etf-summary">{escape(monitor.summary)}</div>
      {changes}
      {core_plan}
      {portfolio}
      {sensitivities}
      <div class="etf-groups">{groups}</div>
      <div class="small-note">PE衡量底层持仓组合的盈利估值，Forward PE基于未来盈利预期；组合P/B衡量底层持仓市值相对账面净资产的加权估值，并非ETF自身资产负债表指标。组合估值按发行商披露节奏更新，不等同于实时行情。PE位置优先显示本地历史分位；样本不足时显示“当前PE/近一年缓存最高PE”的近似比例。σ200使用63/126/252日窗口去极值后的稳健趋势波动率。持仓重叠度基于可获得的前十大持仓近似计算，并非完整穿透。估值源若标记为proxy，表示使用高度相关的同类ETF作近似参考。黄金、现金、短债和固定收益类产品不适用PE/PB，应观察实际利率、久期、收益率和流动性。</div>
      {warnings}
    </section>"""


def _render_core_etf_plan(plan: dict | None) -> str:
    if not plan or not plan.get("enabled"):
        return ""
    rows = []
    for item in plan.get("decisions") or []:
        target_value = item.get("target_weight_pct")
        target = f"{target_value:.0f}%" if isinstance(target_value, (int, float)) else "N/A"
        drawdown = _fmt_pct(item.get("drawdown_1y_peak_pct"))
        sma200 = _fmt_pct(item.get("distance_sma200_pct"))
        planned = _fmt_gbp(item.get("planned_addition_gbp"))
        executed = _fmt_gbp(item.get("estimated_executed_gbp"))
        suggested = _fmt_gbp(item.get("suggested_order_gbp"))
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(item.get('symbol') or ''))}</strong></td>"
            f"<td>{escape(target)}</td>"
            f"<td>{escape(drawdown)} / {escape(sma200)}</td>"
            f"<td>{escape(str(item.get('stage') or ''))}<div class=\"small-note\">{escape(str(item.get('trigger') or ''))}</div></td>"
            f"<td>{escape(planned)} / {escape(executed)}</td>"
            f"<td><strong>{escape(suggested)}</strong></td>"
            f"<td><strong>{escape(str(item.get('status') or ''))}</strong><div class=\"small-note\">{escape(str(item.get('action') or ''))}</div></td>"
            "</tr>"
        )
    warnings = "".join(f"<li>{escape(str(item))}</li>" for item in (plan.get("warnings") or []))
    warning_block = f'<div class="portfolio-notes"><ul>{warnings}</ul></div>' if warnings else ""
    body = "".join(rows) or '<tr><td colspan="7">计划已启用，但暂无可评估标的。</td></tr>'
    return f"""<div class="portfolio-panel">
      <div class="portfolio-title">核心ETF加仓判单</div>
      <div class="small-note">{escape(str(plan.get("summary") or ""))}</div>
      <div class="portfolio-table-scroll">
        <table class="portfolio-table">
          <thead><tr><th>ETF</th><th>目标</th><th>距1Y高点 / SMA200</th><th>触发档</th><th>计划 / 已执行估算</th><th>今日上限</th><th>判单</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
      <div class="small-note">“可下单”表示预设条件满足，不代表自动交易；下单前核对IBKR实时价格、当日事件和statement是否已反映最近成交。</div>
      {warning_block}
    </div>"""


def _render_portfolio_panel(
    monitor: ETFMonitor,
    news_monitor: NewsMonitor | None = None,
    portfolio_event_monitor: PortfolioEventMonitor | None = None,
    option_history: list[dict] | None = None,
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
    option_panel = _render_option_risk_panel(monitor.portfolio_positions, option_history)
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
      {option_panel}
      {performance_panel}
      {exposure_panel}
      {mag7_panel}
      {event_panel}
      <div class="portfolio-notes"><ul>{note_html}</ul></div>
    </div>"""


def _render_option_risk_panel(
    positions: list[PortfolioPosition],
    option_history: list[dict] | None = None,
) -> str:
    legs = _portfolio_option_legs(positions)
    lifecycle_events = _portfolio_option_lifecycle_events(positions)
    if not legs and not lifecycle_events:
        return ""
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for leg in legs:
        key = (str(leg.get("underlying") or ""), str(leg.get("expiry") or ""))
        groups.setdefault(key, []).append(leg)
    strategy_rows = (
        "\n".join(
            _render_option_strategy_row(underlying, expiry, group_legs)
            for (underlying, expiry), group_legs in sorted(groups.items())
        )
        if groups
        else '<tr><td colspan="6">暂无开放/成交期权腿；仅发现生命周期诊断记录。</td></tr>'
    )
    leg_rows = (
        "\n".join(_render_option_leg_row(leg) for leg in legs)
        if legs
        else '<tr><td colspan="10">暂无期权腿明细。</td></tr>'
    )
    lifecycle_status = _render_option_lifecycle_status(lifecycle_events)
    open_premium_summary = _render_open_option_premium_summary(legs)
    closeout_summary = _render_open_option_closeout_summary(groups, option_history)
    return f"""<div class="portfolio-notes">
      {lifecycle_status}
      {open_premium_summary}
      {closeout_summary}
      <strong>IBKR期权风险（成本与结构识别）</strong>
      <div class="small-note">期权已从普通股票/ETF持仓中剥离。当前使用IBKR statement成交现金流识别成本、方向、到期与行权价；如Flex/OpenPosition提供mark或market value，则显示当前MTM。delta、gamma、theta、vega和POP仍需要IBKR期权行情或模型输入，未取得时不做伪精确估算。</div>
      <div class="portfolio-table-scroll">
        <table class="portfolio-table">
          <thead><tr><th>策略/标的</th><th>到期</th><th>结构</th><th>剩余仓位成本/权利金</th><th>盈亏边界</th><th>数据状态</th></tr></thead>
          <tbody>{strategy_rows}</tbody>
        </table>
      </div>
      <details>
        <summary>查看期权腿明细</summary>
        <div class="portfolio-table-scroll">
          <table class="portfolio-table">
            <thead><tr><th>合约</th><th>方向</th><th>数量</th><th>成交价</th><th>Mark</th><th>IV/Greeks</th><th>当前MTM</th><th>Net cash</th><th>手续费</th><th>来源</th></tr></thead>
            <tbody>{leg_rows}</tbody>
          </table>
        </div>
      </details>
    </div>"""


def _render_open_option_premium_summary(legs: list[dict[str, object]]) -> str:
    if not legs:
        return ""
    net_premium_gbp = sum(_option_cash_after_fee_gbp(leg) for leg in legs)
    return (
        '<div class="portfolio-exposure-grid" style="margin-top:8px;">'
        '<div class="portfolio-exposure">'
        '<span class="muted">未平仓期权剩余净权利金/成本</span>'
        f'<strong class="{_pnl_class(net_premium_gbp)}">{escape(_fmt_signed_gbp(net_premium_gbp))}</strong>'
        '<span class="portfolio-scope">优先按当前 OpenPosition 成本基础汇总；缺失时回退至扣费后成交现金流。'
        'spread 已扣除 long legs 成本。不等同于已实现收益，若到期归零且未被执行/指派才可全部保留。</span>'
        '</div></div>'
    )


def _render_open_option_closeout_summary(
    groups: dict[tuple[str, str], list[dict[str, object]]],
    option_history: list[dict] | None = None,
) -> str:
    if not groups:
        return ""
    snapshot = option_closeout_snapshot_from_groups(groups)
    total = _option_float(snapshot.get("total_gbp"))
    if total is None:
        return ""
    source_label = str(snapshot.get("source") or "缺失")
    available_groups = int(snapshot.get("available_groups") or 0)
    total_groups = int(snapshot.get("total_groups") or 0)
    complete = bool(snapshot.get("complete"))
    title = "当前全部期权平仓损益估算" if complete else "当前可估期权平仓损益"
    coverage = f"{available_groups}/{total_groups} 组策略"
    history_html = _render_option_closeout_changes(snapshot, option_history or [])
    return (
        '<div class="portfolio-exposure-grid" style="margin-top:8px;">'
        '<div class="portfolio-exposure">'
        f'<span class="muted">{title}</span>'
        f'<strong class="{_pnl_class(total)}">{escape(_fmt_signed_gbp(total))}</strong>'
        f'<span class="portfolio-scope">来源：{escape(source_label)}；覆盖 {coverage}。'
        '按当前 mark/market value 粗估，尚未扣除新产生的平仓手续费、买卖价差与滑点。</span>'
        f'{history_html}'
        '</div></div>'
    )


def _render_option_closeout_changes(current: dict[str, object], history: list[dict]) -> str:
    current_total = _option_float(current.get("total_gbp"))
    if current_total is None:
        return ""
    comparable = []
    for item in sorted(history, key=lambda row: str(row.get("report_date") or "")):
        snapshot = item.get("option_closeout")
        if not isinstance(snapshot, dict):
            continue
        historical_total = _option_float(snapshot.get("total_gbp"))
        if historical_total is not None:
            comparable.append((historical_total, snapshot))
    if not comparable:
        return '<span class="portfolio-scope">1–3D变化：历史待积累。</span>'
    current_signature = current.get("position_signature")
    changes = []
    position_changed = False
    for days, (historical_total, snapshot) in enumerate(reversed(comparable[-3:]), start=1):
        delta = current_total - historical_total
        historical_signature = snapshot.get("position_signature")
        changed = bool(current_signature and historical_signature and current_signature != historical_signature)
        position_changed = position_changed or changed
        marker = "*" if changed else ""
        changes.append(f"{days}D {escape(_fmt_signed_gbp(delta))}{marker}")
    change_text = " · ".join(changes)
    note = "；* 含仓位组成变化" if position_changed else ""
    return f'<span class="portfolio-scope">总MTM未实现变化：{change_text}{note}（D=报告日）。</span>'


def _portfolio_option_legs(positions: list[PortfolioPosition]) -> list[dict[str, object]]:
    for position in positions:
        if not position.option_legs_json:
            continue
        try:
            raw = json.loads(position.option_legs_json)
        except json.JSONDecodeError:
            return []
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    return []


def _portfolio_option_lifecycle_events(positions: list[PortfolioPosition]) -> list[dict[str, object]]:
    for position in positions:
        raw_json = getattr(position, "option_lifecycle_json", "")
        if not raw_json:
            continue
        try:
            raw = json.loads(raw_json)
        except json.JSONDecodeError:
            return []
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    return []


def _render_option_lifecycle_status(events: list[dict[str, object]]) -> str:
    if not events:
        return (
            '<div class="small-note">'
            "到期/行权/指派记录：Flex Query 已配置为可接收；当前样本未出现相关事件，"
            "realized P/L 入账规则待真实样本验证。"
            "</div>"
        )
    rows = "\n".join(_render_option_lifecycle_row(event) for event in events[:20])
    return f"""<div class="small-note">
        到期/行权/指派记录：已捕获 {len(events)} 条；当前仅作诊断展示，尚未自动计入收益。
      </div>
      <details>
        <summary>查看到期/行权/指派诊断记录</summary>
        <div class="portfolio-table-scroll">
          <table class="portfolio-table">
            <thead><tr><th>事件</th><th>标的</th><th>到期</th><th>结构</th><th>数量</th><th>金额GBP</th><th>日期</th><th>来源</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
      </details>"""


def _render_option_lifecycle_row(event: dict[str, object]) -> str:
    event_label = {
        "assignment": "指派",
        "exercise": "行权",
        "expiration": "到期",
    }.get(str(event.get("event_type") or ""), "生命周期事件")
    right = str(event.get("right") or "")
    strike = event.get("strike")
    structure = f"{right}{strike}" if right or strike not in (None, "") else "N/A"
    amount = event.get("amount_gbp")
    amount_text = _fmt_signed_gbp(amount) if isinstance(amount, (int, float)) else "N/A"
    quantity = event.get("quantity")
    quantity_text = f"{quantity:.2f}" if isinstance(quantity, (int, float)) else "N/A"
    return f"""<tr>
      <td>{escape(event_label)}</td>
      <td><strong>{escape(str(event.get("underlying") or event.get("symbol") or "UNKNOWN"))}</strong><br><span class="portfolio-scope">{escape(str(event.get("symbol") or ""))}</span></td>
      <td>{escape(str(event.get("expiry") or ""))}</td>
      <td>{escape(structure)}</td>
      <td>{escape(quantity_text)}</td>
      <td>{escape(amount_text)}</td>
      <td>{escape(str(event.get("date") or ""))}</td>
      <td>{escape(str(event.get("source_file") or ""))}</td>
    </tr>"""


def _render_option_strategy_row(underlying: str, expiry: str, legs: list[dict[str, object]]) -> str:
    strategy = _classify_option_strategy(legs)
    currency = _option_currency(legs)
    net_cash = sum(_option_cash_after_fee_native(leg) for leg in legs)
    net_cash_gbp = sum(_option_cash_after_fee_gbp(leg) for leg in legs)
    market_value_native = _option_group_market_value_native(legs)
    market_value_gbp = _option_group_market_value_gbp(legs)
    mtm_pnl_gbp, mtm_pnl_source = _option_group_unrealized_result(legs)
    boundary = _option_boundary_text(strategy, legs, net_cash, net_cash_gbp)
    mtm_line = (
        f"当前MTM {escape(_fmt_signed_gbp(market_value_gbp))}"
        if market_value_gbp is not None
        else "当前MTM缺失"
    )
    if market_value_native is not None:
        mtm_line += f"；原币 {escape(_fmt_option_cash(market_value_native, currency))}"
    pnl_line = (
        f"MTM未实现（{mtm_pnl_source}） {escape(_fmt_signed_gbp(mtm_pnl_gbp))}"
        if mtm_pnl_gbp is not None
        else "MTM未实现待确认"
    )
    adjustment_line = ""
    adjusted_legs = [leg for leg in legs if leg.get("mtm_quantity_adjusted")]
    if adjusted_legs:
        changes = "；".join(
            f"{_fmt_option_number(leg.get('strike'))}{str(leg.get('right') or '')} "
            f"{_fmt_option_number(abs(_option_float(leg.get('mtm_snapshot_contracts')) or 0))}→"
            f"{_fmt_option_number(abs(_option_float(leg.get('signed_contracts')) or 0))}张"
            for leg in adjusted_legs
        )
        adjustment_method = (
            "按剩余FIFO批次重建"
            if all(str(leg.get("mtm_quantity_adjustment_method") or "") == "FIFO lots" for leg in adjusted_legs)
            else "按剩余数量比例调整"
        )
        adjustment_line = f'<br><span class="portfolio-scope">Activity快照后部分平仓：{escape(changes)}；MTM/成本{adjustment_method}</span>'
    structure = "；".join(
        _option_leg_label(leg)
        for leg in sorted(legs, key=lambda item: (_option_float(item.get("strike")) or 0))
    )
    return f"""<tr>
      <td><strong>{escape(underlying or "UNKNOWN")}</strong><br><span class="portfolio-scope">{escape(strategy)}</span></td>
      <td>{escape(expiry or "到期日待确认")}</td>
      <td>{escape(structure)}</td>
      <td>{escape(_fmt_signed_gbp(net_cash_gbp))}<br><span class="portfolio-scope">剩余仓位；原币 {escape(_fmt_option_cash(net_cash, currency))}</span><br><span class="portfolio-scope">{mtm_line}</span><br><span class="portfolio-scope">{pnl_line}</span>{adjustment_line}</td>
      <td>{escape(boundary)}</td>
      <td>成交已识别；MTM取自Flex/OpenPosition；Greeks/POP待IBKR行情或模型估算</td>
    </tr>"""


def _classify_option_strategy(legs: list[dict[str, object]]) -> str:
    puts = [leg for leg in legs if str(leg.get("right") or "").upper() == "P"]
    calls = [leg for leg in legs if str(leg.get("right") or "").upper() == "C"]
    if len(puts) >= 2 and not calls:
        short_puts = [leg for leg in puts if (_option_float(leg.get("signed_contracts")) or 0) < 0]
        long_puts = [leg for leg in puts if (_option_float(leg.get("signed_contracts")) or 0) > 0]
        if short_puts and long_puts:
            short_quantity = sum(abs(_option_float(leg.get("signed_contracts")) or 0) for leg in short_puts)
            long_quantity = sum(_option_float(leg.get("signed_contracts")) or 0 for leg in long_puts)
            short_strikes = [_option_float(leg.get("strike")) for leg in short_puts]
            long_strikes = [_option_float(leg.get("strike")) for leg in long_puts]
            if (
                abs(short_quantity - long_quantity) < 1e-6
                and all(strike is not None for strike in short_strikes + long_strikes)
                and min(short_strikes) > max(long_strikes)
            ):
                return "Bull put spread / 牛市看跌价差"
    if len(calls) == 1 and (_option_float(calls[0].get("signed_contracts")) or 0) > 0:
        return "Long call / 买入看涨"
    return "Option legs / 期权组合"


def _option_boundary_text(
    strategy: str,
    legs: list[dict[str, object]],
    net_cash: float,
    net_cash_gbp: float | None = None,
) -> str:
    currency = _option_currency(legs)
    multiplier = _option_float(legs[0].get("multiplier")) or 100.0
    if "Bull put spread" in strategy:
        put_legs = [leg for leg in legs if str(leg.get("right") or "").upper() == "P"]
        short_puts = [leg for leg in put_legs if (_option_float(leg.get("signed_contracts")) or 0) < 0]
        long_puts = [leg for leg in put_legs if (_option_float(leg.get("signed_contracts")) or 0) > 0]
        spread_count = sum(abs(_option_float(leg.get("signed_contracts")) or 0) for leg in short_puts)
        if len(put_legs) > 2 and spread_count:
            short_notional = sum(
                (_option_float(leg.get("strike")) or 0)
                * abs(_option_float(leg.get("signed_contracts")) or 0)
                for leg in short_puts
            )
            long_notional = sum(
                (_option_float(leg.get("strike")) or 0)
                * (_option_float(leg.get("signed_contracts")) or 0)
                for leg in long_puts
            )
            gross_width_value = max((short_notional - long_notional) * multiplier, 0)
            max_loss = max(gross_width_value - net_cash, 0)
            count_text = _fmt_option_number(spread_count)
            if net_cash_gbp is not None and abs(net_cash) > 1e-9:
                max_loss_gbp = max_loss * abs(net_cash_gbp / net_cash)
                return (
                    f"{count_text}组价差；"
                    f"最大收益约 {_fmt_gbp(net_cash_gbp)}（{_fmt_option_cash_abs(net_cash, currency)}）；"
                    f"最大亏损约 {_fmt_gbp(max_loss_gbp)}（{_fmt_option_cash_abs(max_loss, currency)}）"
                )
            return f"{count_text}组价差；最大收益约 {net_cash:.2f}；最大亏损约 {max_loss:.2f}（原币）"
        short_put = next((leg for leg in legs if str(leg.get("right") or "") == "P" and (_option_float(leg.get("signed_contracts")) or 0) < 0), None)
        long_put = next((leg for leg in legs if str(leg.get("right") or "") == "P" and (_option_float(leg.get("signed_contracts")) or 0) > 0), None)
        if short_put and long_put:
            short_strike = _option_float(short_put.get("strike"))
            long_strike = _option_float(long_put.get("strike"))
            contracts = abs(_option_float(short_put.get("signed_contracts")) or 1.0)
            if short_strike is not None and long_strike is not None and contracts:
                net_credit = net_cash / (contracts * multiplier)
                max_profit = net_cash
                max_loss = max((short_strike - long_strike - net_credit) * multiplier * contracts, 0)
                breakeven = short_strike - net_credit
                if net_cash_gbp is not None and abs(net_cash) > 1e-9:
                    max_profit_gbp = net_cash_gbp
                    max_loss_gbp = max_loss * abs(net_cash_gbp / net_cash)
                    return (
                        f"盈亏平衡约 {breakeven:.2f}；"
                        f"最大收益约 {_fmt_gbp(max_profit_gbp)}（{_fmt_option_cash_abs(max_profit, currency)}）；"
                        f"最大亏损约 {_fmt_gbp(max_loss_gbp)}（{_fmt_option_cash_abs(max_loss, currency)}）"
                    )
                return f"盈亏平衡约 {breakeven:.2f}；最大收益约 {max_profit:.2f}；最大亏损约 {max_loss:.2f}（原币）"
    if "Long call" in strategy:
        leg = legs[0]
        strike = _option_float(leg.get("strike"))
        contracts = abs(_option_float(leg.get("signed_contracts")) or 1.0)
        if strike is not None and contracts:
            debit = -net_cash / (contracts * multiplier)
            breakeven = strike + debit
            if net_cash_gbp is not None and abs(net_cash) > 1e-9:
                max_loss_gbp = abs(net_cash_gbp)
                return (
                    f"盈亏平衡约 {breakeven:.2f}；"
                    f"最大亏损约 {_fmt_gbp(max_loss_gbp)}（{_fmt_option_cash_abs(-net_cash, currency)}）；"
                    "上行收益取决于到期结算"
                )
            return f"盈亏平衡约 {breakeven:.2f}；最大亏损约 {-net_cash:.2f}（原币）；上行收益取决于到期结算"
    return "需按腿逐项复核；当前不提供POP/Greeks伪精确值"


def _render_option_leg_row(leg: dict[str, object]) -> str:
    currency = str(leg.get("currency") or "")
    market_value_native = _option_float(leg.get("market_value_native"))
    market_value_gbp = _option_float(leg.get("market_value_gbp"))
    mtm_cell = (
        f"{escape(_fmt_signed_gbp(market_value_gbp))}<br><span class=\"portfolio-scope\">{escape(_fmt_option_cash(market_value_native or 0.0, currency))}</span>"
        if market_value_gbp is not None or market_value_native is not None
        else "MTM缺失"
    )
    return f"""<tr>
      <td><strong>{escape(str(leg.get("symbol") or ""))}</strong><br><span class="portfolio-scope">{escape(str(leg.get("expiry") or ""))} {escape(str(leg.get("right") or ""))}{escape(_fmt_option_number(leg.get("strike")))}</span></td>
      <td>{escape(str(leg.get("side") or ""))}</td>
      <td>{escape(_fmt_option_number(leg.get("contracts")))}</td>
      <td>{escape(_fmt_option_number(leg.get("trade_price")))}</td>
      <td>{escape(_fmt_option_number(leg.get("mark_price")))}</td>
      <td>{_option_greeks_text(leg)}</td>
      <td>{mtm_cell}</td>
      <td>{escape(_fmt_option_cash(_option_cash_after_fee_native(leg), currency))}<br><span class="portfolio-scope">原始netCash {escape(_fmt_option_cash(_option_float(leg.get("net_cash_native")) or 0, currency))}；GBP {escape(_fmt_signed_gbp(_option_cash_after_fee_gbp(leg)))}</span></td>
      <td>{escape(_fmt_option_cash(_option_float(leg.get("commission_native")) or 0, currency))}</td>
      <td>{escape(str(leg.get("source") or "IBKR statement"))}</td>
    </tr>"""


def _option_greeks_text(leg: dict[str, object]) -> str:
    iv = _option_float(leg.get("implied_volatility"))
    delta = _option_float(leg.get("unit_delta"))
    gamma = _option_float(leg.get("unit_gamma"))
    theta = _option_float(leg.get("unit_theta"))
    vega = _option_float(leg.get("unit_vega"))
    fields: list[str] = []
    if iv is not None:
        fields.append(f"IV {iv * 100:.1f}%")
    if delta is not None:
        fields.append(f"Δ {delta:.2f}")
    if gamma is not None:
        fields.append(f"Γ {gamma:.4f}")
    if theta is not None:
        fields.append(f"Θ {theta:.3f}/day")
    if vega is not None:
        fields.append(f"Vega {vega:.3f}")
    if not fields:
        return "N/A"
    source = str(leg.get("market_data_source") or "")
    source_note = f'<br><span class="portfolio-scope">{escape(source)}</span>' if source else ""
    return escape(" · ".join(fields)) + source_note


def _option_leg_label(leg: dict[str, object]) -> str:
    signed = _option_float(leg.get("signed_contracts")) or 0
    side = "short" if signed < 0 else "long"
    right = "P" if str(leg.get("right") or "").upper() == "P" else "C"
    strike = _fmt_option_number(leg.get("strike"))
    contracts = _fmt_option_number(abs(signed) or leg.get("contracts"))
    return f"{side} {contracts}x {strike}{right}"


def _option_currency(legs: list[dict[str, object]]) -> str:
    for leg in legs:
        currency = str(leg.get("currency") or "").strip().upper()
        if currency:
            return currency
    return ""


def _option_cash_after_fee_native(leg: dict[str, object]) -> float:
    open_premium = _option_float(leg.get("open_net_premium_native"))
    if open_premium is not None:
        return open_premium
    value = _option_float(leg.get("net_cash_after_fee_native"))
    if value is not None:
        return value
    net_cash = _option_float(leg.get("net_cash_native"))
    commission = _option_float(leg.get("commission_native"))
    if net_cash is not None and commission is not None:
        return net_cash + commission
    return net_cash or 0.0


def _option_cash_after_fee_gbp(leg: dict[str, object]) -> float:
    open_premium = _option_float(leg.get("open_net_premium_gbp"))
    if open_premium is not None:
        return open_premium
    value = _option_float(leg.get("net_cash_after_fee_gbp"))
    if value is not None:
        return value
    net_cash = _option_float(leg.get("net_cash_gbp"))
    commission = _option_float(leg.get("commission_gbp"))
    if net_cash is not None and commission is not None:
        return net_cash + commission
    return net_cash or 0.0


def _option_group_market_value_native(legs: list[dict[str, object]]) -> float | None:
    values = [_option_float(leg.get("market_value_native")) for leg in legs]
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _option_group_market_value_gbp(legs: list[dict[str, object]]) -> float | None:
    values = [_option_float(leg.get("market_value_gbp")) for leg in legs]
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _option_group_unrealized_pnl_gbp(legs: list[dict[str, object]]) -> float | None:
    values = [_option_float(leg.get("unrealized_pnl_gbp")) for leg in legs]
    if not values or any(value is None for value in values):
        return None
    return sum(value or 0.0 for value in values)


def _option_group_unrealized_result(legs: list[dict[str, object]]) -> tuple[float | None, str]:
    ibkr_unrealized_pnl_gbp = _option_group_unrealized_pnl_gbp(legs)
    if ibkr_unrealized_pnl_gbp is not None:
        return ibkr_unrealized_pnl_gbp, "IBKR"
    market_value_gbp = _option_group_market_value_gbp(legs)
    if market_value_gbp is None:
        return None, "缺失"
    net_cash_gbp = sum(_option_cash_after_fee_gbp(leg) for leg in legs)
    return net_cash_gbp + market_value_gbp, "估算"


def _option_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_option_number(value: object) -> str:
    number = _option_float(value)
    if number is None:
        return "N/A"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _fmt_option_cash(value: float, currency: str) -> str:
    prefix = f"{currency} " if currency else ""
    sign = "+" if value > 0 else ""
    return f"{sign}{prefix}{value:,.2f}"


def _fmt_option_cash_abs(value: float, currency: str) -> str:
    prefix = f"{currency} " if currency else ""
    return f"{prefix}{abs(value):,.2f}"


def _render_portfolio_performance(monitor: ETFMonitor) -> str:
    performance = monitor.portfolio_performance
    if performance is None:
        return ""
    stock_realized = sum(trade.realized_pnl_gbp for trade in performance.closed_trades)
    option_realized = sum(trade.realized_pnl_gbp for trade in performance.closed_option_trades)
    realized_detail = (
        f"股票 {_fmt_signed_gbp(stock_realized)} · 期权 {_fmt_signed_gbp(option_realized)}"
    )
    realized_residual = performance.realized_pnl_gbp - stock_realized - option_realized
    if abs(realized_residual) >= 0.01:
        realized_detail += f" · 其他/未归因 {_fmt_signed_gbp(realized_residual)}"
    cards = (
        ("扣费后可识别总收益", performance.total_return_gbp, ""),
        ("未实现盈亏", performance.unrealized_pnl_gbp, ""),
        ("已实现交易盈亏（净额）", performance.realized_pnl_gbp, realized_detail),
        ("股息收入", performance.dividend_income_gbp, ""),
        ("隐含交易成本", -performance.implied_trading_cost_gbp, ""),
    )
    rendered_cards = []
    for label, value, detail in cards:
        detail_html = f'<span class="portfolio-scope">{escape(detail)}</span>' if detail else ""
        rendered_cards.append(
            f'<div class="portfolio-exposure"><span class="muted">{escape(label)}</span>'
            f'<strong class="{_pnl_class(value)}">{escape(_fmt_signed_gbp(value))}</strong>'
            f'{detail_html}</div>'
        )
    rendered = "".join(rendered_cards)
    return (
        '<div class="portfolio-notes"><strong>收益归因（statement 导出窗口内，可识别口径）</strong></div>'
        f'<div class="portfolio-exposure-grid">{rendered}</div>'
        '<div class="small-note">Revolut 隐含交易成本按 Total Amount 与 股数×成交价 的差额估算，可能包含佣金、税费、FX/执行价差与四舍五入；总收益已使用实际现金流口径，避免把费用当作利润。</div>'
        f'{_render_unmatched_sell_breakdown(performance)}'
        f'{_render_closed_trade_breakdown(performance)}'
        f'{_render_closed_option_trade_breakdown(performance)}'
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
    groups = _closed_trade_groups(performance.closed_trades)
    rows = "".join(_render_closed_trade_group(symbol, trades) for symbol, trades in groups)
    trades = performance.closed_trades
    quantity = sum(trade.quantity for trade in trades)
    cost_basis = sum(trade.cost_basis_gbp for trade in trades)
    gross_proceeds = sum(trade.gross_proceeds_gbp for trade in trades)
    net_proceeds = sum(trade.net_proceeds_gbp for trade in trades)
    implied_cost = sum(trade.implied_trading_cost_gbp for trade in trades)
    realized_pnl = sum(trade.realized_pnl_gbp for trade in trades)
    average_cost_pnl = _sum_optional(
        getattr(trade, "average_cost_realized_pnl_gbp", None) for trade in trades
    )
    return f"""<details class="portfolio-notes">
      <summary>已平仓交易归因（FIFO近似）</summary>
      <div class="small-note">用于解释 statement 窗口内已实现盈亏来源；先按 ticker 聚合，展开后显示所有 FIFO 买入批次，0天表示同日买卖。</div>
      <div class="portfolio-table-scroll">
        <table class="portfolio-table">
          <thead><tr><th>资产</th><th>清算窗口</th><th>数量</th><th>成本基础</th><th>净卖出额</th><th>已实现盈亏</th></tr></thead>
          <tbody>{rows}</tbody>
          <tfoot><tr>
            <td colspan="2">已平仓股票合计<br><span class="portfolio-scope">{len(groups)} 个标的 · {len(trades)} 个已平仓批次</span></td>
            <td>{escape(_fmt_quantity(quantity))}</td>
            <td>{escape(_fmt_gbp(cost_basis))}</td>
            <td>{escape(_fmt_gbp(net_proceeds))}<br><span class="portfolio-scope">毛额 {escape(_fmt_gbp(gross_proceeds))} · 成本 {escape(_fmt_gbp(implied_cost))}</span></td>
            <td class="{_pnl_class(realized_pnl)}">{escape(_fmt_signed_gbp(realized_pnl))}<br><span class="portfolio-scope">均价口径 {escape(_fmt_signed_gbp(average_cost_pnl))}</span></td>
          </tr></tfoot>
        </table>
      </div>
    </details>"""


def _render_closed_option_trade_breakdown(performance) -> str:
    if not getattr(performance, "closed_option_trades", None):
        return ""
    rows = "".join(
        f"""<tr>
          <td><strong>{escape(item.underlying)}</strong><br><span class="portfolio-scope">{escape(_closed_option_contract_label(item))}</span></td>
          <td>{escape(item.expiry or 'N/A')}</td>
          <td>{escape(item.opened_at or 'N/A')} → {escape(item.closed_at or 'N/A')}<br><span class="portfolio-scope">已平仓 {escape(_fmt_option_number(item.contracts_closed))} 张；{escape(str(item.legs))} 条成交（开仓+平仓）</span></td>
          <td>{escape(_fmt_option_cash(item.realized_pnl_native or 0.0, item.currency))}</td>
          <td class="{_pnl_class(item.realized_pnl_gbp)}">{escape(_fmt_signed_gbp(item.realized_pnl_gbp))}</td>
        </tr>"""
        for item in performance.closed_option_trades
    )
    total = sum(item.realized_pnl_gbp for item in performance.closed_option_trades)
    return f"""<details class="portfolio-notes" open>
      <summary>已平仓期权现金流归因（IBKR）</summary>
      <div class="small-note">这里展示已完全对冲或清仓的期权合约现金流，金额来自 IBKR Flex 的成交 net cash 扣费后折算 GBP；该金额已经计入上方“已实现交易盈亏”。当前为合约级归因，不替代券商账单。</div>
      <div class="portfolio-table-scroll">
        <table class="portfolio-table">
          <thead><tr><th>标的/合约</th><th>到期</th><th>清仓窗口</th><th>原币已实现</th><th>GBP已实现</th></tr></thead>
          <tbody>{rows}</tbody>
          <tfoot><tr><td colspan="4">已平仓期权合计</td><td class="{_pnl_class(total)}">{escape(_fmt_signed_gbp(total))}</td></tr></tfoot>
        </table>
      </div>
    </details>"""


def _closed_option_contract_label(item) -> str:
    strike = _fmt_option_number(getattr(item, "strike", None))
    right = getattr(item, "right", "") or ""
    if right or strike != "N/A":
        return f"{strike}{right}"
    return "Option round-trip"


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
    average_cost_pnl = _sum_optional(
        getattr(trade, "average_cost_realized_pnl_gbp", None) for trade in trades
    )
    opened_dates = [trade.opened_at for trade in trades if trade.opened_at]
    closed_dates = [trade.closed_at for trade in trades if trade.closed_at]
    window = f"{min(opened_dates) if opened_dates else 'N/A'} → {max(closed_dates) if closed_dates else 'N/A'}"
    details = _render_closed_trade_lot_details(trades)
    return f"""<tr>
      <td>{escape(symbol)}<br><span class="portfolio-scope">{len(trades)}个已平仓批次</span></td>
      <td>{escape(window)}<br><details><summary class="portfolio-scope">查看 FIFO 批次计算明细</summary>{details}</details></td>
      <td>{escape(_fmt_quantity(quantity))}</td>
      <td>{escape(_fmt_gbp(cost_basis))}</td>
      <td>{escape(_fmt_gbp(net_proceeds))}<br><span class="portfolio-scope">毛额 {escape(_fmt_gbp(gross_proceeds))} · 成本 {escape(_fmt_gbp(implied_cost))}</span></td>
      <td class="{_pnl_class(realized_pnl)}">{escape(_fmt_signed_gbp(realized_pnl))}<br><span class="portfolio-scope">均价口径 {escape(_fmt_signed_gbp(average_cost_pnl))}</span></td>
    </tr>"""


def _render_closed_trade_lot_details(trades: list) -> str:
    rows = "".join(
        f"""<tr>
          <td>{escape(trade.opened_at or 'N/A')}</td>
          <td>{escape(trade.closed_at or 'N/A')}</td>
          <td>{'Short' if getattr(trade, 'position_side', 'long') == 'short' else 'Long'}</td>
          <td>{escape(_fmt_holding_days(trade.holding_days))}</td>
          <td>{escape(_fmt_quantity(trade.quantity))}</td>
          <td>{escape(_fmt_gbp(trade.cost_basis_gbp))}</td>
          <td>{escape(_fmt_gbp(getattr(trade, "average_cost_basis_gbp", None)))}</td>
          <td>{escape(_fmt_gbp(trade.gross_proceeds_gbp))}</td>
          <td>{escape(_fmt_gbp(trade.implied_trading_cost_gbp))}</td>
          <td>{escape(_fmt_gbp(trade.net_proceeds_gbp))}</td>
          <td>{escape(_fmt_gbp(_safe_divide(trade.cost_basis_gbp, trade.quantity)))}</td>
          <td>{escape(_fmt_gbp(getattr(trade, "average_cost_per_share_gbp", None)))}</td>
          <td>{escape(_fmt_gbp(_safe_divide(trade.net_proceeds_gbp, trade.quantity)))}</td>
          <td class="{_pnl_class(trade.realized_pnl_gbp)}">{escape(_fmt_signed_gbp(trade.realized_pnl_gbp))}</td>
          <td class="{_pnl_class(getattr(trade, "average_cost_realized_pnl_gbp", None))}">{escape(_fmt_signed_gbp(getattr(trade, "average_cost_realized_pnl_gbp", None)))}</td>
        </tr>"""
        for trade in trades
    )
    return f"""<div class="small-note">以下 FIFO/均价/卖出金额均为 GBP 会计口径，用于和组合总收益对账；对美股等非GBP资产，这不是原生成交币种价格。Short 行的 FIFO成本表示买回成本，卖出净额表示卖空开仓收入。</div>
      <div class="portfolio-table-scroll">
        <table class="portfolio-table">
          <thead><tr><th>开仓日期</th><th>平仓日期</th><th>方向</th><th>持有期</th><th>匹配数量</th><th>FIFO成本GBP</th><th>均价成本GBP</th><th>卖出毛额GBP</th><th>交易成本GBP</th><th>卖出净额GBP</th><th>FIFO成本/股GBP</th><th>均价成本/股GBP</th><th>净卖出/股GBP</th><th>FIFO盈亏GBP</th><th>均价盈亏GBP</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>"""


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < 1e-12:
        return None
    return numerator / denominator


def _sum_optional(values) -> float | None:
    total = 0.0
    found = False
    for value in values:
        if value is None:
            continue
        total += value
        found = True
    return total if found else None


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
        <span class="portfolio-scope">GBP不亏价 {escape(_fmt_breakeven(position))}</span><br>
        <span class="portfolio-scope">卖出自动换回GBP后的账户不亏线；随当前FX变化</span></td>
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
        cycle = f" · {position.distribution_cycle_note}" if position.distribution_cycle_note else ""
        return (
            f"{_fmt_pct(position.drawdown_from_year_peak_pct)} · 峰值 {peak}"
            f"（{position.year_peak_date or '日期待确认'}）{sigma} · {position.drawdown_regime}{cycle}"
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

