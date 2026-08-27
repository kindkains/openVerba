# openVerba — Design

**Datum:** 2026-08-24
**Status:** freigegeben
**Lizenz des Projekts:** AGPL-3.0-or-later

## 1. Zweck

openVerba ist ein selbst gehosteter Vokabeltrainer für Familien und Schulkinder. Jeder
Nutzer pflegt seinen eigenen Vokabelbestand und lernt ihn in drei Abfragerichtungen. Der
Bestand wächst mit dem Unterricht mit: Das Kind trägt neue Wörter ein, sobald sie
drankommen, und lernt sie anschließend im selben Werkzeug.

Nicht-Ziele: kein Klassenraum-Management, keine Noten, keine mobile App, kein
Mehrmandanten-Betrieb über Familiengrenzen hinaus.

## 2. Architektur

Zwei Container, eine `docker-compose.yml`, keine Annahmen über die Umgebung. Die
Anwendung muss unverändert auf einem vServer, einem Raspberry Pi und unter Docker
Desktop auf Windows starten.

| Service | Basis | Rolle |
|---|---|---|
| `app` | `python:3.12-slim` | FastAPI + Uvicorn, Jinja2-Templates, statische Assets |
| `db` | `mariadb:11` | Named Volume `openverba-db`, Healthcheck, kein Port nach außen |

Rahmenbedingungen:

- Sämtliche Konfiguration kommt aus `.env`; `.env.example` dokumentiert jede Variable.
  Nichts Umgebungsspezifisches ist im Code oder im Compose-File hartkodiert.
- `app` startet erst, wenn der Healthcheck von `db` grün ist, führt dann die
  Alembic-Migrationen aus und seedet die Sprachtabelle.
- Genau ein exponierter Port (`OPENVERBA_PORT`, Default 8080). Die Anwendung setzt keinen
  Reverse-Proxy voraus, funktioniert aber hinter einem.
- Kein Node, kein Frontend-Buildstep. CSS und HTMX liegen im Image.

### Modulgrenzen

Jedes Modul hat einen Zweck und wird einzeln getestet.

| Modul | Aufgabe | Abhängigkeiten |
|---|---|---|
| `config.py` | `.env` einlesen und validieren | – |
| `db.py` | Engine, Session-Factory | `config` |
| `models.py` | SQLAlchemy-Modelle | `db` |
| `auth.py` | Login, Sessions, Passwort-Hashing, Reset-Tokens | `models`, `config` |
| `checker.py` | Antwortvergleich (rein funktional, kennt keine DB) | – |
| `leitner.py` | Boxwechsel und Auswahl der nächsten Vokabeln | `models` |
| `mailer.py` | Zustellung des Reset-Links (SMTP oder Anzeige) | `config` |
| `routers/` | HTTP-Endpunkte, Formularvalidierung | alle obigen |

`checker.py` und `leitner.py` sind die fachliche Substanz und bewusst frei von
Web- und ORM-Abhängigkeiten, damit sie ohne laufende Umgebung testbar bleiben.

## 3. Datenmodell

| Tabelle | Spalten (fachlich) |
|---|---|
| `languages` | `id`, `code` (z.B. `en`, `la`), `name`, `active` |
| `users` | `id`, `username` (unique), `email` (nullable), `password_hash`, `is_admin`, `must_change_password`, `created_at` |
| `password_reset_tokens` | `id`, `user_id`, `token_hash`, `expires_at`, `used_at` |
| `vocab_sets` | `id`, `owner_id`, `language_id`, `name`, `description`, `created_at` |
| `vocab_entries` | `id`, `set_id`, `note`, `created_at` |
| `vocab_variants` | `id`, `entry_id`, `side` (`foreign`/`de`), `text`, `is_primary` |
| `learn_progress` | `user_id`, `entry_id`, `direction` (`fw`/`bw`), `box`, `due_at`, `correct_count`, `wrong_count`, `last_seen_at` |

Entscheidungen:

- **Sprachen liegen in der Datenbank**, vorbefüllt mit Englisch und Latein. Weitere
  Sprachen legt der Admin über die Oberfläche an, ohne Code-Änderung.
