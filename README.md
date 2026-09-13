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

## Applying a patch

Changes are delivered as patches applied with `git apply`, in numbered
order. **A patch can add a dependency**, so reinstall whenever the
`git apply` touched a `requirements*.lock`:

```bash
git apply --check 00NN-....patch      # says yes or no, changes nothing
git apply 00NN-....patch
git status --short                    # did a lock change?
pip install --require-hashes -r requirements-test.lock
python -m pytest -q
```

Skipping the reinstall gives a `ModuleNotFoundError`. Depending on
where the import sits, that is either three named failures or pytest's
whole collection collapsing before a single test can report anything
useful. No test can check what is installed in your virtualenv — the
suite only checks that a new dependency is declared and locked.

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
- **Gated, if you want it**: an allow-list (host and URL wildcards,
  `re:…` regular expressions) shortens listed targets on the spot; any
  other target is asked for an e-mail address and the short link goes
  to the mailbox, not to the screen. An `/admin` page (HTTP Basic,
  PBKDF2) lists every link, who asked for it, and can block — 410,
  recreation-proof — or delete. Empty list = everything allowed, the
  2016-compatible default.
- **Tested**: 576 tests, 91% coverage, three CI workflows (unit,
  quality, container smoke).
- **Audited**: one internal pass and four external passes (three by
  ChatGPT, one crossing pass by Claude), all filed under
  `docs/fr/audits/`, every fixable finding fixed with a regression
  test of its own.

## The allow-list in one minute

```ini
urlshortener.whitelist =
    example.coop *.example.coop
    https://docs.example.org/*
    re:^https://forum\.example\.net/t/\d+$
urlshortener.smtp_host = localhost
urlshortener.mail_sender = links@example.coop
```

Three entry forms, told apart by shape: a bare pattern matches the
**host**, a pattern containing `://` matches the **whole URL**, a
`re:` prefix is a regular expression (fullmatch). Everything is
matched against the **canonical** form the service stores. Two rules
bite: `*.example.coop` does **not** match the bare apex
`example.coop` — list both, as above — and entries are separated by
any whitespace, so an entry can never contain a space (in a regex,
write `\s`). The full manual, including internationalised domains and
a pre-deployment check, is in
[docs/en/01_installation.md](docs/en/01_installation.md).

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
