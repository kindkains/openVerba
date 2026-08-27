"""Login, Logout, Passwortwechsel und Reset-Ablauf."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth, mailer
from app.db import get_session
from app.deps import require_user
from app.models import User
from app.templating import render

log = logging.getLogger(__name__)
router = APIRouter()

MIN_PASSWORD_LENGTH = 8


@router.get("/login")
def login_form(request: Request):
    if auth.read_session(request) is not None:
        return RedirectResponse("/learn", status_code=303)
    return render(request, "login.html", {})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
    session: Session = Depends(get_session),
):
    if not auth.csrf_valid(request, csrf_token):
        return render(
            request, "login.html", {"error": "Sitzung abgelaufen, bitte noch einmal."},
            status_code=400,
        )

    user = session.scalar(select(User).where(User.username == username.strip()))
    if user is None or not auth.verify_password(password, user.password_hash):
        # Bewusst dieselbe Meldung für "gibt es nicht" und "falsches Passwort".
        return render(
            request,
            "login.html",
            {"error": "Benutzername oder Passwort stimmt nicht.", "username": username},
            status_code=401,
        )

    response = RedirectResponse("/learn", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.issue_session(user.id),
        httponly=True,
        samesite="lax",
        max_age=auth.SESSION_MAX_AGE,
    )
    return response


@router.get("/logout")
@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response


@router.get("/password")
def password_form(request: Request, user: User = Depends(require_user)):
    return render(request, "password.html", {"forced": user.must_change_password}, user=user)


@router.post("/password")
def password_change(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(...),
    repeat_password: str = Form(...),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    def fail(message: str):
        return render(
            request,
            "password.html",
            {"error": message, "forced": user.must_change_password},
            user=user,
            status_code=400,
        )

    if not auth.csrf_valid(request, csrf_token):
        return fail("Sitzung abgelaufen, bitte noch einmal.")
    if not auth.verify_password(current_password, user.password_hash):
        return fail("Das aktuelle Passwort stimmt nicht.")
    if new_password != repeat_password:
        return fail("Die beiden neuen Passwörter sind nicht gleich.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return fail(f"Das neue Passwort braucht mindestens {MIN_PASSWORD_LENGTH} Zeichen.")

    user.password_hash = auth.hash_password(new_password)
    user.must_change_password = False
    session.add(user)
    session.commit()
    return RedirectResponse("/learn", status_code=303)


@router.get("/forgot")
def forgot_form(request: Request):
    return render(request, "forgot.html", {})


@router.post("/forgot")
def forgot(
    request: Request,
    username: str = Form(...),
    csrf_token: str = Form(""),
    session: Session = Depends(get_session),
):
    if not auth.csrf_valid(request, csrf_token):
        return render(
            request, "forgot.html", {"error": "Sitzung abgelaufen, bitte noch einmal."},
            status_code=400,
        )

    user = session.scalar(select(User).where(User.username == username.strip()))
    if user is not None:
        token = auth.create_reset_token(session, user)
        if user.email:
            mailer.send_reset_link(user.email, auth.reset_link(token))

    # Immer dieselbe Antwort — sonst verrät die Seite, welche Namen es gibt.
    return render(request, "forgot.html", {"done": True})


@router.get("/reset/{token}")
def reset_form(request: Request, token: str):
    return render(request, "reset.html", {"token": token})


@router.post("/reset/{token}")
def reset(
    request: Request,
    token: str,
    new_password: str = Form(...),
    repeat_password: str = Form(...),
    csrf_token: str = Form(""),
    session: Session = Depends(get_session),
):
    def fail(message: str):
        return render(
            request, "reset.html", {"token": token, "error": message}, status_code=400
        )

    if not auth.csrf_valid(request, csrf_token):
        return fail("Sitzung abgelaufen, bitte noch einmal.")
    if new_password != repeat_password:
        return fail("Die beiden Passwörter sind nicht gleich.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return fail(f"Das Passwort braucht mindestens {MIN_PASSWORD_LENGTH} Zeichen.")

    user = auth.consume_reset_token(session, token)
    if user is None:
        return fail("Dieser Link ist abgelaufen oder wurde schon benutzt.")

    user.password_hash = auth.hash_password(new_password)
    user.must_change_password = False
    session.add(user)
    session.commit()
    return render(request, "reset.html", {"done": True})
