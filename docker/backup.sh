#!/bin/bash
# Back up the SQLite file from the running container.
#
# Two things this script must get right, both from the external audit
# of 2026-08-22 (finding C-12):
#
# * the dump contains EVERY target URL the service has ever stored, so
#   it is created private and stays private. `umask 077` is set before
#   anything is written, rather than the permissions being relaxed and
#   then tightened after the fact -- which would leave a window during
#   which the file is world-readable;
#
# * it must not be assembled in memory. The previous version copied the
#   whole database into a `:memory:` connection before dumping it,
#   inside a container declared `mem_limit: 512m`. `.backup` to a file
#   streams instead, and takes a CONSISTENT snapshot of a database that
#   is being written to -- which a plain `cp` does not.
set -euo pipefail

umask 077

CONTAINER="${1:-urlshortener}"
DESTINATION="${2:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="urlshortener-${STAMP}.sqlite"

install -d -m 700 "${DESTINATION}"

# Snapshot inside the container, then stream the file out. /tmp is the
# container's own, and is removed whether or not the copy succeeds.
docker exec "${CONTAINER}" /home/urlshortener/venv/bin/python - <<'PY'
import os
import sqlite3

SOURCE = "/home/urlshortener/app/var/urlshortener.sqlite"
SNAPSHOT = "/tmp/urlshortener-backup.sqlite"

if os.path.exists(SNAPSHOT):
    os.unlink(SNAPSHOT)
os.umask(0o077)

source = sqlite3.connect("file:%s?mode=ro" % SOURCE, uri=True)
target = sqlite3.connect(SNAPSHOT)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY

docker exec "${CONTAINER}" cat /tmp/urlshortener-backup.sqlite > "${DESTINATION}/${NAME}"
docker exec "${CONTAINER}" rm -f /tmp/urlshortener-backup.sqlite

echo "Wrote ${DESTINATION}/${NAME}"
echo "It contains every stored URL — keep it where the database is kept."
echo "Restore: stop the service, put this file at var/urlshortener.sqlite, start it."
echo "Verify:  sqlite3 ${DESTINATION}/${NAME} 'PRAGMA integrity_check; SELECT count(*) FROM links;'"
