"""Run at every startup (see entrypoint.sh): creates tables if missing,
seeds the admin user once, seeds historical events once. All idempotent -
safe to run on every container start."""
from __future__ import annotations

import logging

from .config import settings
from .db import Base, engine, session_scope
from .events_seed import seed_historical_events
from .models import User  # noqa: F401 - import registers the table on Base.metadata
from .security import hash_password

logger = logging.getLogger("marketpulse.seed")


def run() -> None:
    Base.metadata.create_all(engine)

    with session_scope() as db:
        existing = db.query(User).filter(User.username == settings.admin_username).one_or_none()
        if existing is None:
            db.add(User(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
            logger.info("Created default admin user '%s'", settings.admin_username)

    with session_scope() as db:
        count = seed_historical_events(db)
        if count:
            logger.info("Seeded %d historical events", count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
