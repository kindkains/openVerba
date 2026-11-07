"""Der Lernablauf.

Eine Lerneinheit wird beim Start zusammengestellt und dann abgearbeitet. Der Zustand
der laufenden Einheit steckt in einem signierten Cookie — so braucht openVerba keine
serverseitige Sitzungshaltung und läuft auch hinter mehreren Prozessen.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth, checker, leitner
from app.config import get_settings
from app.db import get_session
from app.deps import require_user
from app.models import (
    DIRECTION_BW,
    DIRECTION_FW,
    SIDE_DE,
    SIDE_FOREIGN,
    Language,
    LearnProgress,
    User,
    VocabEntry,
    VocabSet,
)
from app.templating import render

router = APIRouter(prefix="/learn")

ROUND_COOKIE = "openverba_round"

SCOPE_SET = "set"
SCOPE_SETS = "sets"  # die im Startformular angehakten Sets
SCOPE_LANGUAGE = "language"
SCOPE_GLOBAL = "global"

MODE_FW = "fw"
MODE_BW = "bw"
MODE_MIXED = "mixed"

# Obergrenze pro Einheit: Der Rundenzustand steckt in einem Cookie, und Browser
# schneiden Cookies oberhalb von ~4 KB kommentarlos ab.
MAX_ROUND_SIZE = 200


def _round_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="openverba-round")


def _read_round(request: Request) -> dict | None:
    raw = request.cookies.get(ROUND_COOKIE)
    if not raw:
        return None
    try:
        data = _round_serializer().loads(raw)
    except BadSignature:
        return None
    return data if isinstance(data, dict) and data.get("items") else None


def _store_round(response, data: dict) -> None:
    response.set_cookie(
        ROUND_COOKIE,
        _round_serializer().dumps(data),
        httponly=True,
        secure=auth.cookie_secure(),
        samesite="lax",
        max_age=60 * 60 * 6,
    )


def _entries_for_scope(
    session: Session, user: User, scope: str, scope_ids: list[int]
) -> list[VocabEntry]:
    query = (
        select(VocabEntry)
        .join(VocabSet, VocabEntry.set_id == VocabSet.id)
        .where(VocabSet.deleted_at.is_(None))
    )
    scope_id = scope_ids[0]
    if scope in (SCOPE_SET, SCOPE_SETS):
        query = query.where(VocabSet.id.in_(scope_ids), VocabSet.owner_id == user.id)
    elif scope == SCOPE_LANGUAGE:
        query = query.where(
            VocabSet.language_id == scope_id, VocabSet.owner_id == user.id
        )
    else:  # globaler Pool: alle Vokabeln aller Nutzer in dieser Sprache
        query = query.where(VocabSet.language_id == scope_id)
    return list(session.scalars(query))


def _directions(mode: str, rng: random.Random) -> list[str]:
    if mode == MODE_FW:
        return [DIRECTION_FW]
    if mode == MODE_BW:
        return [DIRECTION_BW]
    return [rng.choice([DIRECTION_FW, DIRECTION_BW])]


def _progress_map(
    session: Session, user: User, entry_ids: list[int]
) -> dict[tuple[int, str], LearnProgress]:
    if not entry_ids:
        return {}
    rows = session.scalars(
        select(LearnProgress).where(
            LearnProgress.user_id == user.id, LearnProgress.entry_id.in_(entry_ids)
        )
    )
    return {(row.entry_id, row.direction): row for row in rows}


@router.get("")
def start_form(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    sets = list(
        session.scalars(
            select(VocabSet)
            .where(VocabSet.owner_id == user.id, VocabSet.deleted_at.is_(None))
            .order_by(VocabSet.name)
        )
    )
    languages = list(
        session.scalars(select(Language).where(Language.active).order_by(Language.name))
    )
    return render(
        request,
        "learn_start.html",
        {
            "sets": sets,
            "languages": languages,
            "session_size": get_settings().session_size,
            "max_round_size": MAX_ROUND_SIZE,
        },
        user=user,
    )


@router.post("/start")
def start(
    request: Request,
    source: str = Form(SCOPE_SETS),
    set_ids: list[str] = Form([], alias="sets"),
    mode: str = Form(MODE_MIXED),
    size: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    if not auth.csrf_valid(request, csrf_token):
        return RedirectResponse("/learn", status_code=303)

    # source ist entweder "sets" (dann zählen die angehakten Sets) oder kommt als
    # "scope:id", z.B. "set:3" oder "global:1"
    if source == SCOPE_SETS:
        scope = SCOPE_SETS
        scope_ids = sorted({int(s) for s in set_ids if s.isdigit()})
        if not scope_ids:
            return render(request, "learn_empty.html", {"no_sets_ticked": True}, user=user)
    else:
        scope, _, raw_id = source.partition(":")
        if not raw_id.isdigit() or scope not in (SCOPE_SET, SCOPE_LANGUAGE, SCOPE_GLOBAL):
            return RedirectResponse("/learn", status_code=303)
        scope_ids = [int(raw_id)]

    entries = _entries_for_scope(session, user, scope, scope_ids)
    if not entries:
        return render(
            request,
            "learn_empty.html",
            {},
            user=user,
        )

    rng = random.Random()
    entry_ids = [e.id for e in entries]
    progress = _progress_map(session, user, entry_ids)
    now = datetime.now(timezone.utc)

    candidates: list[leitner.Candidate] = []
    for entry in entries:
        for direction in _directions(mode, rng):
            row = progress.get((entry.id, direction))
            due_at = row.due_at if row else None
            if due_at is not None and due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            candidates.append(
                leitner.Candidate(
                    entry_id=entry.id,
                    direction=direction,
                    box=row.box if row else None,
                    due_at=due_at,
                )
            )

    # Ausgewählte Sets werden immer komplett abgefragt (bis MAX_ROUND_SIZE). Die
    # Wunschgröße zählt nur beim Mischen — alle eigenen Sets einer Sprache oder der
    # gemeinsame Pool.
    if scope in (SCOPE_SET, SCOPE_SETS):
        wanted = len(candidates)
    elif size.strip().isdigit():
        wanted = int(size.strip())
    else:
        wanted = get_settings().session_size
    wanted = max(1, min(wanted, MAX_ROUND_SIZE))

    chosen = leitner.select(candidates, wanted, now, rng)
    if not chosen:
        return render(request, "learn_empty.html", {}, user=user)

    data = {
        "items": [[c.entry_id, c.direction] for c in chosen],
        "i": 0,
        "ok": 0,
        "bad": 0,
    }
    response = RedirectResponse("/learn/question", status_code=303)
    _store_round(response, data)
    return response


@router.get("/question")
def question(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    data = _read_round(request)
    if data is None:
        return RedirectResponse("/learn", status_code=303)
    if data["i"] >= len(data["items"]):
        return RedirectResponse("/learn/done", status_code=303)

    entry_id, direction = data["items"][data["i"]]
    entry = session.get(VocabEntry, entry_id)
    if entry is None:
        # Vokabel wurde zwischenzeitlich gelöscht — überspringen.
        data["i"] += 1
        response = RedirectResponse("/learn/question", status_code=303)
        _store_round(response, data)
        return response

    ask_side = SIDE_FOREIGN if direction == DIRECTION_FW else SIDE_DE
    return render(
        request,
        "learn_question.html",
        {
            "prompt": entry.prompt(ask_side),
            "direction": direction,
            "position": data["i"] + 1,
            "total": len(data["items"]),
            "correct": data["ok"],
            "wrong": data["bad"],
        },
        user=user,
    )


@router.post("/answer")
def answer(
    request: Request,
    given: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    data = _read_round(request)
    if data is None or not auth.csrf_valid(request, csrf_token):
        return RedirectResponse("/learn", status_code=303)
    if data["i"] >= len(data["items"]):
        return RedirectResponse("/learn/done", status_code=303)

    entry_id, direction = data["items"][data["i"]]
    entry = session.get(VocabEntry, entry_id)
    if entry is None:
        data["i"] += 1
        response = RedirectResponse("/learn/question", status_code=303)
        _store_round(response, data)
        return response

    ask_side = SIDE_FOREIGN if direction == DIRECTION_FW else SIDE_DE
    answer_side = SIDE_DE if direction == DIRECTION_FW else SIDE_FOREIGN
    targets = [v.text for v in entry.side(answer_side)]

    result = checker.check(
        given, targets, typo_tolerance=get_settings().typo_tolerance
    )

    now = datetime.now(timezone.utc)
    row = session.get(LearnProgress, (user.id, entry_id, direction))
    if row is None:
        # Zähler ausdrücklich auf 0: Die Spaltendefaults greifen erst beim INSERT,
        # gerechnet wird aber schon vorher.
        row = LearnProgress(
            user_id=user.id,
            entry_id=entry_id,
            direction=direction,
            box=1,
            due_at=now,
            correct_count=0,
            wrong_count=0,
        )
        session.add(row)

    row.box = leitner.next_box(row.box, result.correct)
    row.due_at = leitner.due_after(row.box, now)
    row.last_seen_at = now
    if result.correct:
        row.correct_count += 1
        data["ok"] += 1
    else:
        row.wrong_count += 1
        data["bad"] += 1
    session.commit()

    data["i"] += 1
    response = render(
        request,
        "learn_feedback.html",
        {
            "prompt": entry.prompt(ask_side),
            "given": given,
            "result": result,
            "note": entry.note,
            "box": row.box,
            "position": data["i"],
            "total": len(data["items"]),
            "finished": data["i"] >= len(data["items"]),
        },
        user=user,
    )
    _store_round(response, data)
    return response


@router.get("/done")
def done(request: Request, user: User = Depends(require_user)):
    data = _read_round(request)
    if data is None:
        return RedirectResponse("/learn", status_code=303)
    response = render(
        request,
        "learn_done.html",
        {"correct": data["ok"], "wrong": data["bad"], "total": len(data["items"])},
        user=user,
    )
    response.delete_cookie(ROUND_COOKIE)
    return response
