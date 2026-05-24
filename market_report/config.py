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
class AppConfig:
    report_title: str
    report_timezone: str
    output_dir: Path
    weights: dict[str, float]
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
    weights = _normalize_weights(raw.get("weights", {}))

    recipients = _env_list("REPORT_RECIPIENTS") or _as_list(email.get("to", []))
    username = os.environ.get("SMTP_USERNAME", email.get("username", ""))
    sender = os.environ.get("SMTP_FROM", email.get("from", username))

    return AppConfig(
        report_title=report.get("title", "Macro Regime Radar：宏观状态雷达"),
        report_timezone=report.get("timezone", "America/New_York"),
        output_dir=Path(report.get("output_dir", "output")),
        weights=weights,
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
