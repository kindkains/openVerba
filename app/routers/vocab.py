"""Vokabelsets und Einträge.

Jeder pflegt seinen eigenen Bestand. Der Bestand wächst mit dem Unterricht mit: Das Kind
trägt neue Wörter ein, sobald sie drankommen.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth
from app.db import get_session
from app.deps import require_user
from app.models import (
    SIDE_DE,
    SIDE_FOREIGN,
    Language,
    User,
    VocabEntry,
    VocabSet,
    VocabVariant,
)
from app.templating import render

router = APIRouter()

# Mehrere gültige Formulierungen werden mit Semikolon getrennt: "Hund; Rüde"
VARIANT_SEPARATOR = ";"


def parse_variants(raw: str) -> list[str]:
    """Zerlegt die Eingabe in Varianten, ohne Duplikate und ohne Leereinträge."""
    seen: list[str] = []
    for part in raw.split(VARIANT_SEPARATOR):
        text = part.strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _editable_set(session: Session, user: User, set_id: int) -> VocabSet | None:
    """Das Set, sofern der Nutzer es bearbeiten darf: der Besitzer — oder der Admin,
    der bei allen Nutzern nachpflegen kann."""
    vocab_set = session.get(VocabSet, set_id)
    if vocab_set is None or vocab_set.deleted_at is not None:
        # Was im Papierkorb liegt, wird nur über den Adminbereich angefasst.
        return None
    if vocab_set.owner_id != user.id and not user.is_admin:
        return None
    return vocab_set


@router.get("/sets")
def list_sets(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    # Der Admin sieht die Sets aller Nutzer, alle anderen nur die eigenen.
    query = (
        select(VocabSet)
        .join(User, VocabSet.owner_id == User.id)
        .where(VocabSet.deleted_at.is_(None))
    )
    if user.is_admin:
        query = query.order_by(User.username, VocabSet.name)
    else:
        query = query.where(VocabSet.owner_id == user.id).order_by(VocabSet.name)
    sets = list(session.scalars(query))
    languages = list(
        session.scalars(select(Language).where(Language.active).order_by(Language.name))
    )
    counts = {s.id: len(s.entries) for s in sets}
    return render(
        request,
        "sets.html",
        {"sets": sets, "languages": languages, "counts": counts},
        user=user,
    )


@router.post("/sets")
def create_set(
    request: Request,
    name: str = Form(...),
    language_id: int = Form(...),
    description: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not auth.csrf_valid(request, csrf_token) or not name.strip():
        return RedirectResponse("/sets", status_code=303)

    vocab_set = VocabSet(
        owner_id=user.id,
        language_id=language_id,
        name=name.strip(),
        description=description.strip() or None,
    )
    session.add(vocab_set)
    session.commit()
    return RedirectResponse(f"/sets/{vocab_set.id}", status_code=303)


@router.post("/sets/{set_id}/delete")
def delete_set(
    request: Request,
    set_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if auth.csrf_valid(request, csrf_token):
        vocab_set = _editable_set(session, user, set_id)
        if vocab_set is not None:
            # Nur in den Papierkorb — endgültig löschen kann der Admin, und ein
            # versehentlich gelöschtes Set lässt sich so wiederherstellen.
            vocab_set.deleted_at = datetime.now(timezone.utc)
            session.commit()
    return RedirectResponse("/sets", status_code=303)


@router.get("/sets/{set_id}")
def set_detail(
    request: Request,
    set_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    vocab_set = _editable_set(session, user, set_id)
    if vocab_set is None:
        return RedirectResponse("/sets", status_code=303)
    entries = sorted(vocab_set.entries, key=lambda e: e.id or 0, reverse=True)
    return render(
        request,
        "set_detail.html",
        {
            "vocab_set": vocab_set,
            "entries": entries,
            "side_foreign": SIDE_FOREIGN,
            "side_de": SIDE_DE,
        },
        user=user,
    )


@router.post("/sets/{set_id}/entries")
def add_entry(
    request: Request,
    set_id: int,
    foreign: str = Form(...),
    german: str = Form(...),
    note: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    vocab_set = _editable_set(session, user, set_id)
    if vocab_set is None:
        return RedirectResponse("/sets", status_code=303)

    def fail(message: str):
        entries = sorted(vocab_set.entries, key=lambda e: e.id or 0, reverse=True)
        return render(
            request,
            "set_detail.html",
            {
                "vocab_set": vocab_set,
                "entries": entries,
                "side_foreign": SIDE_FOREIGN,
                "side_de": SIDE_DE,
                "error": message,
                "form": {"foreign": foreign, "german": german, "note": note},
            },
            user=user,
            status_code=400,
        )

    if not auth.csrf_valid(request, csrf_token):
        return fail("Sitzung abgelaufen, bitte noch einmal.")

    foreign_variants = parse_variants(foreign)
    german_variants = parse_variants(german)
    if not foreign_variants:
        return fail("Die Fremdsprachen-Seite darf nicht leer sein.")
    if not german_variants:
        return fail("Die deutsche Seite darf nicht leer sein.")

    entry = VocabEntry(set_id=vocab_set.id, note=note.strip() or None)
    session.add(entry)
    session.flush()

    for index, text in enumerate(foreign_variants):
        session.add(
            VocabVariant(
                entry_id=entry.id, side=SIDE_FOREIGN, text=text, is_primary=(index == 0)
            )
        )
    for index, text in enumerate(german_variants):
        session.add(
            VocabVariant(
                entry_id=entry.id, side=SIDE_DE, text=text, is_primary=(index == 0)
            )
        )
    session.commit()
    return RedirectResponse(f"/sets/{set_id}", status_code=303)


@router.post("/entries/{entry_id}/delete")
def delete_entry(
    request: Request,
    entry_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    entry = session.get(VocabEntry, entry_id)
    if entry is None:
        return RedirectResponse("/sets", status_code=303)
    set_id = entry.set_id
    if auth.csrf_valid(request, csrf_token) and _editable_set(session, user, set_id):
        session.delete(entry)
        session.commit()
    return RedirectResponse(f"/sets/{set_id}", status_code=303)
