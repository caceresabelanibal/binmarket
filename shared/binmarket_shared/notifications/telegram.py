from __future__ import annotations

import logging

import httpx

from binmarket_shared.config import settings

from .base import NotificationChannel
from .types import AlertEvent

logger = logging.getLogger("binmarket.notifications.telegram")


class TelegramChannel(NotificationChannel):
    name = "telegram"

    def is_configured(self) -> bool:
        return bool(settings.telegram_bot_token and settings.telegram_chat_id)

    def send(self, event: AlertEvent) -> None:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        text = f"*{event.level.value}* — {event.title}\n{event.message}"
        try:
            response = httpx.post(
                url,
                json={"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to send Telegram alert: %s", exc)