- **`vocab_variants` statt zweier Textspalten.** Beide Seiten einer Vokabel dürfen
  mehrere gültige Formulierungen haben (`Hund` / `Rüde`, `run` / `sprint`). `is_primary`
  bestimmt, was beim Abfragen angezeigt wird.
- **`note`** nimmt Zusatzinfos auf, die nicht Teil der Antwort sind — bei Latein
  typischerweise die Stammformen (`amare, amo, amavi, amatum`). Wird nach der Antwort
  eingeblendet, nie mitgeprüft.
- **`learn_progress` hängt am Nutzer, nicht am Besitzer der Vokabel.** Nur so kann ein
  Nutzer fremde Vokabeln lernen und trotzdem eigene Boxen führen. Der Primärschlüssel ist
  `(user_id, entry_id, direction)`: Beide Abfragerichtungen werden getrennt gezählt, weil
  Deutsch → Fremdsprache deutlich schwerer ist als umgekehrt.
- Löscht der Admin einen Nutzer, werden dessen Sets, Einträge und Fortschritte per
  Fremdschlüssel-Kaskade mit entfernt. Die Oberfläche warnt vorher mit Anzahl der
  betroffenen Vokabeln.

## 4. Lernen

### Quelle

Drei Stufen, vor jeder Lerneinheit wählbar:

1. Ein einzelnes eigenes Set.
2. Alle eigenen Sets einer Sprache.
3. Alle Vokabeln aller Nutzer in dieser Sprache (globaler Pool).

### Modi

1. Fremdsprache → Deutsch (`fw`)
2. Deutsch → Fremdsprache (`bw`)
3. Zufällig gemischt — die Richtung wird pro Vokabel gewürfelt und getrennt gewertet.

### Auswahl (Leitner)

Fünf Boxen. Richtig beantwortet: eine Box hoch (max. 5). Falsch: zurück auf Box 1.
`due_at` wird nach Box gesetzt (Box 1: sofort, 2: +1 Tag, 3: +3 Tage, 4: +7 Tage,
5: +21 Tage).

Die Auswahl füllt eine Lerneinheit (Default 20 Vokabeln, einstellbar) in dieser
Reihenfolge auf:

1. fällige Vokabeln (`due_at <= now`), niedrigste Box zuerst
2. noch nie gesehene Vokabeln
3. der Rest, zufällig

Damit entsteht kein Rückstau: Wer drei Tage aussetzt, bekommt keine 400 überfälligen
Karten vorgesetzt, sondern eine normale Einheit.

### Antwortprüfung

`checker.py` normalisiert Eingabe und alle Varianten der Zielseite in dieser Reihenfolge:

1. Trimmen, Mehrfach-Leerzeichen zu einem zusammenziehen, Kleinschreibung.
2. Unicode NFKD, danach kombinierende Zeichen entfernen — `amāre` gilt als `amare`.
3. Führende Artikel und Infinitiv-Marker optional: `der|die|das|den|dem|ein|eine` und
   englisch `to |the ` dürfen fehlen oder dastehen.
4. Klammerzusätze optional: `(sich) freuen` akzeptiert `sich freuen` und `freuen`.
5. Vergleich gegen **jede** Variante der Zielseite; eine Übereinstimmung genügt.
6. Tippfehler-Toleranz: Levenshtein-Distanz ≤ 1 bei normalisierter Länge ≥ 5 zählt als
   richtig, die Rückmeldung zeigt aber die korrekte Schreibweise. Abschaltbar über
   `OPENVERBA_TYPO_TOLERANCE=false`.

Nach jeder Antwort zeigt die Oberfläche alle gültigen Varianten und die `note`.

## 5. Accounts und Passwort-Reset

- Der Admin wird beim ersten Start aus `OPENVERBA_ADMIN_USER` und
  `OPENVERBA_ADMIN_PASSWORD` angelegt. Existiert der Nutzer bereits, passiert nichts —
  der Start bleibt idempotent. `must_change_password` erzwingt den Wechsel beim ersten
  Login.
- **Keine Selbstregistrierung.** Nur der Admin legt Nutzer an, löscht sie und setzt
  Passwörter zurück. `email` ist optional, damit Kinder ohne Postfach einen Account
  bekommen.
