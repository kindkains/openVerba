"""Wiederkehrende Abhängigkeiten der Router."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import read_session
from app.db import get_session
from app.models import User


def _redirect(target: str) -> HTTPException:
    """Umleitung als Ausnahme — so kann eine Dependency den Request abbrechen."""
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER, headers={"Location": target}
    )


def require_user(
    request: Request, session: Session = Depends(get_session)
) -> User:
    uid = read_session(request)
    if uid is None:
        raise _redirect("/login")
    user = session.get(User, uid)
    if user is None:
        raise _redirect("/login")
    # Erstes Login mit dem Bootstrap-Passwort: erst wechseln, dann weiter.
    if user.must_change_password and request.url.path not in ("/password", "/logout"):
        raise _redirect("/password")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dieser Bereich ist dem Admin vorbehalten.",
        )
    return user
