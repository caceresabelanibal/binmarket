from __future__ import annotations

from abc import ABC, abstractmethod

from .types import AlertEvent


class NotificationChannel(ABC):
    """A pluggable delivery mechanism for AlertEvents.

    New channels (e.g. a future SMS or push-notification integration) just
    implement `send`; the dispatcher discovers configured channels from env
    vars and fans every event out to all of them, so adding a channel never
    requires touching call sites that raise alerts.
    """

    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        ...

    @abstractmethod
    def send(self, event: AlertEvent) -> None:
        ...
