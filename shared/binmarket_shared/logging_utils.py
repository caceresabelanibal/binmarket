"""Structured logging: stdlib logging to stdout (captured by `docker logs`)
plus a `log_event` helper that persists to the `system_logs` table so the
frontend's System Logs screen can show cross-service history without needing
a separate log-aggregation stack.
"""
from __future__ import annotations

import logging
import sys

from binmarket_shared.db.base import session_scope
from binmarket_shared.db.models import SystemLog


def configure_logging(service: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{service}] %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def log_event(service: str, level: str, message: str, context: dict | None = None) -> None:
    logger = logging.getLogger(f"binmarket.{service}")
    getattr(logger, level.lower(), logger.info)(message)
    try:
        with session_scope() as db:
            db.add(SystemLog(service=service, level=level.upper(), message=message, context=context or {}))
    except Exception:
        logger.exception("Failed to persist system log entry")
