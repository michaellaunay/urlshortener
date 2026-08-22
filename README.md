# urlshortener

A URL shortener. Successor to
[`ecreall/urlshortener`](https://github.com/ecreall/urlshortener) (2016),
rewritten on Pyramid 2 / SQLAlchemy 2. AGPL v3.

Every short link handed out by the 2016 service keeps working: the code
alphabet, `GET /?url=`, `POST /` and `GET /<code>` are unchanged, and
`tools/import_legacy` brings the old `var/urls.db` over verbatim.

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements-test.lock
pip install --no-deps -e .

python -m urlshortener.upgrades development.ini
pserve development.ini --reload      # http://localhost:5123/
```

With Docker:

```bash
./docker/init.sh && $EDITOR docker/.env
docker compose --env-file docker/.env -f docker/docker-compose.yaml up -d --build
```

## Using it

```bash
# legacy entry point, unchanged since 2016
curl 'http://localhost:5123/?url=https://example.org/a/long/page'
# {"short_url": "http://localhost:5123/h6QStqWsRk3", "code": "SUCCESS", ...}

# JSON API v1
curl -X POST http://localhost:5123/api/v1/shorten \
     -H 'Content-Type: application/json' \
     -d '{"url": "https://example.org/a/long/page"}'

# follow it
curl -I http://localhost:5123/h6QStqWsRk3   # 302 -> https://example.org/a/long/page
```

## What is here

- **Compatible** with the 2016 clients, including KuneAgi's
  `/urlmetadata/` mount point. One deliberate change: an unknown code
  answers 404 instead of 200.
- **Safe by construction**: parameterised SQL, one canonical spelling of
  the host before every check, scheme allowlist, no credentials in the
  authority, private addresses refused in all four of their notations,
  eleven-character unpredictable codes, request bodies capped in three
  tiers, CSP and `Referrer-Policy`, no third-party CDN, no IP address
  stored. Start-up refuses a configuration that cannot work.
- **English, French, German, Spanish**, with one locale registry and
  the remaining EU official languages declared and one boolean away.
- **Operable**: digest-pinned multi-stage image, hash-checked
  dependency locks, non-root, health check, backup script, schema
  upgrade steps.
- **Tested**: 410 tests, 91% coverage, three CI workflows (unit,
  quality, container smoke).
- **Audited**: one internal pass and one external pass, both filed
  under `docs/fr/audits/`, every fixable finding fixed with a
  regression test of its own.

## Documentation

Bilingual, in [`docs/fr`](docs/fr/00_index.md) and
[`docs/en`](docs/en/00_index.md):

installation · API and routes · internationalisation · Docker and
operations · migrating from 2016 · security · the Keycloak SSO roadmap
· the audit reports.

`CHANGES.txt` lists every difference from the 2016 service, deliberate
breaks included.

## Licence

GNU Affero General Public License v3 or later.
Copyright (c) 2016 Ecreall — Copyright (c) 2026 Logikascium.

The intellectual property of Ecreall was acquired by Logikascium in
2024; this repository continues that lineage rather than forking away
from it.
