from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.redis_client import redis_client
from binmarket_shared.redis_keys import HEARTBEAT_TTL_SECONDS, heartbeat_key

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@router.get("/readiness")
def readiness(db: Session = Depends(get_db)) -> dict:
    checks: dict[str, str] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ONLINE"
    except Exception as exc:
        checks["database"] = f"OFFLINE: {exc}"

    try:
        redis_client.ping()
        checks["redis"] = "ONLINE"
    except Exception as exc:
        checks["redis"] = f"OFFLINE: {exc}"

    for service in ("market-data", "trading-engine"):
        raw = redis_client.get(heartbeat_key(service))
        checks[service] = "ONLINE" if raw else "OFFLINE"

    overall = "ok" if all(v == "ONLINE" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks, "heartbeat_ttl_seconds": HEARTBEAT_TTL_SECONDS}
