# urlshortener — documentation

A URL shortener. Successor to `ecreall/urlshortener` (2016), rewritten
on Pyramid 2 / SQLAlchemy 2, under the AGPL v3.

The documentation exists in two languages, `docs/fr` and `docs/en`,
which are mirrors: a change to one calls for a change to the other.

## Contents

| Chapter | Subject |
| --- | --- |
| [01 — Installation](01_installation.md) | Standing the service up, locally then on a server |
| [02 — API and routes](02_api.md) | Every entry point, the 2016 ones included |
| [03 — Internationalisation](03_i18n.md) | The locale registry, adding a language |
| [04 — Docker and operations](04_docker.md) | Image, compose, backups, monitoring |
| [05 — Migrating from 2016](05_migration.md) | Taking over `var/urls.db`, wiring KuneAgi |
| [06 — Security](06_security.md) | What is checked, and what is not |
| [07 — Keycloak SSO (planned)](07_sso_keycloak.md) | Roadmap for the next iteration |
| [Audits](audits/README.md) | Security audits, dated and self-contained — one internal, one external |

## In three sentences

The service takes a long address, stores a copy of it and hands back a
short code; it then serves a 302 redirect for that code. The same
address always gives the same code. Everything else — the languages,
the database, the public prefix of the links, the refusal rules — is
configuration.

## What comes from 2016, and what changed

The public contract is preserved: `GET /?url=`, `POST /`, `GET /<code>`
and the code alphabet are identical, so **no short link already handed
out dies**. Underneath it, everything was rebuilt: parameterised
queries, target validation, unpredictable codes, security headers, and
no third-party CDN.

The exhaustive list, deliberate breaks included, is in `CHANGES.txt`.

## Repository conventions

- Code and file names in English; documentation bilingual.
- Commit messages in English, imperative mood.
- Deliveries as a diff applied with `git apply`.
- Three hash-pinned dependency locks: `requirements.lock` (runtime),
  `requirements-test.lock`, `requirements-quality.lock`.
- Any change to a persisted structure **adds** a step in
  `urlshortener/upgrades.py`. A published step is never edited in place.
