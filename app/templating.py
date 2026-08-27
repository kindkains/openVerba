"""Gemeinsamer Rahmen für alle Templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from app.auth import CSRF_COOKIE, cookie_secure, csrf_token_for
from app.models import User

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    *,
    user: User | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Rendert ein Template und sorgt dafür, dass das CSRF-Cookie gesetzt ist."""
    token = csrf_token_for(request)
    payload: dict[str, Any] = {
        "request": request,
        "user": user,
        "csrf_token": token,
    }
    payload.update(context or {})

    response = templates.TemplateResponse(
        request=request, name=template, context=payload, status_code=status_code
    )
    if request.cookies.get(CSRF_COOKIE) != token:
        response.set_cookie(
            CSRF_COOKIE,
            token,
            httponly=False,  # das Formular muss den Wert mitsenden können
            secure=cookie_secure(),
            samesite="lax",
            max_age=60 * 60 * 24 * 14,
        )
    return response
