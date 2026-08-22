#!/bin/bash
# Container entrypoint.
#
# Order matters: the schema is created and stamped BEFORE the server
# accepts a request. Doing it lazily on the first request means the
# first visitor of a fresh deployment gets a 500.
set -euo pipefail

CONFIG_FILE="${1:-production.ini}"
VENV_DIR="${VENV_DIR:-/home/urlshortener/venv}"
APP_HOME="${APP_HOME:-/home/urlshortener/app}"

cd "${APP_HOME}"

# `.env` is read by the application itself (python-dotenv). It is
# looked up from the WORKING DIRECTORY, which is why the cd above is
# not decorative: find_dotenv() called from an installed wheel would
# otherwise search inside site-packages and find nothing.
if [ -f "${APP_HOME}/.env" ]; then
    echo "[start] using ${APP_HOME}/.env"
fi

mkdir -p "${APP_HOME}/var"

# Derive a runtime .ini carrying the container's server settings. The
# versioned production.ini stays valid for bare metal.
RUNTIME_INI="${APP_HOME}/var/runtime.ini"
"${VENV_DIR}/bin/python" "${APP_HOME}/docker/apply_server_overrides.py" \
    "${CONFIG_FILE}" "${RUNTIME_INI}"

echo "[start] applying schema upgrades"
"${VENV_DIR}/bin/python" -m urlshortener.upgrades "${RUNTIME_INI}"

echo "[start] serving ${RUNTIME_INI}"
exec "${VENV_DIR}/bin/pserve" "${RUNTIME_INI}"
