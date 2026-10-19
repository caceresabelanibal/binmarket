from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


@router.get("/login")
def login_page() -> FileResponse:
    return FileResponse(_TEMPLATES_DIR / "login.html")


@router.get("/")
def dashboard_page() -> FileResponse:
    return FileResponse(_TEMPLATES_DIR / "dashboard.html")
