"""Run once at container startup (see entrypoint.sh), after migrations.

Creates/updates the single admin user from ADMIN_USERNAME/ADMIN_PASSWORD and
ensures the singleton `settings` row exists with safe defaults: PAPER mode,
bot OFF, wizard not completed (section 42: "Modo Safe Start"). Idempotent —
safe to run on every container start/restart.
"""
from __future__ import annotations

from binmarket_shared.config import settings as env_settings
from binmarket_shared.db.base import session_scope
from binmarket_shared.db.models import AppSettings, Strategy, User

from app.core.security import hash_password


def run() -> None:
    with session_scope() as db:
        user = db.query(User).filter(User.username == env_settings.admin_username).one_or_none()
        if user is None:
            db.add(User(username=env_settings.admin_username, password_hash=hash_password(env_settings.admin_password)))
            print(f"[seed] created admin user '{env_settings.admin_username}'")
        else:
            user.password_hash = hash_password(env_settings.admin_password)
            print(f"[seed] updated password for admin user '{env_settings.admin_username}'")

        if db.get(AppSettings, 1) is None:
            db.add(AppSettings(id=1))
            print("[seed] created default settings row (PAPER mode, bot OFF)")

        from binmarket_shared.trading.strategies.registry import STRATEGY_REGISTRY

        for name, cls in STRATEGY_REGISTRY.items():
            if db.query(Strategy).filter(Strategy.name == name).one_or_none() is None:
                instance = cls()
                db.add(Strategy(
                    name=name, version=cls.version, description=cls.description,
                    parameters=instance.params, is_enabled=True,
                ))
                print(f"[seed] registered strategy '{name}'")


if __name__ == "__main__":
    run()
