from __future__ import annotations

import json
import os
import re
import smtplib
import sys
from base64 import b64encode
from datetime import date, datetime, time, timezone
from dataclasses import fields
from email.message import EmailMessage
from html import escape
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - keeps older local Python installs usable.
    ZoneInfo = None

from market_report.time_utils import _timezone_for


REQUIRED_RESEND_ENV = ("RESEND_API_KEY", "REPORT_EMAIL_TO", "REPORT_EMAIL_FROM")
REQUIRED_SMTP_ENV = ("SMTP_USERNAME", "SMTP_PASSWORD", "REPORT_EMAIL_TO")
VALID_PROVIDERS = {"resend", "smtp"}
VALID_MODES = {"none", "pulse", "volatility", "full", "auto"}
LONDON = ZoneInfo("Europe/London") if ZoneInfo else None


def main() -> int:
    provider = (os.environ.get("EMAIL_PROVIDER") or "resend").strip().lower()
    if provider not in VALID_PROVIDERS:
        print(f"Invalid EMAIL_PROVIDER '{provider}'. Expected one of: {', '.join(sorted(VALID_PROVIDERS))}", file=sys.stderr)
        return 2

    requested_mode = os.environ.get("EMAIL_MODE", "full").strip().lower()
    if requested_mode not in VALID_MODES:
        print(f"Invalid EMAIL_MODE '{requested_mode}'. Expected one of: {', '.join(sorted(VALID_MODES))}", file=sys.stderr)
        return 3

    mode = _infer_email_mode() if requested_mode == "auto" else requested_mode
    if mode == "none":
        print("EMAIL_MODE=none; report email skipped successfully.")
        return 0

    required_env = REQUIRED_SMTP_ENV if provider == "smtp" else REQUIRED_RESEND_ENV
    missing = [name for name in required_env if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        return 4

    output_dir = Path(os.environ.get("REPORT_OUTPUT_DIR", "output"))
    report_path = _latest_html_report(output_dir)
    if report_path is None:
        print("No HTML market report found in output directory.", file=sys.stderr)
        return 5

    html = report_path.read_text(encoding="utf-8")
    if not html.strip():
        print(f"HTML report is empty: {report_path}", file=sys.stderr)
        return 6

    payload = _load_payload(report_path)
    if mode in {"pulse", "volatility", "full"} and payload is None:
        print(f"Structured report payload not found for EMAIL_MODE={mode}: {report_path.with_suffix('.json')}", file=sys.stderr)
        return 7

    recipients = _parse_recipients(os.environ["REPORT_EMAIL_TO"])
    if not recipients:
        print("REPORT_EMAIL_TO does not contain any valid recipient address.", file=sys.stderr)
        return 8

    subject, message_html, message_text = _render_message(mode, report_path, html, payload)

    if provider == "smtp":
        return _send_smtp(subject, message_html, message_text, recipients, mode, report_path)
    return _send_resend(subject, message_html, message_text, recipients, mode, report_path)


def _send_resend(
    subject: str,
    message_html: str,
    message_text: str,
    recipients: list[str],
    mode: str,
    report_path: Path,
    attachments: list[dict[str, str | bytes]] | None = None,
) -> int:
    try:
        import resend

        resend.api_key = os.environ["RESEND_API_KEY"]
        payload = {
            "from": os.environ["REPORT_EMAIL_FROM"],
            "to": recipients,
            "subject": subject,
            "html": message_html,
            "text": message_text,
        }
        if attachments:
            payload["attachments"] = [
                {
                    "filename": str(item["filename"]),
                    "content": b64encode(_attachment_content_bytes(item["content"])).decode("ascii"),
                }
                for item in attachments
            ]
        response = resend.Emails.send(
            payload
        )
    except Exception as exc:
        print(f"Failed to send market report via Resend: {exc}", file=sys.stderr)
        return 9

    message_id = _response_id(response)
    suffix = f" Message id: {message_id}" if message_id else ""
    print(f"Market report email sent successfully via Resend. Mode: {mode}. Recipients: {len(recipients)}. Report: {report_path}.{suffix}")
    return 0


def _send_smtp(
    subject: str,
    message_html: str,
    message_text: str,
    recipients: list[str],
    mode: str,
    report_path: Path,
    attachments: list[dict[str, str | bytes]] | None = None,
) -> int:
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "587")
    security = (os.environ.get("SMTP_SECURITY") or "starttls").strip().lower()
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    sender = os.environ.get("SMTP_FROM") or os.environ.get("REPORT_EMAIL_FROM") or username

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(message_text)
    message.add_alternative(message_html, subtype="html")
    for item in attachments or []:
        maintype, _, subtype = str(item.get("mime_type", "application/octet-stream")).partition("/")
        message.add_attachment(
            _attachment_content_bytes(item["content"]),
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=str(item["filename"]),
        )

    try:
        if security == "ssl" or port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                if security != "none":
                    smtp.starttls()
                smtp.login(username, password)
                smtp.send_message(message)
    except Exception as exc:
        print(f"Failed to send market report via SMTP: {exc}", file=sys.stderr)
        return 10

    print(f"Market report email sent successfully via SMTP. Mode: {mode}. Recipients: {len(recipients)}. Report: {report_path}.")
    return 0


