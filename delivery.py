from __future__ import annotations

import mimetypes
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Sequence


@dataclass
class EmailSettings:
    host: str
    port: int
    sender: str
    username: str | None = None
    password: str | None = None
    use_ssl: bool = False
    use_starttls: bool = True


def parse_recipients(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_email_settings(sender: str | None = None) -> EmailSettings:
    resolved_sender = sender or os.getenv("PERFSRAPER_EMAIL_FROM")
    host = os.getenv("PERFSRAPER_SMTP_HOST")
    port = int(os.getenv("PERFSRAPER_SMTP_PORT", "587"))
    username = os.getenv("PERFSRAPER_SMTP_USERNAME")
    password = os.getenv("PERFSRAPER_SMTP_PASSWORD")
    use_ssl = _env_flag("PERFSRAPER_SMTP_USE_SSL", default=False)
    use_starttls = _env_flag("PERFSRAPER_SMTP_STARTTLS", default=not use_ssl)

    missing = []
    if not resolved_sender:
        missing.append("PERFSRAPER_EMAIL_FROM")
    if not host:
        missing.append("PERFSRAPER_SMTP_HOST")
    if username and password is None:
        missing.append("PERFSRAPER_SMTP_PASSWORD")

    if missing:
        raise ValueError("Email delivery requires environment variables: " + ", ".join(missing))

    return EmailSettings(
        host=host,
        port=port,
        sender=resolved_sender,
        username=username,
        password=password,
        use_ssl=use_ssl,
        use_starttls=use_starttls,
    )


def build_email_message(
    sender: str,
    recipients: Sequence[str],
    subject: str,
    text_body: str,
    html_body: str,
    attachments: Sequence[str | Path] = (),
) -> EmailMessage:
    if not recipients:
        raise ValueError("At least one email recipient is required.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    for attachment in attachments:
        path = Path(attachment)
        mime_type, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)

    return message


def send_email_message(message: EmailMessage, settings: EmailSettings) -> None:
    smtp_cls = smtplib.SMTP_SSL if settings.use_ssl else smtplib.SMTP
    with smtp_cls(settings.host, settings.port, timeout=30) as smtp:
        if not settings.use_ssl and settings.use_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.username:
            smtp.login(settings.username, settings.password or "")
        smtp.send_message(message)


def send_report_email(
    settings: EmailSettings,
    recipients: Sequence[str],
    subject: str,
    text_body: str,
    html_body: str,
    attachments: Sequence[str | Path] = (),
) -> EmailMessage:
    message = build_email_message(
        sender=settings.sender,
        recipients=recipients,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
    )
    send_email_message(message, settings)
    return message
