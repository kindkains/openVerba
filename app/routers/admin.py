"""Adminbereich: Nutzer, Sprachen, Passwort-Anfragen.

Es gibt keine Selbstregistrierung — Nutzer entstehen ausschließlich hier.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import auth, mailer
from app.db import get_session
from app.deps import require_admin
from app.models import Language, PasswordResetToken, User, VocabEntry, VocabSet
from app.templating import render

router = APIRouter(prefix="/admin")

MIN_PASSWORD_LENGTH = 8


def _entry_counts(session: Session) -> dict[int, int]:
    """Wie viele Vokabeln hängen an welchem Nutzer? Für die Löschwarnung."""
    rows = session.execute(
        select(VocabSet.owner_id, func.count(VocabEntry.id))
        .join(VocabEntry, VocabEntry.set_id == VocabSet.id, isouter=True)
        .where(VocabSet.deleted_at.is_(None))
        .group_by(VocabSet.owner_id)
    ).all()
    return {owner_id: count for owner_id, count in rows}


def _overview(session: Session) -> dict:
    users = list(session.scalars(select(User).order_by(User.username)))
    counts = _entry_counts(session)
    open_requests = list(
        session.scalars(
            select(PasswordResetToken)
            .where(PasswordResetToken.used_at.is_(None))
            .where(PasswordResetToken.expires_at > datetime.now(timezone.utc))
            .order_by(PasswordResetToken.created_at.desc())
        )
    )
    trashed_sets = list(
        session.scalars(
            select(VocabSet)
            .where(VocabSet.deleted_at.is_not(None))
            .order_by(VocabSet.deleted_at.desc())
        )
    )
    return {
        "users": users,
        "entry_counts": counts,
        "open_requests": open_requests,
        "languages": list(session.scalars(select(Language).order_by(Language.name))),
        "trashed_sets": trashed_sets,
    }


@router.get("")
def overview(
    request: Request,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return render(request, "admin.html", _overview(session), user=admin)


@router.post("/users")
def create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(...),
    is_admin: str = Form(""),
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    def fail(message: str):
        context = _overview(session)
        context["error"] = message
        return render(request, "admin.html", context, user=admin, status_code=400)

    if not auth.csrf_valid(request, csrf_token):
        return fail("Sitzung abgelaufen, bitte noch einmal.")

    name = username.strip()
    if not name:
        return fail("Der Benutzername darf nicht leer sein.")
    if len(password) < MIN_PASSWORD_LENGTH:
        return fail(f"Das Passwort braucht mindestens {MIN_PASSWORD_LENGTH} Zeichen.")
    if session.scalar(select(User).where(User.username == name)) is not None:
        return fail(f"Den Benutzer '{name}' gibt es schon.")

    session.add(
        User(
            username=name,
            email=email.strip() or None,  # Kinder haben oft kein Postfach
            password_hash=auth.hash_password(password),
            is_admin=bool(is_admin),
            must_change_password=True,
        )
    )
    session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.get("/users/{user_id}/delete")
def confirm_delete(
    request: Request,
    user_id: int,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    target = session.get(User, user_id)
    if target is None:
        return RedirectResponse("/admin", status_code=303)
    entry_count = _entry_counts(session).get(user_id, 0)
    set_count = session.scalar(
        select(func.count(VocabSet.id)).where(VocabSet.owner_id == user_id)
    )
    return render(
        request,
        "admin_delete.html",
        {"target": target, "entry_count": entry_count, "set_count": set_count or 0},
        user=admin,
    )


@router.post("/users/{user_id}/delete")
def delete_user(
    request: Request,
    user_id: int,
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if not auth.csrf_valid(request, csrf_token):
        return RedirectResponse("/admin", status_code=303)
    target = session.get(User, user_id)
    if target is None:
        return RedirectResponse("/admin", status_code=303)
    if target.id == admin.id:
        context = _overview(session)
        context["error"] = "Du kannst dich nicht selbst löschen."
        return render(request, "admin.html", context, user=admin, status_code=400)

    # Sets, Einträge und Fortschritte gehen per Kaskade mit.
    session.delete(target)
    session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{user_id}/reset")
def make_reset_link(
    request: Request,
    user_id: int,
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if not auth.csrf_valid(request, csrf_token):
        return RedirectResponse("/admin", status_code=303)
    target = session.get(User, user_id)
    if target is None:
        return RedirectResponse("/admin", status_code=303)

    token = auth.create_reset_token(session, target)
    link = auth.reset_link(token)
    mail_sent = bool(target.email) and mailer.send_reset_link(target.email, link)

    context = _overview(session)
    context["generated_link"] = link
    context["generated_for"] = target.username
    context["mail_sent"] = mail_sent
    # Der Link bleibt auch dann sichtbar, wenn die Mail rausging — ein
    # fehlgeschlagener Versand soll keine Sackgasse sein.
    return render(request, "admin.html", context, user=admin)


@router.post("/sets/{set_id}/restore")
def restore_set(
    request: Request,
    set_id: int,
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if not auth.csrf_valid(request, csrf_token):
        return RedirectResponse("/admin", status_code=303)
    vocab_set = session.get(VocabSet, set_id)
    if vocab_set is not None and vocab_set.deleted_at is not None:
        vocab_set.deleted_at = None
        session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/sets/{set_id}/purge")
def purge_set(
    request: Request,
    set_id: int,
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Endgültig löschen geht nur aus dem Papierkorb heraus — nie direkt."""
    if not auth.csrf_valid(request, csrf_token):
        return RedirectResponse("/admin", status_code=303)
    vocab_set = session.get(VocabSet, set_id)
    if vocab_set is not None and vocab_set.deleted_at is not None:
        session.delete(vocab_set)
        session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{user_id}/password")
