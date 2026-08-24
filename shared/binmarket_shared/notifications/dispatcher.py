from __future__ import annotations

import logging

from .base import NotificationChannel
from .discord import DiscordChannel
from .email_channel import EmailChannel
from .telegram import TelegramChannel
from .types import AlertEvent

logger = logging.getLogger("binmarket.notifications")

_CHANNELS: list[NotificationChannel] = [TelegramChannel(), DiscordChannel(), EmailChannel()]


def notify(event: AlertEvent) -> None:
    """Fan an AlertEvent out to every configured channel.

    Web notifications are not sent from here: the frontend already receives
    every relevant event over the existing `/ws` fan-out (bot state, orders,
    risk events), so a dedicated web channel would just duplicate that path.
    Un-configured channels (empty tokens/webhooks) are silently skipped —
    this lets a fresh install run with zero alert channels active.
    """
    for channel in _CHANNELS:
        if not channel.is_configured():
            continue
        try:
            channel.send(event)
        except Exception:
            logger.exception("Notification channel %s failed", channel.name)
