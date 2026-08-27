"""Leitner-Boxen: Boxwechsel, Fälligkeit und Auswahl der nächsten Lerneinheit.

Bewusst kein SM-2/Anki: Bei mehreren Auszeittagen soll kein Rückstau entstehen. Die
Auswahl füllt immer genau eine Einheit auf, egal wie viel überfällig ist.

Reine Logik auf einfachen Datenklassen — ohne Datenbank und ohne HTTP testbar.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

MIN_BOX = 1
MAX_BOX = 5

# Box -> Abstand bis zur nächsten Abfrage
BOX_INTERVALS: dict[int, timedelta] = {
    1: timedelta(0),
    2: timedelta(days=1),
    3: timedelta(days=3),
    4: timedelta(days=7),
    5: timedelta(days=21),
}


def next_box(box: int, correct: bool) -> int:
    """Richtig: eine Box hoch (höchstens 5). Falsch: zurück auf Box 1."""
    if not correct:
        return MIN_BOX
    return min(box + 1, MAX_BOX)


def due_after(box: int, now: datetime) -> datetime:
    """Fälligkeitszeitpunkt für eine Box."""
    box = max(MIN_BOX, min(box, MAX_BOX))
    return now + BOX_INTERVALS[box]


@dataclass(frozen=True)
class Candidate:
    """Eine mögliche Abfrage: eine Vokabel in einer Richtung.

    `box is None` bedeutet: für diesen Nutzer noch nie gesehen.
    """

    entry_id: int
    direction: str
    box: int | None = None
    due_at: datetime | None = None

    @property
    def seen(self) -> bool:
        return self.box is not None

    def is_due(self, now: datetime) -> bool:
        return self.seen and self.due_at is not None and self.due_at <= now


def select(
    candidates: list[Candidate],
    size: int,
    now: datetime,
    rng: random.Random | None = None,
) -> list[Candidate]:
    """Stellt eine Lerneinheit zusammen.

    Reihenfolge der Auffüllung:

    1. fällige Vokabeln, niedrigste Box zuerst
    2. noch nie gesehene Vokabeln
    3. der Rest, zufällig

    Dadurch bekommt niemand nach drei Tagen Pause 400 überfällige Karten vorgesetzt,
    sondern eine normale Einheit.
    """
    if size <= 0 or not candidates:
        return []
    rng = rng or random.Random()

    due: list[Candidate] = []
    unseen: list[Candidate] = []
    rest: list[Candidate] = []
    for candidate in candidates:
        if candidate.is_due(now):
            due.append(candidate)
        elif not candidate.seen:
            unseen.append(candidate)
        else:
            rest.append(candidate)

    # Niedrigste Box zuerst, bei Gleichstand das am längsten Überfällige.
    due.sort(key=lambda c: (c.box or MIN_BOX, c.due_at or now))
    rng.shuffle(unseen)
    rng.shuffle(rest)

    selection = due[:size]
    if len(selection) < size:
        selection += unseen[: size - len(selection)]
    if len(selection) < size:
        selection += rest[: size - len(selection)]
    return selection
