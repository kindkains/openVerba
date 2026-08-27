"""Leitner-Boxen: Boxwechsel, Fälligkeit, Auswahl."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.leitner import (
    BOX_INTERVALS,
    MAX_BOX,
    MIN_BOX,
    Candidate,
    due_after,
    next_box,
    select,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


class TestBoxwechsel:
    @pytest.mark.parametrize("box,erwartet", [(1, 2), (2, 3), (3, 4), (4, 5)])
    def test_richtig_geht_hoch(self, box, erwartet):
        assert next_box(box, correct=True) == erwartet

    def test_box_fuenf_bleibt_box_fuenf(self):
        assert next_box(MAX_BOX, correct=True) == MAX_BOX

    @pytest.mark.parametrize("box", [1, 2, 3, 4, 5])
    def test_falsch_faellt_ganz_zurueck(self, box):
        assert next_box(box, correct=False) == MIN_BOX


class TestFaelligkeit:
    def test_box_eins_ist_sofort_wieder_faellig(self):
        assert due_after(1, NOW) == NOW

    @pytest.mark.parametrize("box,tage", [(2, 1), (3, 3), (4, 7), (5, 21)])
    def test_abstaende_je_box(self, box, tage):
        assert due_after(box, NOW) == NOW + timedelta(days=tage)

    def test_intervalle_wachsen_streng_monoton(self):
        werte = [BOX_INTERVALS[b] for b in range(1, 6)]
        assert werte == sorted(werte)
        assert len(set(werte)) == len(werte)


class TestAuswahl:
    def test_faellige_kommen_zuerst_niedrigste_box_voran(self):
        kandidaten = [
            Candidate(1, "fw", box=3, due_at=NOW - timedelta(days=1)),
            Candidate(2, "fw", box=1, due_at=NOW - timedelta(days=1)),
            Candidate(3, "fw", box=2, due_at=NOW - timedelta(days=1)),
        ]
        gewaehlt = select(kandidaten, 3, NOW, random.Random(0))
        assert [c.entry_id for c in gewaehlt] == [2, 3, 1]

    def test_ungesehene_kommen_nach_den_faelligen(self):
        kandidaten = [
            Candidate(1, "fw"),  # nie gesehen
            Candidate(2, "fw", box=1, due_at=NOW - timedelta(hours=1)),
        ]
        gewaehlt = select(kandidaten, 2, NOW, random.Random(0))
        assert [c.entry_id for c in gewaehlt] == [2, 1]

    def test_nicht_faellige_fuellen_nur_auf(self):
        kandidaten = [
            Candidate(1, "fw", box=4, due_at=NOW + timedelta(days=5)),
            Candidate(2, "fw", box=1, due_at=NOW - timedelta(hours=1)),
            Candidate(3, "fw"),
        ]
        gewaehlt = select(kandidaten, 3, NOW, random.Random(0))
        assert [c.entry_id for c in gewaehlt] == [2, 3, 1]

    def test_kein_rueckstau_bei_langer_pause(self):
        """400 überfällige Karten ergeben trotzdem nur eine normale Einheit."""
        kandidaten = [
            Candidate(i, "fw", box=1, due_at=NOW - timedelta(days=3))
            for i in range(400)
        ]
        assert len(select(kandidaten, 20, NOW, random.Random(0))) == 20

    def test_liefert_nie_mehr_als_vorhanden(self):
        kandidaten = [Candidate(1, "fw"), Candidate(2, "fw")]
        assert len(select(kandidaten, 20, NOW, random.Random(0))) == 2

    def test_leere_eingabe(self):
        assert select([], 20, NOW) == []

    def test_groesse_null(self):
        assert select([Candidate(1, "fw")], 0, NOW) == []

    def test_richtungen_werden_getrennt_gefuehrt(self):
        kandidaten = [
            Candidate(1, "fw", box=1, due_at=NOW - timedelta(hours=1)),
            Candidate(1, "bw", box=4, due_at=NOW + timedelta(days=5)),
        ]
        gewaehlt = select(kandidaten, 1, NOW, random.Random(0))
        assert gewaehlt[0].direction == "fw"
