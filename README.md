# openVerba

Selbst gehosteter Vokabeltrainer für Familien und Schulkinder. Jeder pflegt seinen eigenen
Vokabelbestand und lernt ihn in drei Abfragerichtungen. Der Bestand wächst mit dem
Unterricht mit: neue Wörter eintragen, sobald sie drankommen, und im selben Werkzeug
lernen.

Zwei Container, eine `docker-compose.yml`, keine Annahmen über die Umgebung — läuft
unverändert auf einem vServer, einem Raspberry Pi und unter Docker Desktop.

## Schnellstart

```bash
git clone git@github.com:kindkains/openVerba.git
cd openVerba
cp .env.example .env
```

Dann die `.env` ausfüllen. Drei Werte sind Pflicht:

```bash
# Schlüssel erzeugen
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

| Variable | |
|---|---|
| `OPENVERBA_SECRET_KEY` | signiert die Session-Cookies |
| `OPENVERBA_ADMIN_PASSWORD` | Passwort des Bootstrap-Admins |
| `MARIADB_PASSWORD`, `MARIADB_ROOT_PASSWORD` | Datenbankzugänge |

Danach:

```bash
docker compose up -d
```

Die Oberfläche läuft auf <http://localhost:8080> (Port über `OPENVERBA_PORT`
einstellbar). Beim ersten Anmelden als Admin verlangt openVerba einen Passwortwechsel.

## Wie es benutzt wird

1. **Als Admin** unter *Verwaltung* die Benutzer anlegen. Eine Selbstregistrierung gibt es
   bewusst nicht. Die Mailadresse ist optional — Kinder haben oft keine. Der Admin sieht
   und bearbeitet zudem die Vokabelsets aller Benutzer und kann Passwörter direkt setzen
   (wahlweise mit erzwungenem Wechsel bei der nächsten Anmeldung).
2. **Als Benutzer** unter *Meine Vokabeln* ein Set anlegen (etwa „Unit 3“) und Vokabeln
   eintragen. Mehrere gültige Antworten werden mit Semikolon getrennt:
   `to run; to sprint` ↔ `rennen; sprinten`. Die erste Variante ist die, die beim
   Abfragen angezeigt wird.
3. Das Feld **Notiz** nimmt Zusatzinfos auf, die nie abgefragt werden — bei Latein etwa
   die Stammformen `currere, curro, cucurri, cursum`. Sie erscheinen nach der Antwort.
4. **Lernen** startet eine Einheit. Quelle ist wahlweise ein einzelnes Set, alle eigenen
   Sets einer Sprache oder der gemeinsame Pool aller Benutzer.

## Wie abgefragt wird

Fünf Leitner-Boxen. Richtig beantwortet geht eine Vokabel eine Box hoch, falsch fällt sie
auf Box 1 zurück. Die Wiedervorlage richtet sich nach der Box: sofort, 1, 3, 7, 21 Tage.
Eine falsch beantwortete Vokabel ist damit sofort wieder fällig und kommt in der
nächsten Einheit als erste dran.

**Ein einzelnes Set wird immer komplett abgefragt.** Nur beim Mischen — alle eigenen
Sets einer Sprache oder der gemeinsame Pool — greift die Einheitsgröße: Standard sind
20 Vokabeln (`OPENVERBA_SESSION_SIZE`), vor dem Start frei wählbar, Obergrenze 200.

Eine Einheit wird in dieser Reihenfolge aufgefüllt: fällige Vokabeln (niedrigste Box
zuerst), dann noch nie gesehene, dann der Rest. **Damit entsteht kein Rückstau** — wer drei
Tage aussetzt, bekommt keine 400 überfälligen Karten vorgesetzt, sondern eine normale
Einheit. Genau deshalb kein SM-2/Anki.

Beide Richtungen werden getrennt gezählt, weil Deutsch → Fremdsprache deutlich schwerer
ist als umgekehrt. Der Fortschritt hängt am lernenden Benutzer, nicht am Besitzer der
Vokabel: fremde Vokabeln aus dem gemeinsamen Pool lassen sich lernen, ohne dessen Boxen
anzufassen.

### Was als richtig gilt

Groß-/Kleinschreibung, Mehrfach-Leerzeichen und diakritische Zeichen sind egal — `amāre`
gilt als `amare`. Artikel und Infinitiv-Marker dürfen fehlen oder dastehen (`der Hund` =
`Hund`, `to run` = `run`). Klammerzusätze sind optional: `(sich) freuen` akzeptiert
`sich freuen` und `freuen`. Jede hinterlegte Variante zählt.

Ein Tippfehler wird ab fünf Zeichen Länge verziehen, die Rückmeldung zeigt dann die
richtige Schreibweise. Abschaltbar über `OPENVERBA_TYPO_TOLERANCE=false`.

## Gelöschte Sets: der Papierkorb

Löscht ein Benutzer ein Set, verschwindet es nur aus seiner Sicht und aus allen
Abfragen — tatsächlich liegt es im Papierkorb. Der Admin sieht das in der Verwaltung,
kann das Set samt Lernfortschritt wiederherstellen oder es endgültig löschen.
Endgültiges Löschen geht nur aus dem Papierkorb heraus, nie direkt.

## Passwort vergessen

Im Normalbetrieb ohne Mailserver: Der Benutzer stellt über *Passwort vergessen* eine
Anfrage, der Admin sieht sie in seinem Bereich, erzeugt einen Einmal-Link und gibt ihn
weiter. Die Links gelten 24 Stunden und lassen sich nur einmal verwenden.

Ist `SMTP_HOST` gesetzt und hat der Benutzer eine Adresse hinterlegt, geht derselbe Link
zusätzlich per Mail raus. Die Anfrage bleibt trotzdem im Admin-Bereich sichtbar, damit ein
fehlgeschlagener Versand keine Sackgasse ist.

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Die Tests laufen gegen SQLite im Speicher, es braucht also kein MariaDB. `checker.py` und
`leitner.py` sind bewusst frei von Web- und ORM-Abhängigkeiten und dadurch ohne laufende
Umgebung testbar.

Gegen ein echtes MariaDB testen (sichert Migrationen und Kollation ab):

```bash
docker compose up -d db
DATABASE_URL="mysql+pymysql://openverba:PASSWORT@127.0.0.1:3306/openverba?charset=utf8mb4" \
  .venv/bin/python -m pytest
