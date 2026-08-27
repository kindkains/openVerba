#!/usr/bin/env bash
#
# Startreihenfolge: Migrationen einspielen, Grunddaten setzen, dann erst die Anwendung.
# Läuft bei jedem Start; beide Schritte sind idempotent.

set -Eeuo pipefail

echo "[openverba] Migrationen werden eingespielt ..."
alembic upgrade head

echo "[openverba] Grunddaten werden geprüft (Sprachen, Bootstrap-Admin) ..."
python -m app.bootstrap

echo "[openverba] Start."
exec "$@"
