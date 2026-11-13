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


def _write_variants(
    entry: VocabEntry, foreign_variants: list[str], german_variants: list[str]
) -> None:
    """Setzt die Varianten eines Eintrags neu. Die erste je Seite ist die primäre.

    Der Lernfortschritt hängt am Eintrag, nicht an den Varianten — eine Korrektur
    lässt die Boxen also unangetastet.
    """
    entry.variants = [
        VocabVariant(side=SIDE_FOREIGN, text=text, is_primary=(index == 0))
        for index, text in enumerate(foreign_variants)
    ] + [
        VocabVariant(side=SIDE_DE, text=text, is_primary=(index == 0))
        for index, text in enumerate(german_variants)
    ]


def _language_choices(session: Session, current: Language | None = None) -> list[Language]:
    """Aktive Sprachen; die aktuelle bleibt wählbar, auch wenn sie deaktiviert wurde."""
    languages = list(
        session.scalars(select(Language).where(Language.active).order_by(Language.name))
    )
    if current is not None and current not in languages:
        languages.append(current)
    return languages


def _target_sets(session: Session, owner_id: int) -> list[VocabSet]:
    """Sets, in die ein Eintrag verschoben werden darf: alle aktiven Sets des Besitzers.

    Bewusst nur innerhalb desselben Besitzers — auch der Admin schiebt keine Vokabeln
    von einem Benutzer zum anderen.
    """
    return list(
        session.scalars(
            select(VocabSet)
            .join(Language, VocabSet.language_id == Language.id)
            .where(VocabSet.owner_id == owner_id, VocabSet.deleted_at.is_(None))
            .order_by(Language.name, VocabSet.name)
        )
    )


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
    languages = _language_choices(session)
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


@router.get("/sets/{set_id}/edit")
def edit_set_form(
    request: Request,
    set_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    vocab_set = _editable_set(session, user, set_id)
    if vocab_set is None:
        return RedirectResponse("/sets", status_code=303)
    return render(
        request,
        "set_edit.html",
        {
            "vocab_set": vocab_set,
            "languages": _language_choices(session, vocab_set.language),
            "form": {
                "name": vocab_set.name,
                "language_id": vocab_set.language_id,
                "description": vocab_set.description or "",
            },
        },
        user=user,
    )


@router.post("/sets/{set_id}/edit")
def edit_set(
    request: Request,
    set_id: int,
    name: str = Form(""),
    language_id: int = Form(...),
    description: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    vocab_set = _editable_set(session, user, set_id)
    if vocab_set is None:
        return RedirectResponse("/sets", status_code=303)
    languages = _language_choices(session, vocab_set.language)

    def fail(message: str):
        return render(
            request,
            "set_edit.html",
            {
                "vocab_set": vocab_set,
                "languages": languages,
                "error": message,
                "form": {
                    "name": name,
                    "language_id": language_id,
                    "description": description,
                },
            },
            user=user,
            status_code=400,
        )

    if not auth.csrf_valid(request, csrf_token):
        return fail("Sitzung abgelaufen, bitte noch einmal.")
    if not name.strip():
        return fail("Der Name darf nicht leer sein.")
    language = next((lang for lang in languages if lang.id == language_id), None)
    if language is None:
        return fail("Diese Sprache gibt es nicht.")

    # Die Sprache darf auch bei gefülltem Set wechseln: Vokabeln und Lernfortschritt
    # hängen am Eintrag und ziehen einfach mit — typisch für "falsche Sprache erwischt".
    vocab_set.name = name.strip()
    vocab_set.language_id = language.id
    vocab_set.description = description.strip() or None
    session.commit()
    return RedirectResponse(f"/sets/{set_id}", status_code=303)


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
    _write_variants(entry, foreign_variants, german_variants)
    session.add(entry)
    session.commit()
    return RedirectResponse(f"/sets/{set_id}", status_code=303)


def _editable_entry(
    session: Session, user: User, entry_id: int
) -> tuple[VocabEntry, VocabSet] | tuple[None, None]:
    entry = session.get(VocabEntry, entry_id)
    if entry is None:
        return None, None
    vocab_set = _editable_set(session, user, entry.set_id)
    if vocab_set is None:
        return None, None
    return entry, vocab_set


@router.get("/entries/{entry_id}/edit")
def edit_entry_form(
    request: Request,
    entry_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    entry, vocab_set = _editable_entry(session, user, entry_id)
    if entry is None:
        return RedirectResponse("/sets", status_code=303)
    return render(
        request,
        "entry_edit.html",
        {
            "entry": entry,
            "vocab_set": vocab_set,
            "target_sets": _target_sets(session, vocab_set.owner_id),
            "form": {
                "foreign": "; ".join(v.text for v in entry.side(SIDE_FOREIGN)),
                "german": "; ".join(v.text for v in entry.side(SIDE_DE)),
                "note": entry.note or "",
                "set_id": vocab_set.id,
            },
        },
        user=user,
    )


@router.post("/entries/{entry_id}/edit")
def edit_entry(
    request: Request,
    entry_id: int,
    foreign: str = Form(""),
    german: str = Form(""),
    note: str = Form(""),
    set_id: int | None = Form(None),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    entry, vocab_set = _editable_entry(session, user, entry_id)
    if entry is None:
        return RedirectResponse("/sets", status_code=303)
    target_sets = _target_sets(session, vocab_set.owner_id)

    def fail(message: str):
        return render(
            request,
            "entry_edit.html",
            {
                "entry": entry,
                "vocab_set": vocab_set,
                "target_sets": target_sets,
                "error": message,
                "form": {
                    "foreign": foreign,
                    "german": german,
                    "note": note,
                    "set_id": set_id or vocab_set.id,
                },
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

    target = vocab_set
    if set_id is not None and set_id != vocab_set.id:
        target = next((s for s in target_sets if s.id == set_id), None)
        if target is None:
            return fail("In dieses Set lässt sich die Vokabel nicht verschieben.")

    _write_variants(entry, foreign_variants, german_variants)
    entry.note = note.strip() or None
    entry.vocab_set = target
    session.commit()
    # Zurück dorthin, wo man herkam — dort fehlt die Vokabel ggf. jetzt, das ist gewollt.
    return RedirectResponse(f"/sets/{vocab_set.id}", status_code=303)


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