```

Dafür muss der Port der Datenbank vorübergehend nach außen gelegt werden — im
Normalbetrieb ist er bewusst zu.

### Aufbau

| Modul | Aufgabe |
|---|---|
| `config.py` | `.env` einlesen und validieren |
| `db.py` | Engine, Session-Factory |
| `models.py` | SQLAlchemy-Modelle |
| `auth.py` | Login, Sessions, Passwort-Hashing, Reset-Tokens |
| `checker.py` | Antwortvergleich, rein funktional |
| `leitner.py` | Boxwechsel und Auswahl der nächsten Vokabeln |
| `mailer.py` | Zustellung des Reset-Links |
| `routers/` | HTTP-Endpunkte |

Die Design-Entscheidungen samt Begründung stehen in
[`docs/superpowers/specs/2026-08-24-openverba-design.md`](docs/superpowers/specs/2026-08-24-openverba-design.md).

## Betrieb

Die Anwendung setzt keinen Reverse-Proxy voraus, funktioniert aber hinter einem. Läuft sie
hinter TLS, gehört die öffentliche Adresse in `OPENVERBA_BASE_URL` — sonst zeigen die
Reset-Links ins Leere.

Migrationen und Grunddaten laufen bei jedem Start automatisch und sind idempotent. Die
Datenbank liegt im Named Volume `openverba-db` und hat keinen Port nach außen.

## Lizenz

AGPL-3.0-or-later, siehe [LICENSE](LICENSE).