- **Reset im Standardbetrieb:** Der Nutzer stellt über "Passwort vergessen" eine Anfrage.
  Der Admin sieht offene Anfragen in seinem Bereich, erzeugt einen Einmal-Link und gibt
  ihn weiter. Kein SMTP nötig.
- **Reset per Mail:** Ist `SMTP_HOST` gesetzt und hat der Nutzer eine Adresse hinterlegt,
  verschickt `mailer.py` denselben Link automatisch. Der Admin sieht die Anfrage
  weiterhin, damit ein fehlgeschlagener Versand nicht zur Sackgasse wird.
- Reset-Tokens sind Einmal-Tokens, 24 Stunden gültig, in der Datenbank nur als Hash.
- Sessions laufen über signierte Cookies (`SECRET_KEY` aus der `.env`), Passwörter über
  bcrypt. Alle Formulare tragen ein CSRF-Token.
- Auf die Anfrageseite antwortet die Anwendung immer gleich, egal ob der Nutzername
  existiert — kein Nutzernamen-Orakel.

## 6. Fehlerbehandlung

- Ist die Datenbank nicht erreichbar, liefert die Anwendung eine verständliche
  Fehlerseite statt eines Stacktrace und erholt sich, sobald die Datenbank zurück ist.
- Formulare werden serverseitig validiert; Fehler erscheinen am Feld, die Eingaben
  bleiben erhalten.
- Fehlgeschlagener Mailversand wird protokolliert und dem Admin gemeldet, bricht den
  Reset-Vorgang aber nicht ab — der Link bleibt im Admin-Bereich abrufbar.
- Unbehandelte Ausnahmen landen im Log, nie in der Antwort an den Browser.

## 7. Tests

- **Unit-Tests (pytest, SQLite in-memory):** `checker.py` (Normalisierung, Synonyme,
  Artikel, Klammern, Tippfehlergrenze) und `leitner.py` (Boxwechsel, `due_at`-Berechnung,
  Auffüllreihenfolge der Auswahl).
- **Routen-Smoketests (httpx):** Login, Nutzerverwaltung durch den Admin,
  Vokabel-CRUD, ein vollständiger Lerndurchlauf, Reset-Ablauf ohne SMTP.
- **Integrationslauf:** `docker compose --profile test` startet die Suite gegen ein
  echtes MariaDB, damit Migrationen und Kollation abgesichert sind.

## 8. Ordnerstruktur

```
openverba/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── README.md
├── LICENSE                      (AGPL-3.0)
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── auth.py
│   ├── checker.py
│   ├── leitner.py
│   ├── mailer.py
│   ├── routers/
│   ├── templates/
│   ├── static/
│   └── alembic/
├── tests/
└── docs/superpowers/specs/
```

## 9. Konfiguration (.env)

| Variable | Default | Zweck |
|---|---|---|
| `OPENVERBA_PORT` | `8080` | Port auf dem Host |
| `OPENVERBA_SECRET_KEY` | – | Signatur der Session-Cookies, Pflicht |
| `OPENVERBA_ADMIN_USER` | `admin` | Bootstrap-Admin |
| `OPENVERBA_ADMIN_PASSWORD` | – | Bootstrap-Passwort, Pflicht beim ersten Start |
| `OPENVERBA_SESSION_SIZE` | `20` | Vokabeln pro Lerneinheit |
| `OPENVERBA_TYPO_TOLERANCE` | `true` | Levenshtein-Toleranz an/aus |
| `MARIADB_DATABASE` | `openverba` | Datenbankname |
| `MARIADB_USER` / `MARIADB_PASSWORD` | – | Anwendungszugang |
| `MARIADB_ROOT_PASSWORD` | – | Root-Passwort des Datenbankcontainers |
| `SMTP_HOST` | leer | leer = Reset-Link nur im Admin-Bereich |
| `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_STARTTLS` | – | Mailversand, sofern `SMTP_HOST` gesetzt |
| `OPENVERBA_BASE_URL` | `http://localhost:8080` | Basis für Reset-Links in Mails |
