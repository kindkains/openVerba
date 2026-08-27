"""Antwortvergleich.

Rein funktional: dieses Modul kennt weder Datenbank noch HTTP. Es bekommt eine Eingabe
und die gültigen Varianten der Zielseite und sagt, ob das passt.

Die Normalisierung folgt der Design-Spec, Abschnitt 4 "Antwortprüfung".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Artikel und Infinitiv-Marker dürfen fehlen oder dastehen.
_OPTIONAL_LEADING = frozenset(
    {"der", "die", "das", "den", "dem", "ein", "eine", "to", "the"}
)

_WHITESPACE = re.compile(r"\s+")
_PARENS = re.compile(r"\(([^)]*)\)")


def normalize(text: str) -> str:
    """Schritte 1 und 2: Groß-/Kleinschreibung, Leerzeichen, diakritische Zeichen.

    `amāre` und `  Amare ` werden beide zu `amare`.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _WHITESPACE.sub(" ", text).strip().lower()
    return text


def _strip_leading_article(text: str) -> str:
    head, _, rest = text.partition(" ")
    if rest and head in _OPTIONAL_LEADING:
        return rest
    return text


def forms(text: str) -> frozenset[str]:
    """Alle Schreibweisen, die für denselben Begriff durchgehen sollen.

    Deckt Schritt 3 (optionaler Artikel) und Schritt 4 (optionaler Klammerzusatz) ab.
    `(sich) freuen` liefert unter anderem `sich freuen` und `freuen`.
    """
    base = normalize(text)
    if not base:
        return frozenset()

    with_parens = _WHITESPACE.sub(" ", _PARENS.sub(r"\1", base)).strip()
    without_parens = _WHITESPACE.sub(" ", _PARENS.sub("", base)).strip()

    result: set[str] = set()
    for candidate in (with_parens, without_parens):
        if not candidate:
            continue
        result.add(candidate)
        result.add(_strip_leading_article(candidate))
    return frozenset(f for f in result if f)


def _within_one_edit(a: str, b: str) -> bool:
    """Levenshtein-Distanz höchstens 1 — ohne die volle Matrix zu bauen."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False

    if la == lb:
        diffs = 0
        for ca, cb in zip(a, b):
            if ca != cb:
                diffs += 1
                if diffs > 1:
                    return False
        return True

    # Genau ein Zeichen Unterschied in der Länge: einmal überspringen erlaubt.
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    i = j = 0
    skipped = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        if skipped:
            return False
        skipped = True
        j += 1
    return True


@dataclass(frozen=True)
class CheckResult:
    correct: bool
    # Richtig, aber mit Tippfehler — die Oberfläche zeigt dann die saubere Schreibweise.
    typo: bool = False
    matched: str | None = None
    accepted: tuple[str, ...] = field(default_factory=tuple)


def check(
    answer: str,
    targets: list[str],
    *,
    typo_tolerance: bool = True,
    min_length_for_typo: int = 5,
) -> CheckResult:
    """Vergleicht die Eingabe gegen **jede** Variante der Zielseite.

    Eine Übereinstimmung genügt (Schritt 5). Schlägt der exakte Vergleich fehl, greift
    optional die Tippfehler-Toleranz (Schritt 6).
    """
    accepted = tuple(t for t in targets if t and t.strip())
    answer_forms = forms(answer)
    if not answer_forms or not accepted:
        return CheckResult(correct=False, accepted=accepted)

    target_forms = [(target, forms(target)) for target in accepted]

    # Schritt 5: exakte Übereinstimmung nach Normalisierung.
    for target, candidates in target_forms:
        if answer_forms & candidates:
            return CheckResult(correct=True, matched=target, accepted=accepted)

    # Schritt 6: ein Tippfehler wird verziehen, ab 5 Zeichen normalisierter Länge.
    if typo_tolerance:
        for target, candidates in target_forms:
            for candidate in candidates:
                if len(candidate) < min_length_for_typo:
                    continue
                if any(_within_one_edit(a, candidate) for a in answer_forms):
                    return CheckResult(
                        correct=True, typo=True, matched=target, accepted=accepted
                    )

    return CheckResult(correct=False, accepted=accepted)
