from __future__ import annotations

from email.message import EmailMessage

import pytest

from delivery import EmailSettings, build_email_message, load_email_settings, parse_recipients, send_email_message


def test_parse_recipients_supports_commas_and_semicolons():
    assert parse_recipients("alpha@example.com, beta@example.com;gamma@example.com") == [
        "alpha@example.com",
        "beta@example.com",
        "gamma@example.com",
    ]


def test_build_email_message_adds_html_and_attachment(tmp_path):
    attachment = tmp_path / "report.xlsx"
    attachment.write_bytes(b"xlsx")

    message = build_email_message(
        sender="reports@example.com",
        recipients=["client@example.com"],
        subject="Daily report",
        text_body="Plain text body",
        html_body="<html><body><strong>Styled body</strong></body></html>",
        attachments=[attachment],
    )

    assert message["To"] == "client@example.com"
    assert message.get_body(preferencelist=("html",)).get_content_type() == "text/html"

    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "report.xlsx"


def test_send_email_message_uses_starttls_and_login(monkeypatch):
    events: list[str] = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            events.append(f"connect:{host}:{port}:{timeout}")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append("close")
            return False

        def starttls(self, context):
            assert context is not None
            events.append("starttls")

        def login(self, username, password):
            events.append(f"login:{username}:{password}")

        def send_message(self, message: EmailMessage):
            events.append(f"send:{message['Subject']}")

    monkeypatch.setattr("delivery.smtplib.SMTP", FakeSMTP)

    message = build_email_message(
        sender="reports@example.com",
        recipients=["client@example.com"],
        subject="Daily report",
        text_body="Plain text body",
        html_body="<html><body>Styled body</body></html>",
    )
    settings = EmailSettings(
        host="smtp.example.com",
        port=587,
        sender="reports@example.com",
        username="mailer",
        password="secret",
        use_ssl=False,
        use_starttls=True,
    )

    send_email_message(message, settings)

    assert events == [
        "connect:smtp.example.com:587:30",
        "starttls",
        "login:mailer:secret",
        "send:Daily report",
        "close",
    ]


def test_load_email_settings_requires_sender_and_host(monkeypatch):
    monkeypatch.delenv("PERFSRAPER_EMAIL_FROM", raising=False)
    monkeypatch.delenv("PERFSRAPER_SMTP_HOST", raising=False)

    with pytest.raises(ValueError, match="PERFSRAPER_EMAIL_FROM, PERFSRAPER_SMTP_HOST"):
        load_email_settings()
