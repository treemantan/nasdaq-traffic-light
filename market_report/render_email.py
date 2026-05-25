from __future__ import annotations

from html import escape

from .data_sources import MarketMetric
from .etf_monitor import ETFAssetMonitor, ETFMonitor
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
    etf_monitor = _render_etf_monitor(report.etf_monitor)
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


def _render_etf_monitor(monitor: ETFMonitor | None) -> str:
    if monitor is None:
        return ""
    rows = "".join(_render_etf_row(asset) for asset in monitor.assets)
    return f"""<tr>
      <td style="padding:0 24px 18px;">
        <div style="font-size:19px;font-weight:700;color:#f3f4f6;margin:8px 0 8px;">UK ETF估值、趋势与拥挤度监控器</div>
        <div style="font-size:13px;color:#d1d5db;margin-bottom:8px;">{escape(monitor.summary)}</div>
        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:12px;color:#d1d5db;">
          <tr>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">ETF</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">主题</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">1Dσ / 1M / RSI</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">PE / Fwd PE</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">PE位置</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">新增仓位环境</th>
            <th align="left" style="padding:7px;border-bottom:1px solid #263244;color:#9ca3af;">拥挤度</th>
          </tr>
          {rows}
        </table>
        <div style="font-size:12px;color:#9ca3af;margin-top:8px;">PE位置优先显示本地历史分位；样本不足时显示当前PE/近一年缓存最高PE的近似比例。σ200使用去极值后的稳健趋势波动率，避免少数极端日收益掩盖趋势拉伸。proxy 表示使用同类ETF作近似估值参考；黄金ETC不适用PE/PB。</div>
      </td>
    </tr>"""


def _render_etf_row(asset: ETFAssetMonitor) -> str:
    valuation_source = f"估值源：{asset.valuation_source}" if asset.valuation_source != "unavailable" else "估值源：暂无"
    return f"""<tr>
      <td style="padding:7px;border-bottom:1px solid #263244;"><strong>{escape(asset.symbol)}</strong><br>{escape(asset.provider)}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(asset.theme)}<br>{escape(_fmt_sigma_200d(asset.trend_sigma_200d))} · {escape(asset.trend_stretch_label)}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(_fmt_sigma(asset.daily_sigma))} / {escape(_fmt_pct(asset.momentum_1m))} / {escape(_fmt_plain(asset.rsi14))}<br>{escape(asset.sigma_label)}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(_fmt_plain(asset.pe))} / {escape(_fmt_plain(asset.forward_pe))}<br>{escape(asset.valuation_label)}<br><span style="color:#9ca3af;">{escape(valuation_source)}</span></td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{escape(_fmt_pe_position(asset))}</td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{asset.entry_score}/100<br>{escape(asset.entry_label)}<br><span style="color:#9ca3af;">{escape(_fmt_backtest(asset))}</span></td>
      <td style="padding:7px;border-bottom:1px solid #263244;">{asset.crowding_score}/100<br>{escape(asset.crowding_label)}</td>
    </tr>"""


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
    return (
        f"历史检验：{backtest.reliability}；≥{backtest.threshold}样本 {backtest.good_count}/{backtest.sample_size}；"
        f"3M {_fmt_pct(backtest.good_forward_3m)} vs 全样本 {_fmt_pct(backtest.all_forward_3m)}"
    )


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