def set_password(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
    require_change: str = Form(""),
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Passwort direkt setzen — der kurze Weg, wenn das Kind gerade daneben steht."""
    if not auth.csrf_valid(request, csrf_token):
        return RedirectResponse("/admin", status_code=303)
    target = session.get(User, user_id)
    if target is None:
        return RedirectResponse("/admin", status_code=303)

    if len(new_password) < MIN_PASSWORD_LENGTH:
        context = _overview(session)
        context["error"] = (
            f"Das Passwort braucht mindestens {MIN_PASSWORD_LENGTH} Zeichen."
        )
        return render(request, "admin.html", context, user=admin, status_code=400)

    target.password_hash = auth.hash_password(new_password)
    target.must_change_password = bool(require_change)

    # Offene Reset-Links des Nutzers wären sonst ein zweiter, vergessener Zugang.
    now = datetime.now(timezone.utc)
    for token_row in session.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == target.id,
            PasswordResetToken.used_at.is_(None),
        )
    ):
        token_row.used_at = now
    session.commit()

    context = _overview(session)
    context["password_set_for"] = target.username
    return render(request, "admin.html", context, user=admin)


@router.post("/languages")
def add_language(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    csrf_token: str = Form(""),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if not auth.csrf_valid(request, csrf_token):
        return RedirectResponse("/admin", status_code=303)

    code_clean = code.strip().lower()
    name_clean = name.strip()
    if not code_clean or not name_clean:
        context = _overview(session)
        context["error"] = "Kürzel und Name dürfen nicht leer sein."
        return render(request, "admin.html", context, user=admin, status_code=400)
    if session.scalar(select(Language).where(Language.code == code_clean)) is not None:
        context = _overview(session)
        context["error"] = f"Das Kürzel '{code_clean}' gibt es schon."
        return render(request, "admin.html", context, user=admin, status_code=400)

    session.add(Language(code=code_clean, name=name_clean, active=True))
    session.commit()
    return RedirectResponse("/admin", status_code=303)
