from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class AlertLevel(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class AlertEvent:
    """A notification-worthy event. Alert channels only ever see this shape,
    never internal ORM objects, so channels stay decoupled from the DB layer.
    """

    title: str
    message: str
    level: AlertLevel = AlertLevel.INFO
    category: str = "general"  # e.g. buy, sell, stop_loss, take_profit, error, risk, connectivity
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
