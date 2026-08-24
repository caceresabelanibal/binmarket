from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from binmarket_shared.db.base import get_session
from binmarket_shared.db.models import AppSettings, User

from .security import COOKIE_NAME, decode_access_token

get_db = get_session


def get_current_user(
    db: Session = Depends(get_db),
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    username = decode_access_token(token)
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
    user = db.query(User).filter(User.username == username).one_or_none()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario no encontrado")
    return user


def get_app_settings(db: Session = Depends(get_db)) -> AppSettings:
    settings_row = db.get(AppSettings, 1)
    if settings_row is None:
        settings_row = AppSettings(id=1)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row
