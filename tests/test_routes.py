"""Smoketests über die HTTP-Schicht: Login, Verwaltung, Vokabeln, ein ganzer Lerndurchlauf."""

from __future__ import annotations

from sqlalchemy import select

from app.models import LearnProgress, PasswordResetToken, User, VocabEntry, VocabSet
from tests.conftest import csrf, login, make_entry, make_set, make_user


class TestAnmeldung:
    def test_ohne_anmeldung_umleitung_zum_login(self, client):
        response = client.get("/learn", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_erfolgreiche_anmeldung(self, client, db):
        make_user(db)
        login(client)
        assert client.get("/learn").status_code == 200

    def test_falsches_passwort(self, client, db):
        make_user(db)
        client.get("/login")
        response = client.post(
            "/login",
            data={"username": "kind", "password": "falsch", "csrf_token": csrf(client)},
        )
        assert response.status_code == 401

    def test_unbekannter_benutzer_gleiche_meldung(self, client, db):
        make_user(db)
        client.get("/login")
        response = client.post(
            "/login",
            data={"username": "gibtsnicht", "password": "x", "csrf_token": csrf(client)},
        )
        assert response.status_code == 401
        assert "stimmt nicht" in response.text

    def test_ohne_csrf_token_abgelehnt(self, client, db):
        make_user(db)
        client.get("/login")
        response = client.post(
            "/login", data={"username": "kind", "password": "geheim123", "csrf_token": ""}
        )
        assert response.status_code == 400

    def test_passwortwechsel_wird_erzwungen(self, client, db):
        user = make_user(db)
        user.must_change_password = True
        db.commit()
        login(client)
        response = client.get("/learn", follow_redirects=False)
        assert response.headers["location"] == "/password"


class TestVerwaltung:
    def test_admin_legt_benutzer_an(self, client, db):
        make_user(db, "chef", is_admin=True)
        login(client, "chef")
        response = client.post(
            "/admin/users",
            data={
                "username": "neu",
                "email": "",
                "password": "startpasswort",
                "csrf_token": csrf(client),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        angelegt = db.scalar(select(User).where(User.username == "neu"))
        assert angelegt is not None
        assert angelegt.must_change_password is True
        assert angelegt.email is None

    def test_doppelter_benutzername_abgelehnt(self, client, db):
        make_user(db, "chef", is_admin=True)
        login(client, "chef")
        response = client.post(
            "/admin/users",
            data={"username": "chef", "password": "startpasswort", "csrf_token": csrf(client)},
        )
        assert response.status_code == 400

    def test_normaler_benutzer_kommt_nicht_in_die_verwaltung(self, client, db):
        make_user(db)
        login(client)
        assert client.get("/admin").status_code == 403

    def test_admin_erzeugt_reset_link(self, client, db):
        make_user(db, "chef", is_admin=True)
        ziel = make_user(db, "kind")
        login(client, "chef")
        response = client.post(
            f"/admin/users/{ziel.id}/reset", data={"csrf_token": csrf(client)}
        )
        assert response.status_code == 200
        assert "/reset/" in response.text
        assert db.scalar(select(PasswordResetToken)) is not None

    def test_admin_kann_sich_nicht_selbst_loeschen(self, client, db):
        chef = make_user(db, "chef", is_admin=True)
        login(client, "chef")
        response = client.post(
            f"/admin/users/{chef.id}/delete", data={"csrf_token": csrf(client)}
        )
        assert response.status_code == 400
        assert db.get(User, chef.id) is not None


class TestVokabeln:
    def test_set_und_eintrag_anlegen(self, client, db, language):
        make_user(db)
        login(client)
        client.post(
            "/sets",
            data={"name": "Unit 1", "language_id": language.id, "csrf_token": csrf(client)},
        )
        vocab_set = db.scalar(select(VocabSet))
        assert vocab_set is not None

        client.post(
            f"/sets/{vocab_set.id}/entries",
            data={
                "foreign": "to run; to sprint",
                "german": "rennen; sprinten",
                "note": "unregelmäßig",
                "csrf_token": csrf(client),
            },
        )
        entry = db.scalar(select(VocabEntry))
        assert entry is not None
        assert len(entry.variants) == 4
        assert entry.note == "unregelmäßig"

    def test_leere_seite_wird_abgelehnt(self, client, db, language):
        user = make_user(db)
        vocab_set = make_set(db, user, language)
        login(client)
        response = client.post(
            f"/sets/{vocab_set.id}/entries",
            data={"foreign": "hund", "german": "   ", "csrf_token": csrf(client)},
        )
        assert response.status_code == 400

    def test_fremde_sets_sind_nicht_erreichbar(self, client, db, language):
        fremd = make_user(db, "fremd")
        fremdes_set = make_set(db, fremd, language)
        make_user(db, "kind")
        login(client, "kind")
        response = client.get(f"/sets/{fremdes_set.id}", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/sets"


class TestLerndurchlauf:
    def _vorbereiten(self, db, language):
        user = make_user(db)
        vocab_set = make_set(db, user, language)
        make_entry(db, vocab_set, ["dog"], ["Hund"])
        make_entry(db, vocab_set, ["cat"], ["Katze"])
        return user, vocab_set

    def test_ganze_runde(self, client, db, language):
        user, vocab_set = self._vorbereiten(db, language)
        login(client)

        gestartet = client.post(
            "/learn/start",
            data={"source": f"set:{vocab_set.id}", "mode": "fw", "csrf_token": csrf(client)},
            follow_redirects=False,
        )
        assert gestartet.status_code == 303

        for _ in range(2):
            frage = client.get("/learn/question")
            assert frage.status_code == 200
            antwort = client.post(
                "/learn/answer",
                data={"given": "Hund", "csrf_token": csrf(client)},
            )
            assert antwort.status_code == 200

        auswertung = client.get("/learn/done")
        assert auswertung.status_code == 200

        fortschritte = list(db.scalars(select(LearnProgress)))
        assert len(fortschritte) == 2
        assert all(p.user_id == user.id for p in fortschritte)

    def test_richtige_antwort_hebt_die_box(self, client, db, language):
        _, vocab_set = self._vorbereiten(db, language)
        login(client)
        client.post(
            "/learn/start",
            data={"source": f"set:{vocab_set.id}", "mode": "fw", "csrf_token": csrf(client)},
        )
        frage = client.get("/learn/question")
        # Die angezeigte Vokabel bestimmt die erwartete Antwort.
        erwartet = "Hund" if "dog" in frage.text else "Katze"
        client.post("/learn/answer", data={"given": erwartet, "csrf_token": csrf(client)})

        fortschritt = db.scalar(select(LearnProgress))
        assert fortschritt.box == 2
        assert fortschritt.correct_count == 1

    def test_falsche_antwort_zaehlt_als_fehler(self, client, db, language):
        _, vocab_set = self._vorbereiten(db, language)
        login(client)
        client.post(
            "/learn/start",
            data={"source": f"set:{vocab_set.id}", "mode": "fw", "csrf_token": csrf(client)},
        )
        client.get("/learn/question")
        client.post("/learn/answer", data={"given": "voellig daneben", "csrf_token": csrf(client)})

        fortschritt = db.scalar(select(LearnProgress))
        assert fortschritt.box == 1
        assert fortschritt.wrong_count == 1

    def test_leere_auswahl_meldet_sich(self, client, db, language):
        make_user(db)
        login(client)
        response = client.post(
            "/learn/start",
            data={"source": f"global:{language.id}", "mode": "fw", "csrf_token": csrf(client)},
        )
        assert "Hier ist noch nichts" in response.text

    def test_globaler_pool_enthaelt_fremde_vokabeln(self, client, db, language):
        fremd = make_user(db, "fremd")
        fremdes_set = make_set(db, fremd, language)
        make_entry(db, fremdes_set, ["dog"], ["Hund"])
        make_user(db, "kind")
        login(client, "kind")

        response = client.post(
            "/learn/start",
            data={"source": f"global:{language.id}", "mode": "fw", "csrf_token": csrf(client)},
            follow_redirects=False,
        )
        assert response.status_code == 303


class TestPasswortReset:
    def test_ablauf_ohne_smtp(self, client, db):
        user = make_user(db)

        client.get("/forgot")
        angefragt = client.post(
            "/forgot", data={"username": "kind", "csrf_token": csrf(client)}
        )
        assert angefragt.status_code == 200
        assert db.scalar(select(PasswordResetToken)) is not None

        # Der Admin gibt den Link weiter — hier direkt erzeugt.
        from app.auth import create_reset_token

        token = create_reset_token(db, user)

        client.get(f"/reset/{token}")
        gesetzt = client.post(
            f"/reset/{token}",
            data={
                "new_password": "neuespasswort",
                "repeat_password": "neuespasswort",
                "csrf_token": csrf(client),
            },
        )
        assert gesetzt.status_code == 200

        client.cookies.clear()
        login(client, "kind", "neuespasswort")

    def test_token_nur_einmal_verwendbar(self, client, db):
        user = make_user(db)
        from app.auth import create_reset_token

        token = create_reset_token(db, user)
        client.get(f"/reset/{token}")
        daten = {
            "new_password": "neuespasswort",
            "repeat_password": "neuespasswort",
            "csrf_token": csrf(client),
        }
        assert client.post(f"/reset/{token}", data=daten).status_code == 200

        zweiter = client.post(f"/reset/{token}", data=daten)
        assert zweiter.status_code == 400

    def test_unbekannter_benutzer_verraet_nichts(self, client, db):
        make_user(db)
        client.get("/forgot")
        response = client.post(
            "/forgot", data={"username": "gibtsnicht", "csrf_token": csrf(client)}
        )
        assert response.status_code == 200
        assert db.scalar(select(PasswordResetToken)) is None


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"
