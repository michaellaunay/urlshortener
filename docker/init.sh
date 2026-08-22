#!/bin/bash
# Run once before the first `docker compose up`.
#
# It creates docker/.env from the example and refuses to overwrite an
# existing one: the day this is run twice by mistake, the deployment
# configuration must survive.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/.." && pwd)"

if [ -f "${HERE}/.env" ]; then
    echo "docker/.env already exists — leaving it alone."
else
    cp "${REPO_ROOT}/.env.example" "${HERE}/.env"
    chmod 0600 "${HERE}/.env"
    echo "Created docker/.env from .env.example."
    echo "EDIT IT: URLSHORTENER_BASE_URL must be the PUBLIC prefix of the"
    echo "short links, trailing slash included — the links handed out are"
    echo "wrong forever otherwise."
fi

echo
echo "Then:"
echo "  docker compose --env-file docker/.env -f docker/docker-compose.yaml up -d --build"
