"""Einstiegspunkt der Anwendung."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.db import engine
from app.routers import admin, auth_routes, learn, vocab
from app.templating import render

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("openverba")

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        log.info("openVerba %s gestartet, Datenbank erreichbar", __version__)
    except SQLAlchemyError as exc:
        # Kein harter Abbruch: Die Anwendung soll sich erholen, sobald die DB da ist.
        log.error(
            "openVerba %s gestartet, Datenbank aber nicht erreichbar: %s",
            __version__,
            exc,
        )
    yield


app = FastAPI(
    title="openVerba",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_routes.router)
app.include_router(admin.router)
app.include_router(vocab.router)
app.include_router(learn.router)


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


@app.get("/")
def index(request: Request) -> RedirectResponse:
    from app.auth import read_session

    if read_session(request) is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/learn", status_code=303)


@app.exception_handler(SQLAlchemyError)
def database_unavailable(request: Request, exc: SQLAlchemyError):
    """Ist die Datenbank weg, gibt es eine lesbare Seite statt eines Stacktrace.

    Sobald die Datenbank zurück ist, funktioniert der nächste Request wieder — die
    Engine baut die Verbindung dank pool_pre_ping selbst neu auf.
    """
    log.error("Datenbankfehler bei %s: %s", request.url.path, exc)
    return render(
        request,
        "error.html",
        {
            "title": "Datenbank nicht erreichbar",
            "message": (
                "openVerba kann die Datenbank gerade nicht erreichen. "
                "Das legt sich meist von selbst — bitte in einem Moment neu laden."
            ),
        },
        status_code=503,
    )


@app.exception_handler(Exception)
def unhandled(request: Request, exc: Exception):
    """Unbehandelte Ausnahmen landen im Log, nie in der Antwort an den Browser."""
    log.exception("Unbehandelte Ausnahme bei %s", request.url.path)
    return render(
        request,
        "error.html",
        {
            "title": "Da ist etwas schiefgegangen",
            "message": "Der Fehler wurde protokolliert. Bitte versuche es noch einmal.",
        },
        status_code=500,
    )


