"""Cookie-Absicherung.

Das Secure-Flag hängt an `OPENVERBA_BASE_URL`: hinter TLS wird es gesetzt, bei einer
lokalen Installation auf http bleibt es weg — sonst käme das Cookie dort nie an.
"""

from __future__ import annotations

from app import auth
from app.config import get_settings
from tests.conftest import login, make_user


def _mit_base_url(monkeypatch, url: str):
    monkeypatch.setenv("OPENVERBA_BASE_URL", url)
    get_settings.cache_clear()


class TestSecureFlag:
    def test_bei_http_kein_secure(self):
        # Die Testumgebung läuft auf http://localhost:8080
        assert auth.cookie_secure() is False

    def test_bei_https_mit_secure(self, monkeypatch):
        _mit_base_url(monkeypatch, "https://openverba.example.org")
        try:
            assert auth.cookie_secure() is True
        finally:
            get_settings.cache_clear()

    def test_trailing_slash_stoert_nicht(self, monkeypatch):
        _mit_base_url(monkeypatch, "https://openverba.example.org/")
        try:
            assert auth.cookie_secure() is True
        finally:
            get_settings.cache_clear()


class TestGesetzteCookies:
    def test_csrf_cookie_ohne_https_ohne_secure(self, client):
        antwort = client.get("/login")
        gesetzt = antwort.headers.get("set-cookie", "")
        assert "openverba_csrf" in gesetzt
        assert "Secure" not in gesetzt

    def test_csrf_cookie_mit_https_traegt_secure(self, client, monkeypatch):
        _mit_base_url(monkeypatch, "https://openverba.example.org")
        try:
            antwort = client.get("/login")
            gesetzt = antwort.headers.get("set-cookie", "")
            assert "openverba_csrf" in gesetzt
            assert "Secure" in gesetzt
        finally:
            get_settings.cache_clear()

    def test_session_cookie_ist_httponly(self, client, db):
        make_user(db)
        antwort = login(client)
        gesetzt = antwort.headers.get("set-cookie", "")
        assert "openverba_session" in gesetzt
        assert "HttpOnly" in gesetzt
