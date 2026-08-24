from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from binmarket_shared.config import settings

from .base import NotificationChannel
from .types import AlertEvent

logger = logging.getLogger("binmarket.notifications.email")


class EmailChannel(NotificationChannel):
    name = "email"

    def is_configured(self) -> bool:
        return bool(settings.smtp_host and settings.smtp_from_email and settings.alert_email_to)

    def send(self, event: AlertEvent) -> None:
        msg = MIMEText(f"{event.message}\n\nCategory: {event.category}\nAt: {event.occurred_at.isoformat()}")
        msg["Subject"] = f"[BinMarket {event.level.value}] {event.title}"
        msg["From"] = settings.smtp_from_email
        msg["To"] = settings.alert_email_to
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                server.starttls()
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.sendmail(settings.smtp_from_email, [settings.alert_email_to], msg.as_string())
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("Failed to send email alert: %s", exc)
