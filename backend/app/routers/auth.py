from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.security import COOKIE_NAME, create_access_token, verify_password
from binmarket_shared.config import settings
from binmarket_shared.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    username: str


@router.post("/login", response_model=UserResponse)
@limiter.limit("10/minute")
def login(request: Request, payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserResponse:
    user = db.query(User).filter(User.username == payload.username).one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o contraseña incorrectos")

    from datetime import datetime, timezone

    user.last_login_at = datetime.now(timezone.utc)

    token = create_access_token(user.username)
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax",
        secure=settings.app_env == "production", max_age=60 * 60 * 12,
    )
    return UserResponse(username=user.username)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"status": "logged_out"}


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(username=user.username)
