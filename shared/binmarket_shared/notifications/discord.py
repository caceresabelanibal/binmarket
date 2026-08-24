from __future__ import annotations

import logging

import httpx

from binmarket_shared.config import settings

from .base import NotificationChannel
from .types import AlertEvent

logger = logging.getLogger("binmarket.notifications.discord")


class DiscordChannel(NotificationChannel):
    name = "discord"

    def is_configured(self) -> bool:
        return bool(settings.discord_webhook_url)

    def send(self, event: AlertEvent) -> None:
        content = f"**[{event.level.value}] {event.title}**\n{event.message}"
        try:
            response = httpx.post(settings.discord_webhook_url, json={"content": content}, timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to send Discord alert: %s", exc)
