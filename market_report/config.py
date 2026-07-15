from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool
    smtp_host: str
    smtp_port: int
    security: str
    username: str
    password_env: str
    sender: str
    recipients: list[str]
    subject_prefix: str
    attach_html: bool


@dataclass(frozen=True)
class OptionsGammaConfig:
    enabled: bool
    benchmark_tickers: list[str]
    tickers: list[str]
    data_source_priority: list[str]
    alpha_vantage_api_key_env: str
    alpha_vantage_max_requests: int
    alpha_vantage_fetch_spot_quote: bool
    expirations_to_include: int
    max_days_to_expiry: int
    min_volume_threshold: int
    min_open_interest_threshold: int
    include_single_names: bool


@dataclass(frozen=True)
class OptionsSentimentConfig:
    enabled: bool
    benchmark_tickers: list[str]
    tickers: list[str]
    alpha_vantage_api_key_env: str
    include_holdings: bool
    max_tickers: int


@dataclass(frozen=True)
class AppConfig:
    report_title: str
    report_timezone: str
    output_dir: Path
    weights: dict[str, float]
    swing_watchlist: list[str]
    options_gamma: OptionsGammaConfig
    options_sentiment: OptionsSentimentConfig
    core_etf_plan: dict
    email: EmailConfig


def load_config(path: str) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        fallback = Path("config.example.json")
        if fallback.exists():
            config_path = fallback
        else:
            raise FileNotFoundError(f"Config file not found: {path}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    report = raw.get("report", {})
    email = raw.get("email", {})
    options_gamma = raw.get("options_gamma", {})
    options_sentiment = raw.get("options_sentiment", {})
    core_etf_plan = _json_env_or_mapping("CORE_ETF_PLAN_JSON", raw.get("core_etf_plan", {}))
    weights = _normalize_weights(raw.get("weights", {}))
    swing_watchlist = _env_list("SWING_WATCHLIST") or _as_list(raw.get("swing_watchlist", []))
    gamma_tickers = _env_list("OPTIONS_GAMMA_TICKERS") or _as_list(options_gamma.get("tickers", []))
    gamma_benchmarks = _env_list("OPTIONS_GAMMA_BENCHMARKS") or _as_list(
        options_gamma.get("benchmark_tickers", ["SPY", "QQQ"])
    )
    gamma_sources = _env_list("OPTIONS_GAMMA_DATA_SOURCES") or _as_list(
        options_gamma.get("data_source_priority", ["yahoo", "alpha_vantage"])
    )
    sentiment_tickers = _env_list("OPTIONS_SENTIMENT_TICKERS") or _as_list(options_sentiment.get("tickers", []))
    sentiment_benchmarks = _env_list("OPTIONS_SENTIMENT_BENCHMARKS") or _as_list(
        options_sentiment.get("benchmark_tickers", ["SPY", "QQQ"])
    )

    recipients = _env_list("REPORT_RECIPIENTS") or _as_list(email.get("to", []))
    username = os.environ.get("SMTP_USERNAME", email.get("username", ""))
    sender = os.environ.get("SMTP_FROM", email.get("from", username))

    return AppConfig(
        report_title=report.get("title", "Macro Regime Radar：宏观状态雷达"),
        report_timezone=report.get("timezone", "America/New_York"),
        output_dir=Path(report.get("output_dir", "output")),
        weights=weights,
        swing_watchlist=swing_watchlist,
        options_gamma=OptionsGammaConfig(
            enabled=_env_bool("OPTIONS_GAMMA_ENABLED", bool(options_gamma.get("enabled", True))),
            benchmark_tickers=gamma_benchmarks,
            tickers=gamma_tickers,
            data_source_priority=gamma_sources,
            alpha_vantage_api_key_env=str(
                os.environ.get(
                    "OPTIONS_GAMMA_ALPHA_KEY_ENV",
                    options_gamma.get("alpha_vantage_api_key_env", "ALPHA_VANTAGE_API_KEY"),
                )
            ),
            alpha_vantage_max_requests=int(
                os.environ.get("OPTIONS_GAMMA_ALPHA_MAX_REQUESTS", options_gamma.get("alpha_vantage_max_requests", 8))
            ),
            alpha_vantage_fetch_spot_quote=_env_bool(
                "OPTIONS_GAMMA_ALPHA_FETCH_SPOT",
                bool(options_gamma.get("alpha_vantage_fetch_spot_quote", True)),
            ),
            expirations_to_include=int(options_gamma.get("expirations_to_include", 3)),
            max_days_to_expiry=int(options_gamma.get("max_days_to_expiry", 30)),
            min_volume_threshold=int(options_gamma.get("min_volume_threshold", 100)),
            min_open_interest_threshold=int(options_gamma.get("min_open_interest_threshold", 100)),
            include_single_names=bool(options_gamma.get("include_single_names", True)),
        ),
        options_sentiment=OptionsSentimentConfig(
            enabled=_env_bool("OPTIONS_SENTIMENT_ENABLED", bool(options_sentiment.get("enabled", True))),
            benchmark_tickers=sentiment_benchmarks,
            tickers=sentiment_tickers,
            alpha_vantage_api_key_env=str(
                os.environ.get(
                    "OPTIONS_SENTIMENT_ALPHA_KEY_ENV",
                    options_sentiment.get("alpha_vantage_api_key_env", "ALPHA_VANTAGE_API_KEY"),
                )
            ),
            include_holdings=_env_bool(
                "OPTIONS_SENTIMENT_INCLUDE_HOLDINGS",
                bool(options_sentiment.get("include_holdings", True)),
            ),
            max_tickers=int(os.environ.get("OPTIONS_SENTIMENT_MAX_TICKERS", options_sentiment.get("max_tickers", 12))),
        ),
        core_etf_plan=core_etf_plan,
        email=EmailConfig(
            enabled=_env_bool("EMAIL_ENABLED", bool(email.get("enabled", False))),
            smtp_host=os.environ.get("SMTP_HOST", email.get("smtp_host", "smtp.gmail.com")),
            smtp_port=int(os.environ.get("SMTP_PORT", email.get("smtp_port", 587))),
            security=os.environ.get("SMTP_SECURITY", email.get("security", "starttls")),
            username=username,
            password_env=email.get("password_env", "SMTP_PASSWORD"),
            sender=sender,
            recipients=recipients,
            subject_prefix=email.get("subject_prefix", "Macro Regime Radar"),
            attach_html=bool(email.get("attach_html", True)),
        ),
    )


def _normalize_weights(raw: Mapping[str, float]) -> dict[str, float]:
    defaults = {
        "nasdaq": 0.4,
        "vix": 0.2,
        "treasury_10y": 0.2,
        "dxy": 0.2,
    }
    weights = {**defaults, **dict(raw)}
    total = sum(float(v) for v in weights.values())
    if total <= 0:
        raise ValueError("Weights must sum to a positive number.")
    return {k: float(v) / total for k, v in weights.items()}


def _as_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def _env_list(name: str) -> list[str]:
    return _as_list(os.environ.get(name, ""))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _json_env_or_mapping(name: str, fallback: object) -> dict:
    raw = os.environ.get(name)
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"{name} must contain a JSON object.")
        return parsed
    return dict(fallback) if isinstance(fallback, Mapping) else {}
