"""Grunddaten beim Start.

Beide Schritte sind idempotent — der Entrypoint ruft sie bei jedem Start auf.
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import get_settings
from app.db import SessionLocal
from app.models import Language, User

log = logging.getLogger(__name__)

# Vorbefüllung. Weitere Sprachen legt der Admin über die Oberfläche an — dafür ist
# keine Code-Änderung nötig.
DEFAULT_LANGUAGES = [("en", "Englisch"), ("la", "Latein")]


def seed_languages(session: Session) -> None:
    existing = {code for code in session.scalars(select(Language.code))}
    for code, name in DEFAULT_LANGUAGES:
        if code not in existing:
            session.add(Language(code=code, name=name, active=True))
            log.info("Sprache angelegt: %s (%s)", name, code)
    session.commit()


def ensure_admin(session: Session) -> None:
    settings = get_settings()
    username = settings.admin_user.strip()
    if not username:
        return

    existing = session.scalar(select(User).where(User.username == username))
    if existing is not None:
        # Schon da — nichts anfassen, damit ein Neustart nichts überschreibt.
        return

    if not settings.admin_password:
        raise SystemExit(
            "OPENVERBA_ADMIN_PASSWORD fehlt: Der Bootstrap-Admin kann nicht "
            "angelegt werden. Bitte in der .env setzen."
        )

    session.add(
        User(
            username=username,
            email=None,
            password_hash=hash_password(settings.admin_password),
            is_admin=True,
            must_change_password=True,
        )
    )
    session.commit()
    log.info("Bootstrap-Admin '%s' angelegt (Passwortwechsel beim ersten Login)", username)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with SessionLocal() as session:
        seed_languages(session)
        ensure_admin(session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
