"""Antwortvergleich — die Regeln aus Abschnitt 4 der Design-Spec."""

from __future__ import annotations

import pytest

from app.checker import check, forms, normalize


class TestNormalisierung:
    def test_trimmt_und_zieht_leerzeichen_zusammen(self):
        assert normalize("  to   run  ") == "to run"

    def test_ignoriert_grossschreibung(self):
        assert normalize("Hund") == "hund"

    def test_entfernt_diakritische_zeichen(self):
        assert normalize("amāre") == "amare"
        assert normalize("café") == "cafe"


class TestExakteTreffer:
    def test_einfache_uebereinstimmung(self):
        assert check("Hund", ["Hund"]).correct

    def test_synonyme_zaehlen_alle(self):
        result = check("Rüde", ["Hund", "Rüde"])
        assert result.correct
        assert result.matched == "Rüde"

    def test_falsche_antwort(self):
        assert not check("Katze", ["Hund"]).correct

    def test_leere_antwort_ist_falsch(self):
        assert not check("", ["Hund"]).correct
        assert not check("   ", ["Hund"]).correct

    def test_ohne_zielvarianten_ist_falsch(self):
        assert not check("Hund", []).correct


class TestArtikelUndMarker:
    @pytest.mark.parametrize("given", ["der Hund", "Hund"])
    def test_deutscher_artikel_optional(self, given):
        assert check(given, ["der Hund"]).correct

    @pytest.mark.parametrize("given", ["to run", "run"])
    def test_englischer_infinitiv_optional(self, given):
        assert check(given, ["to run"]).correct

    def test_artikel_darf_auch_dazukommen(self):
        assert check("das Haus", ["Haus"]).correct


class TestKlammern:
    @pytest.mark.parametrize("given", ["sich freuen", "freuen"])
    def test_klammerzusatz_optional(self, given):
        assert check(given, ["(sich) freuen"]).correct

    def test_klammer_am_ende(self):
        assert check("laufen", ["laufen (schnell)"]).correct


class TestTippfehler:
    def test_ein_fehler_wird_verziehen(self):
        result = check("Hunde", ["Hunde"])
        assert result.correct and not result.typo

        result = check("Hunda", ["Hunde"])
        assert result.correct
        assert result.typo is True

    def test_fehlendes_zeichen(self):
        assert check("amre", ["amare"]).typo

    def test_zusaetzliches_zeichen(self):
        assert check("amaare", ["amare"]).typo

    def test_kurze_woerter_ohne_toleranz(self):
        # "haus" hat nur 4 Zeichen — unter der Grenze von 5.
        assert not check("hais", ["haus"]).correct

    def test_zwei_fehler_sind_zu_viel(self):
        assert not check("amiri", ["amare"]).correct

    def test_abschaltbar(self):
        assert not check("Hunda", ["Hunde"], typo_tolerance=False).correct


class TestFormen:
    def test_liefert_varianten_mit_und_ohne_artikel(self):
        assert forms("der Hund") == frozenset({"der hund", "hund"})

    def test_leerer_text_liefert_nichts(self):
        assert forms("   ") == frozenset()


def test_ergebnis_nennt_alle_gueltigen_antworten():
    result = check("falsch", ["Hund", "Rüde"])
    assert not result.correct
    assert result.accepted == ("Hund", "Rüde")
