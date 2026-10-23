"""Run at every startup (see entrypoint.sh): creates tables if missing,
seeds the admin user once, seeds historical events once, migrates any
stored prediction whose horizon doesn't match the current rule. All
idempotent - safe to run on every container start."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .config import settings
from .db import Base, engine, session_scope
from .events_seed import seed_historical_events
from .models import Prediction, User  # noqa: F401 - import registers the tables on Base.metadata
from .predictor import PREDICTION_HORIZON_HOURS
from .security import hash_password

logger = logging.getLogger("marketpulse.seed")


def migrate_prediction_horizon(db: Session) -> int:
    """Requested directly by the user when the horizon rule changed (48h ->
    24h, so a trade can actually be acted on the next day): brings every
    already-stored Prediction's horizon_hours in line with the current
    predictor.PREDICTION_HORIZON_HOURS, instead of leaving old rows stuck
    evaluating against whatever horizon was in effect when they were
    created - otherwise the backtest panel's stats would mix two different
    rules with no way to tell which was which. Idempotent: becomes a no-op
    once every row already matches, so it's safe to run on every startup."""
    updated = (
        db.query(Prediction)
        .filter(Prediction.horizon_hours != PREDICTION_HORIZON_HOURS)
        .update({"horizon_hours": PREDICTION_HORIZON_HOURS}, synchronize_session=False)
    )
    if updated:
        db.commit()
    return updated


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

    with session_scope() as db:
        migrated = migrate_prediction_horizon(db)
        if migrated:
            logger.info("Migrated %d prediction(s) to the %dh horizon", migrated, PREDICTION_HORIZON_HOURS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
