"""Gemeinsame Test-Einrichtung.

Die Umgebungsvariablen müssen stehen, *bevor* app.config zum ersten Mal gelesen wird —
deshalb passiert das hier ganz oben, vor allen App-Importen.
"""

from __future__ import annotations

import os

os.environ["OPENVERBA_SECRET_KEY"] = "test-secret-key-mindestens-16-zeichen"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OPENVERBA_ADMIN_USER"] = "admin"
os.environ["OPENVERBA_ADMIN_PASSWORD"] = "adminpasswort"
os.environ["OPENVERBA_SESSION_SIZE"] = "20"
os.environ["OPENVERBA_TYPO_TOLERANCE"] = "true"
os.environ["SMTP_HOST"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    SIDE_DE,
    SIDE_FOREIGN,
    Language,
    User,
    VocabEntry,
    VocabSet,
    VocabVariant,
)


@pytest.fixture(autouse=True)
def fresh_database():
    """Jeder Test bekommt ein leeres Schema."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def language(db):
    lang = Language(code="en", name="Englisch", active=True)
    db.add(lang)
    db.commit()
    return lang


def make_user(db, username="kind", password="geheim123", is_admin=False):
    user = User(
        username=username,
        email=None,
        password_hash=hash_password(password),
        is_admin=is_admin,
        must_change_password=False,
    )
    db.add(user)
    db.commit()
    return user


def login(client, username="kind", password="geheim123"):
    """Meldet den Client an. Holt vorher das CSRF-Cookie ab."""
    client.get("/login")
    token = client.cookies.get("openverba_csrf")
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response


def csrf(client) -> str:
    return client.cookies.get("openverba_csrf") or ""


def make_entry(db, vocab_set, foreign, german, note=None):
    entry = VocabEntry(set_id=vocab_set.id, note=note)
    db.add(entry)
    db.flush()
    for index, text in enumerate(foreign):
        db.add(
            VocabVariant(
                entry_id=entry.id, side=SIDE_FOREIGN, text=text, is_primary=(index == 0)
            )
        )
    for index, text in enumerate(german):
        db.add(
            VocabVariant(
                entry_id=entry.id, side=SIDE_DE, text=text, is_primary=(index == 0)
            )
        )
    db.commit()
    return entry


def make_set(db, user, language, name="Unit 1"):
    vocab_set = VocabSet(owner_id=user.id, language_id=language.id, name=name)
    db.add(vocab_set)
    db.commit()
    return vocab_set
