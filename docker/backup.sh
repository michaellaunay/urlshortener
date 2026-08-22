#!/bin/bash
# Back up the SQLite file from the running container.
#
# `sqlite3 .backup` is used rather than `cp`: copying a file that is
# being written produces a snapshot that may not be consistent, and a
# backup nobody has restored is not a backup.
set -euo pipefail

CONTAINER="${1:-urlshortener}"
DESTINATION="${2:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "${DESTINATION}"

docker exec "${CONTAINER}" /home/urlshortener/venv/bin/python - <<'PY' > "${DESTINATION}/urlshortener-${STAMP}.sqlite"
import sqlite3, sys
source = sqlite3.connect("/home/urlshortener/app/var/urlshortener.sqlite")
target = sqlite3.connect(":memory:")
source.backup(target)
for line in target.iterdump():
    sys.stdout.write(line + "\n")
PY

echo "Wrote ${DESTINATION}/urlshortener-${STAMP}.sqlite (SQL dump)."
echo "Restore with: sqlite3 urlshortener.sqlite < urlshortener-${STAMP}.sqlite"
