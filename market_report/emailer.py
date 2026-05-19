from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .config import EmailConfig
from .render_email import render_email_report
from .scoring import ScoredReport


def send_report_email(config: EmailConfig, report: ScoredReport, html: str, attachment_path: Path) -> None:
    if not config.recipients:
        raise ValueError("No email recipients configured. Set email.to or REPORT_RECIPIENTS.")
    if not config.username:
        raise ValueError("No SMTP username configured. Set email.username or SMTP_USERNAME.")
    password = os.environ.get(config.password_env)
    if not password:
        raise ValueError(f"Missing SMTP password environment variable: {config.password_env}")

    subject = _subject(config, report)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.sender or config.username
    message["To"] = ", ".join(config.recipients)
    message.set_content(_plain_text_body(report, attachment_path))
    message.add_alternative(render_email_report(report), subtype="html")

    if config.attach_html:
        message.add_attachment(
            attachment_path.read_bytes(),
            maintype="text",
            subtype="html",
            filename=attachment_path.name,
        )

    if config.security == "ssl" or config.smtp_port == 465:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30) as smtp:
            smtp.login(config.username, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
        if config.security != "none":
            smtp.starttls()
        smtp.login(config.username, password)
        smtp.send_message(message)


def _subject(config: EmailConfig, report: ScoredReport) -> str:
    return (
        f"{config.subject_prefix} | {report.report_date} | "
        f"{report.regime.name} | {report.light_label}{report.overall_score}/100 | 数据:{report.data_quality}"
    )


def _plain_text_body(report: ScoredReport, attachment_path: Path) -> str:
    return f"""纳斯达克红绿灯日报已生成。

日期：{report.report_date}
宏观框架：{report.regime.label} ({report.regime.name})
综合风险分：{report.overall_score}/100
数据健康度：{report.data_quality}
置信度：{report.regime.confidence_score}/100

核心结论：
{report.summary}

数据提示：
核心缓存：{report.data_health.get("core_cached", 0)}
核心缺失：{report.data_health.get("core_missing", 0)}
辅助缺失：{report.data_health.get("aux_missing", 0)}

HTML报告：{attachment_path.name}

免责声明：本报告仅用于宏观市场监控与研究参考，不构成投资建议。
"""