def _attachment_content_bytes(content: str | bytes) -> bytes:
    if isinstance(content, bytes):
        return content
    return content.encode("utf-8")


def _infer_email_mode(now: datetime | None = None) -> str:
    local_now = _london_now(now)
    current = local_now.time()
    if current < time(8, 0):
        return "none"
    if current < time(16, 30):
        return "pulse"
    if current < time(20, 0):
        return "volatility"
    return "full"


def _latest_html_report(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None
    reports = sorted(output_dir.glob("*.html"), key=lambda path: path.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def _load_payload(report_path: Path) -> dict | None:
    payload_path = report_path.with_suffix(".json")
    if not payload_path.exists():
        return None
    return json.loads(payload_path.read_text(encoding="utf-8"))


def _render_message(mode: str, report_path: Path, full_html: str, payload: dict | None) -> tuple[str, str, str]:
    report_date = _report_date(report_path)
    if mode == "full":
        subject = f"Macro Regime Radar - {report_date}"
        try:
            from market_report.render_email import render_email_report

            message_html = render_email_report(_report_from_payload(payload or {}))
        except Exception as exc:
            print(f"Failed to render email-optimized full report from payload: {exc}", file=sys.stderr)
            raise
        text = (
            f"Macro Regime Radar - {report_date}\n\n"
            "The email-optimized HTML market report was generated successfully. "
            "If your email client does not render HTML, please open the GitHub Actions artifact named market-report."
        )
        return subject, message_html, text
    if mode == "pulse":
        return _render_pulse(payload or {})
    if mode == "volatility":
        return _render_volatility(payload or {})
    raise ValueError(f"Unsupported email mode: {mode}")


def _report_from_payload(payload: dict):
    from market_report.data_sources import MarketMetric
    from market_report.etf_monitor import (
        ETFAssetMonitor,
        ETFBacktestStats,
        ETFMonitor,
        ETFThresholdCalibration,
        PortfolioExposure,
        PortfolioPerformance,
        PortfolioPosition,
    )
    from market_report.scoring import (
        IronCondorAssessment,
        RegimeAssessment,
        ScoreDriver,
        ScoredMetric,
        ScoredReport,
    )
    from market_report.news_monitor import NewsEvent, NewsMonitor
    from market_report.mag7_capital_network import AggregateCapitalDisclosure, CapitalRelation, Mag7CapitalNetwork
    from market_report.portfolio_events import PortfolioEventMonitor, PortfolioEventObservation

    metrics = {
        key: _dataclass_from_dict(
            ScoredMetric,
            value,
            converters={"metric": lambda raw: _market_metric_from_payload(raw or {})},
        )
        for key, value in (payload.get("metrics") or {}).items()
        if isinstance(value, dict)
    }
    etf_monitor = None
    if isinstance(payload.get("etf_monitor"), dict):
        etf_monitor = _dataclass_from_dict(
            ETFMonitor,
            payload["etf_monitor"],
            converters={
                "assets": lambda raw: [
                    _etf_asset_from_payload(item)
                    for item in (raw or [])
                    if isinstance(item, dict)
                ],
                "warnings": lambda raw: list(raw or []),
                "portfolio_positions": lambda raw: [
                    _dataclass_from_dict(PortfolioPosition, item)
                    for item in (raw or [])
                    if isinstance(item, dict)
                ],
                "portfolio_exposures": lambda raw: [
                    _dataclass_from_dict(PortfolioExposure, item)
                    for item in (raw or [])
                    if isinstance(item, dict)
                ],
                "portfolio_performance": lambda raw: (
                    _dataclass_from_dict(PortfolioPerformance, raw) if isinstance(raw, dict) else None
                ),
                "portfolio_mag7_exposures": lambda raw: [
                    _dataclass_from_dict(PortfolioExposure, item)
                    for item in (raw or [])
                    if isinstance(item, dict)
                ],
            },
        )
    news_monitor = None
    if isinstance(payload.get("news_monitor"), dict):
        news_monitor = _dataclass_from_dict(
            NewsMonitor,
            payload["news_monitor"],
            converters={
                "events": lambda raw: tuple(
                    _dataclass_from_dict(
                        NewsEvent,
                        item,
                        converters={
                            "themes": lambda themes: tuple(themes or ()),
                            "tickers": lambda tickers: tuple(tickers or ()),
                            "entities": lambda entities: tuple(entities or ()),
                        },
                    )
                    for item in (raw or [])
                    if isinstance(item, dict)
                ),
                "review_required_symbols": lambda raw: tuple(raw or ()),
                "warnings": lambda raw: tuple(raw or ()),
            },
        )
    mag7_capital_network = None
    if isinstance(payload.get("mag7_capital_network"), dict):
        mag7_capital_network = _dataclass_from_dict(
            Mag7CapitalNetwork,
            payload["mag7_capital_network"],
            converters={
                "relations": lambda raw: tuple(
                    _dataclass_from_dict(
                        CapitalRelation,
                        item,
                        converters={"themes": lambda themes: tuple(themes or ())},
                    )
                    for item in (raw or [])
                    if isinstance(item, dict)
                ),
                "aggregate_disclosures": lambda raw: tuple(
                    _dataclass_from_dict(AggregateCapitalDisclosure, item)
                    for item in (raw or [])
                    if isinstance(item, dict)
                ),
                "warnings": lambda raw: tuple(raw or ()),
            },
        )
    portfolio_event_monitor = None
    if isinstance(payload.get("portfolio_event_monitor"), dict):
        portfolio_event_monitor = _dataclass_from_dict(
            PortfolioEventMonitor,
            payload["portfolio_event_monitor"],
            converters={
                "events": lambda raw: tuple(
                    _dataclass_from_dict(
                        PortfolioEventObservation,
                        item,
                        converters={
                            "symbols": lambda symbols: tuple(symbols or ()),
                            "watch_items": lambda watch_items: tuple(watch_items or ()),
                            "event_at": _parse_datetime_or_now,
                            "reminder_at": _parse_datetime_or_now,
                        },
                    )
                    for item in (raw or [])
                    if isinstance(item, dict)
                ),
                "warnings": lambda raw: tuple(raw or ()),
            },
        )

    return _dataclass_from_dict(
        ScoredReport,
        payload,
        converters={
            "metrics": lambda _raw: metrics,
            "regime": lambda raw: _dataclass_from_dict(RegimeAssessment, raw or {}),
            "iron_condor": lambda raw: _dataclass_from_dict(IronCondorAssessment, raw or {}),
            "score_drivers": lambda raw: [
                _dataclass_from_dict(ScoreDriver, item)
                for item in (raw or [])
                if isinstance(item, dict)
            ],
            "etf_monitor": lambda _raw: etf_monitor,
            "news_monitor": lambda _raw: news_monitor,
            "mag7_capital_network": lambda _raw: mag7_capital_network,
            "portfolio_event_monitor": lambda _raw: portfolio_event_monitor,
            "market_shock_backtest": _market_shock_backtest_from_payload,
        },
    )


def _market_metric_from_payload(raw: dict):
    from market_report.data_sources import MarketMetric

    return _dataclass_from_dict(
        MarketMetric,
        raw,
        converters={
            "as_of": _parse_date_or_none,
            "fetched_at": _parse_datetime_or_now,
            "warnings": lambda value: tuple(value or ()),
        },
    )


def _etf_asset_from_payload(raw: dict):
    from market_report.etf_monitor import ETFAssetMonitor, ETFHolding, ETFSensitivity

    return _dataclass_from_dict(
        ETFAssetMonitor,
        raw,
        converters={
            "as_of": _parse_date_or_none,
            "fetched_at": _parse_datetime_or_now,
            "warnings": lambda value: tuple(value or ()),
            "backtest": _etf_backtest_from_payload,
            "holdings": lambda items: tuple(
                _dataclass_from_dict(ETFHolding, item)
                for item in (items or [])
                if isinstance(item, dict)
            ),
            "sensitivities": lambda items: tuple(
                _dataclass_from_dict(ETFSensitivity, item)
                for item in (items or [])
                if isinstance(item, dict)
            ),
        },
    )


def _etf_backtest_from_payload(raw: object):
    from market_report.etf_monitor import ETFBacktestStats, ETFSimilarSample, ETFThresholdCalibration

    if not isinstance(raw, dict):
        return None
    return _dataclass_from_dict(
        ETFBacktestStats,
        raw,
        converters={
            "threshold_calibrations": lambda items: tuple(
                _dataclass_from_dict(ETFThresholdCalibration, item)
                for item in (items or [])
                if isinstance(item, dict)
            ),
            "similar_samples": lambda items: tuple(
                _dataclass_from_dict(ETFSimilarSample, item)
                for item in (items or [])
                if isinstance(item, dict)
            ),
        },
    )


def _market_shock_backtest_from_payload(raw: object):
    from market_report.shock_backtest import MarketShockBacktest, MarketShockSample

    if not isinstance(raw, dict):
        return None
    return _dataclass_from_dict(
        MarketShockBacktest,
        raw,
        converters={
            "samples": lambda items: tuple(
                _dataclass_from_dict(MarketShockSample, item)
                for item in (items or [])
                if isinstance(item, dict)
            ),
            "notes": lambda items: tuple(items or ()),
        },
    )


def _dataclass_from_dict(cls, raw: dict, converters: dict | None = None):
    converters = converters or {}
    values = {}
    for item in fields(cls):
        if item.name not in raw:
            continue
        value = raw[item.name]
        if item.name in converters:
            value = converters[item.name](value)
        values[item.name] = value
    return cls(**values)


def _parse_date_or_none(value: object) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_datetime_or_now(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _render_pulse(payload: dict) -> tuple[str, str, str]:
    stamp = _uk_stamp()
    regime = payload.get("regime", {})
    iron = payload.get("iron_condor", {})
    risks = (payload.get("risks") or [])[:5]
    blockers = iron.get("blockers") or []
    etf_items = _etf_pulse_items(payload)
    subject = f"Market Pulse - {stamp}"
    rows = [
        ("综合风险分", f"{payload.get('overall_score', 'N/A')}/100"),
        ("红绿灯状态", payload.get("light_label", "N/A")),
        ("主导宏观框架", regime.get("label", "N/A")),
        ("Regime置信度", f"{regime.get('confidence_score', 'N/A')}/100"),
        ("Iron Condor环境", f"{iron.get('label', 'N/A')} · {iron.get('score', 'N/A')}/100"),
    ]
    html = _html_shell(
        "Market Pulse",
        _definition_table(rows)
        + _bullet_section("UK ETF开盘观察", etf_items)
        + _bullet_section("关键风险变化", risks)
        + _bullet_section("触发警报 / 阻断项", blockers)
        + "<p style='color:#9ca3af;'>Full report will be sent after the US market close.</p>",
    )
    text = "\n".join(
        [
            subject,
            f"Overall risk score: {payload.get('overall_score', 'N/A')}/100",
            f"Light label: {payload.get('light_label', 'N/A')}",
            f"Macro regime: {regime.get('label', 'N/A')}",
            f"Regime confidence: {regime.get('confidence_score', 'N/A')}/100",
            f"Iron Condor: {iron.get('label', 'N/A')} · {iron.get('score', 'N/A')}/100",
            "Key risks: " + ("; ".join(risks) if risks else "N/A"),
            "UK ETF pulse: " + ("; ".join(etf_items) if etf_items else "N/A"),
            "Alerts/blockers: " + ("; ".join(blockers) if blockers else "N/A"),
            "Full report will be sent after the US market close.",
        ]
    )
    return subject, html, text


def _etf_pulse_items(payload: dict) -> list[str]:
    assets = ((payload.get("etf_monitor") or {}).get("assets") or [])
    valid = [asset for asset in assets if isinstance(asset, dict)]
    if not valid:
        return []

    items: list[str] = []
    movers = [asset for asset in valid if isinstance(asset.get("change_pct"), (int, float))]
    if movers:
        strongest = max(movers, key=lambda asset: asset["change_pct"])
        weakest = min(movers, key=lambda asset: asset["change_pct"])
        items.append(
            f"最强ETF：{strongest.get('symbol', 'N/A')} {strongest.get('change_pct', 0):+.2f}%"
            f"，{strongest.get('entry_label', '新增仓位环境待确认')}"
        )
        items.append(
            f"最弱ETF：{weakest.get('symbol', 'N/A')} {weakest.get('change_pct', 0):+.2f}%"
            f"，{weakest.get('entry_label', '新增仓位环境待确认')}"
        )

    scored = [asset for asset in valid if isinstance(asset.get("entry_score"), int)]
    if scored:
        preferred = max(scored, key=lambda asset: asset["entry_score"])
        pressured = min(scored, key=lambda asset: asset["entry_score"])
        items.append(
            f"新增仓位环境最高：{preferred.get('symbol', 'N/A')} "
            f"{preferred.get('entry_score', 'N/A')}/100，{preferred.get('entry_label', 'N/A')}"
        )
        items.append(
            f"新增仓位环境最低：{pressured.get('symbol', 'N/A')} "
            f"{pressured.get('entry_score', 'N/A')}/100，{pressured.get('entry_label', 'N/A')}"
        )

    crowded = [
        asset
        for asset in valid
        if isinstance(asset.get("crowding_score"), int) and asset.get("crowding_score", 0) >= 85
    ]
    if crowded:
        symbols = "、".join(str(asset.get("symbol", "N/A")) for asset in crowded[:4])
        items.append(f"拥挤度偏高：{symbols}，需关注RSI和趋势拉伸。")
    return items[:5]


def _render_volatility(payload: dict) -> tuple[str, str, str]:
    stamp = _uk_stamp()
    iron = payload.get("iron_condor", {})
    blockers = iron.get("blockers") or []
    warnings = iron.get("warnings") or []
    worsening = _short_vol_environment_answer(iron)
    subject = f"Volatility Regime Update - {stamp}"
    rows = [
        ("VIX", _metric_line(payload, "vix")),
        ("VVIX", _metric_line(payload, "vvix")),
        ("MOVE", _metric_line(payload, "move")),
        ("Nasdaq 100", _metric_pct_line(payload, "nasdaq")),
        ("S&P 500", _metric_pct_line(payload, "sp500")),
        ("10Y Treasury", _metric_value_change_line(payload, "treasury_10y")),
        ("DXY", _metric_pct_line(payload, "dxy")),
        ("Iron Condor环境", f"{iron.get('label', 'N/A')} · {iron.get('score', 'N/A')}/100"),
    ]
    body = (
        f"<p><strong>核心判断：</strong>{escape(worsening)}</p>"
        + _definition_table(rows)
        + _bullet_section("短波动策略相关阻断项", blockers)
        + _bullet_section("短波动策略相关风险提示", warnings[:6])
        + "<p style='color:#9ca3af;'>本邮件仅评估宏观与波动率环境，不构成期权交易建议。</p>"
    )
    html = _html_shell("Volatility / Iron Condor Regime", body)
    text = "\n".join(
        [
            subject,
            f"Core answer: {worsening}",
            f"VIX: {_metric_line(payload, 'vix')}",
            f"VVIX: {_metric_line(payload, 'vvix')}",
            f"MOVE: {_metric_line(payload, 'move')}",
            f"Nasdaq 100: {_metric_pct_line(payload, 'nasdaq')}",
            f"S&P 500: {_metric_pct_line(payload, 'sp500')}",
            f"10Y Treasury: {_metric_value_change_line(payload, 'treasury_10y')}",
            f"DXY: {_metric_pct_line(payload, 'dxy')}",
            f"Iron Condor: {iron.get('label', 'N/A')} · {iron.get('score', 'N/A')}/100",
            "Blockers: " + ("; ".join(blockers) if blockers else "N/A"),
            "Warnings: " + ("; ".join(warnings[:6]) if warnings else "N/A"),
            "This message evaluates market environment only and is not options trading advice.",
        ]
    )
    return subject, html, text


def _short_vol_environment_answer(iron: dict) -> str:
    score = iron.get("score")
    blockers = iron.get("blockers") or []
    if blockers or (isinstance(score, int) and score < 50):
        return "是。当前波动率、利率波动或权益方向性压力正在恶化，区间型卖波动策略的结构性容错下降。"
    if isinstance(score, int) and score < 75:
        return "边际偏谨慎。环境未进入明确压力状态，但仍需要观察波动率和利率冲击是否继续扩散。"
    return "暂未恶化。波动率与跨资产压力仍相对可控，但仍需等待后续数据确认。"


def _metric_line(payload: dict, key: str) -> str:
    metric = _metric(payload, key)
    value = _fmt(metric.get("value"), metric.get("unit", ""))
    change_pct = _metric_change_pct(metric)
    pct = f"{change_pct:+.2f}%" if isinstance(change_pct, (int, float)) else "N/A"
    return f"{value} / {pct}"


def _metric_pct_line(payload: dict, key: str) -> str:
    metric = _metric(payload, key)
    change_pct = _metric_change_pct(metric)
    return f"{change_pct:+.2f}%" if isinstance(change_pct, (int, float)) else "N/A"


def _metric_value_change_line(payload: dict, key: str) -> str:
    metric = _metric(payload, key)
    value = _fmt(metric.get("value"), metric.get("unit", ""))
    change = _metric_change(metric)
    unit = metric.get("unit", "")
    change_text = f"{change:+.3f}{unit}" if isinstance(change, (int, float)) else "N/A"
    return f"{value} / {change_text}"


def _metric(payload: dict, key: str) -> dict:
    scored = (payload.get("metrics") or {}).get(key) or {}
    return scored.get("metric") or {}


def _metric_change(metric: dict) -> float | None:
    raw = metric.get("change")
    if isinstance(raw, (int, float)):
        return float(raw)
    value = metric.get("value")
    previous = metric.get("previous_value")
    if not isinstance(value, (int, float)) or not isinstance(previous, (int, float)):
        return None
    return float(value) - float(previous)


def _metric_change_pct(metric: dict) -> float | None:
    raw = metric.get("change_pct")
    if isinstance(raw, (int, float)):
        return float(raw)
    value = metric.get("value")
    previous = metric.get("previous_value")
    if not isinstance(value, (int, float)) or not isinstance(previous, (int, float)) or previous == 0:
        return None
    return (float(value) / float(previous) - 1) * 100


def _definition_table(rows: list[tuple[str, str]]) -> str:
    items = "".join(
        f"<tr><td style='padding:7px 10px;color:#9ca3af;border-bottom:1px solid #263244;'>{escape(label)}</td>"
        f"<td style='padding:7px 10px;color:#f3f4f6;border-bottom:1px solid #263244;'>{escape(str(value))}</td></tr>"
        for label, value in rows
    )
    return f"<table width='100%' cellspacing='0' cellpadding='0' style='border-collapse:collapse;'>{items}</table>"


def _bullet_section(title: str, items: list[str]) -> str:
    if not items:
        items = ["暂无明显信号。"]
    bullets = "".join(f"<li>{escape(str(item))}</li>" for item in items)
    return f"<h3 style='font-size:15px;color:#f3f4f6;margin:16px 0 8px;'>{escape(title)}</h3><ul>{bullets}</ul>"


def _html_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<body style="margin:0;padding:0;background:#0b1017;font-family:Arial,'Microsoft YaHei',sans-serif;color:#f3f4f6;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0b1017;width:100%;">
    <tr><td align="center" style="padding:22px 12px;">
      <table role="presentation" width="680" cellspacing="0" cellpadding="0" style="width:680px;max-width:100%;background:#111827;border:1px solid #263244;border-radius:8px;">
        <tr><td style="padding:20px 22px;border-bottom:1px solid #263244;">
          <div style="font-size:24px;line-height:1.25;font-weight:700;color:#f3f4f6;">{escape(title)}</div>
          <div style="font-size:13px;color:#9ca3af;margin-top:5px;">Macro Regime Radar · UK monitor</div>
        </td></tr>
        <tr><td style="padding:18px 22px;color:#d1d5db;font-size:14px;line-height:1.55;">{body}</td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _fmt(value: object, unit: str = "") -> str:
    if not isinstance(value, (int, float)):
        return "N/A"
    if unit == "%":
        return f"{value:.3f}%"
    if unit == "bp":
        return f"{value:.0f}bp"
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _parse_recipients(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _report_date(path: Path) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else date.today().isoformat()


def _uk_stamp() -> str:
    return _london_now().strftime("%Y-%m-%d %H:%M UK")


def _london_now(now: datetime | None = None) -> datetime:
    if LONDON is not None:
        return now.astimezone(LONDON) if now else datetime.now(LONDON)
    utc_now = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    return utc_now.astimezone(_timezone_for(utc_now, "Europe/London"))


def _response_id(response: object) -> str | None:
    if isinstance(response, dict):
        value = response.get("id")
        return str(value) if value else None
    value = getattr(response, "id", None)
    return str(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
