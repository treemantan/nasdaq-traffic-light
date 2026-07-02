from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, replace
from datetime import date, datetime
from pathlib import Path

from .config import load_config
from .data_sources import fetch_market_snapshot
from .event_risk_ledger import build_event_risk_ledger
from .emailer import send_report_email
from .etf_monitor import fetch_etf_monitor
from .mag7_capital_network import build_mag7_capital_network
from .memory import load_previous_regime, save_current_regime
from .news_monitor import fetch_news_monitor
from .options_gamma import OptionsGammaConfig as GammaRuntimeConfig
from .options_gamma import build_options_gamma_monitor
from .policy_risk_monitor import build_policy_risk_monitor
from .portfolio_events import build_portfolio_event_monitor
from .render import render_html_report
from .scoring import score_snapshot
from .shock_backtest import analyze_market_shock_history
from .technical_swing import build_technical_swing_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and optionally email the Macro Regime Radar report.")
    parser.add_argument("--config", default="config.json", help="Path to JSON config file.")
    parser.add_argument("--dry-run", action="store_true", help="Generate the report without sending email.")
    parser.add_argument("--output", help="Optional explicit output HTML path.")
    args = parser.parse_args()

    config = load_config(args.config)
    snapshot = fetch_market_snapshot()
    etf_monitor = fetch_etf_monitor(macro_metrics=snapshot.metrics)
    news_monitor = fetch_news_monitor()
    policy_risk_monitor = build_policy_risk_monitor(news_monitor)
    mag7_capital_network = build_mag7_capital_network()
    portfolio_event_monitor = build_portfolio_event_monitor(etf_monitor.portfolio_positions)
    event_risk_ledger = build_event_risk_ledger(
        policy_risk_monitor,
        news_monitor,
        etf_monitor.portfolio_positions,
        snapshot.metrics,
    )
    asset_classes = {
        asset.symbol.upper(): (
            "cash_like"
            if "cash-like" in asset.theme.lower() or "ultrashort" in asset.theme.lower()
            else "fixed_income"
            if not asset.equity_like
            else "equity"
        )
        for asset in etf_monitor.assets
    }
    technical_swing = build_technical_swing_report(
        etf_monitor.portfolio_positions,
        config.swing_watchlist,
        os.environ.get("TECHNICAL_TICKERS", ""),
        asset_classes=asset_classes,
    )
    options_gamma = build_options_gamma_monitor(
        GammaRuntimeConfig(
            enabled=config.options_gamma.enabled,
            benchmark_tickers=tuple(config.options_gamma.benchmark_tickers),
            extra_tickers=tuple(config.options_gamma.tickers),
            data_source_priority=tuple(config.options_gamma.data_source_priority),
            alpha_vantage_api_key_env=config.options_gamma.alpha_vantage_api_key_env,
            alpha_vantage_max_requests=config.options_gamma.alpha_vantage_max_requests,
            alpha_vantage_fetch_spot_quote=config.options_gamma.alpha_vantage_fetch_spot_quote,
            expirations_to_include=config.options_gamma.expirations_to_include,
            max_days_to_expiry=config.options_gamma.max_days_to_expiry,
            min_volume_threshold=config.options_gamma.min_volume_threshold,
            min_open_interest_threshold=config.options_gamma.min_open_interest_threshold,
            include_single_names=config.options_gamma.include_single_names,
        ),
        etf_monitor,
    )
    previous_regime = load_previous_regime(config.output_dir)
    scored = score_snapshot(
        snapshot,
        config.weights,
        previous_regime=previous_regime,
        report_timezone=config.report_timezone,
        etf_monitor=etf_monitor,
        news_monitor=news_monitor,
        mag7_capital_network=mag7_capital_network,
        portfolio_event_monitor=portfolio_event_monitor,
        technical_swing=technical_swing,
        options_gamma=options_gamma,
        policy_risk_monitor=policy_risk_monitor,
        event_risk_ledger=event_risk_ledger,
    )
    scored = replace(scored, market_shock_backtest=analyze_market_shock_history(snapshot.metrics))

    output_path = Path(args.output) if args.output else config.output_dir / f"market-report-{scored.report_date}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html_report(scored, config.report_title)
    output_path.write_text(html, encoding="utf-8")
    _write_report_payload(output_path.with_suffix(".json"), scored)
    save_current_regime(config.output_dir, scored.report_date, scored.regime.name, scored.summary)

    print(f"Report written to {output_path.resolve()}")
    terminal_light = {"绿灯": "green", "黄灯": "yellow", "红灯": "red"}.get(scored.light_label, scored.light_label)
    print(f"Score: {scored.overall_score}/100, light: {terminal_light}")
    terminal_data_quality = {"正常": "normal", "部分延迟": "partial-delay", "需核验": "needs-review"}.get(
        scored.data_quality,
        scored.data_quality,
    )
    print(f"Regime: {scored.regime.name}, confidence: {scored.regime.confidence_score}/100, data: {terminal_data_quality}")

    if args.dry_run or not config.email.enabled:
        print("Email skipped.")
        return 0

    send_report_email(config.email, scored, html, output_path)
    print("Email sent.")
    return 0


def _write_report_payload(path: Path, scored) -> None:
    path.write_text(json.dumps(asdict(scored), ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)
