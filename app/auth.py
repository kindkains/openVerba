"""Login, Sessions, Passwort-Hashing und Reset-Tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import PasswordResetToken, User

SESSION_COOKIE = "openverba_session"
CSRF_COOKIE = "openverba_csrf"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 Tage
RESET_TOKEN_TTL = timedelta(hours=24)


# --- Passwörter ------------------------------------------------------------------


def _prepare(password: str) -> bytes:
    """bcrypt verarbeitet nur 72 Byte.

    Statt zu kürzen (und damit lange Passwörter still zu beschneiden) wird vorher
    gehasht — das ist der von der bcrypt-Bibliothek empfohlene Weg.
    """
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


# --- Sessions --------------------------------------------------------------------


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="openverba-session")


def issue_session(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_session(request: Request) -> int | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid")
    return uid if isinstance(uid, int) else None


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> User | None:
    uid = read_session(request)
    if uid is None:
        return None
    return session.get(User, uid)


# --- CSRF ------------------------------------------------------------------------
#
# Double-Submit: derselbe Zufallswert steckt im Cookie und im Formular. Ein fremdes
# Formular kann das Cookie nicht lesen und den Wert daher nicht mitschicken.


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_token_for(request: Request) -> str:
    return request.cookies.get(CSRF_COOKIE) or new_csrf_token()


def csrf_valid(request: Request, submitted: str | None) -> bool:
    expected = request.cookies.get(CSRF_COOKIE)
    if not expected or not submitted:
        return False
    return hmac.compare_digest(expected, submitted)


# --- Reset-Tokens ----------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_reset_token(session: Session, user: User) -> str:
    """Erzeugt ein Einmal-Token. Im Klartext existiert es nur in der Rückgabe."""
    token = secrets.token_urlsafe(32)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(token),
            expires_at=datetime.now(timezone.utc) + RESET_TOKEN_TTL,
        )
    )
    session.commit()
    return token


def consume_reset_token(session: Session, token: str) -> User | None:
    """Löst ein Token ein. Gibt None zurück, wenn es unbekannt, benutzt oder abgelaufen ist."""
    row = session.execute(
        sa_select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _hash_token(token)
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None:
        return None

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None

    row.used_at = datetime.now(timezone.utc)
    session.commit()
    return session.get(User, row.user_id)


def reset_link(token: str) -> str:
    return f"{get_settings().base_url}/reset/{token}"
