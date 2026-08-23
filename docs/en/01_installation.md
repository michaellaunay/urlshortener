# 01 — Installation

## Requirements

Python 3.11 or 3.12. Nothing else: no compiler, no system library, and
no database server for as long as SQLite is enough.

## Development

```bash
git clone https://github.com/michaellaunay/urlshortener.git
cd urlshortener
python3 -m venv .venv
. .venv/bin/activate          # BEFORE the first pip, see below

pip install --require-hashes -r requirements-test.lock
pip install --no-deps -e .

python -m urlshortener.upgrades development.ini   # create the database
pserve development.ini --reload
```

The service listens on <http://localhost:5123/>.

`development.ini` differs from `production.ini` in three ways, and only
three: templates reload, logging is at DEBUG, and the private-target
guard is **off** so that `http://localhost:8080/` can be shortened
while developing.

On Debian and Ubuntu a `pip install` run **before** activation answers
`externally-managed-environment` (PEP 668) and suggests
`--break-system-packages`. Don't take that suggestion: it installs into
the system python. Activating the virtualenv is the right answer; the
prompt then shows `(.venv)`.

### After a patch that touches the locks

A patch can **add a dependency**. The locks then change, and an
environment populated before the patch does not have it. The symptom is
a `ModuleNotFoundError` that kills pytest's whole collection, long
before any test runs.

The reflex, after any patch whose `git apply` touched a
`requirements*.lock`:

```bash
pip install --require-hashes -r requirements-test.lock
python -m pytest -q
```

A test checks that a new dependency is declared **and** locked; no test
can check what is installed in your virtualenv.

## Running the tests

```bash
pytest -q
pytest -q --cov=urlshortener --cov-report=term-missing
```

523 tests, 91% coverage. The three exact quality-CI commands — run
these verbatim before any delivery:

```bash
ruff check urlshortener tests docker
bandit -ll -r urlshortener docker
pip-audit --require-hashes -r requirements.lock
```

## On a server, without Docker

A dedicated service account, a clone pinned to a SHA, a venv inside it,
the data somewhere else:

```
/srv/urlshortener/
├── app/          # the clone, owned by root, read by the service
│   └── .venv/
├── var/          # the SQLite file — owned by the service alone
└── etc/          # production.ini and urlshortener.env, outside git, 0640
```

```bash
sudo useradd --system --home /srv/urlshortener --shell /usr/sbin/nologin urlshortener
sudo -u urlshortener python3 -m venv /srv/urlshortener/app/.venv
sudo -u urlshortener /srv/urlshortener/app/.venv/bin/pip \
     install --require-hashes -r /srv/urlshortener/app/requirements.lock
sudo -u urlshortener /srv/urlshortener/app/.venv/bin/pip \
     install --no-deps /srv/urlshortener/app
```

The systemd unit is **shipped** in the repository, at
`deploy/systemd/urlshortener.service` — rather than copied here, where
it would drift. It already had: the inline version in this chapter and
the shipped file disagreed about `WorkingDirectory`, which is not
cosmetic, since that is where `find_dotenv(usecwd=True)` looks for the
`.env`.

```bash
sudo install -m 0644 deploy/systemd/urlshortener.service /etc/systemd/system/
sudo install -m 0640 -o root -g urlshortener \
     deploy/systemd/urlshortener.env.example /srv/urlshortener/etc/urlshortener.env
$EDITOR /srv/urlshortener/etc/urlshortener.env     # base_url above all
sudo systemctl daemon-reload
sudo systemctl enable --now urlshortener
```

**The environment is read by systemd, not by `python-dotenv`.**
`find_dotenv` walks UP from the working directory; it never descends
into `etc/`, so a `.env` placed where this documentation put it was
**never loaded**. The `EnvironmentFile` makes the operating contract
explicit and removes any dependence on the current directory for
configuration.

**The database path must be absolute.** `production.ini` says
`sqlite:///%(here)s/var/urlshortener.sqlite`, and `%(here)s` is the
directory of the **.ini file** — that is `etc/`, which
`ProtectSystem=strict` makes read-only. The shipped environment file
already sets `SQLALCHEMY_URL` absolute, under `ReadWritePaths`. A test
checks the two agree.

Two things to read there rather than repeat elsewhere:

- `ExecStartPre` is not decorative: the schema must be ready before the
  first request, or the first visitor of a fresh deployment gets a 500.
  It is also the command that failed on every fresh install before
  train 0017.

- Careful with `ProtectHome=true` if the clone lives under `/home`: the
  unit will not see it. Either follow the layout above, or adjust
  `WorkingDirectory`, `ExecStart` and `ProtectHome` together — in the
  shipped file, not in a copy.

## Configuration

Every `urlshortener.*` key of the `.ini` can be overridden by the
matching environment variable. Precedence is
`environment > .ini > default`.

| `.ini` key | Variable | Default | Purpose |
| --- | --- | --- | --- |
| `urlshortener.base_url` | `URLSHORTENER_BASE_URL` | `http://localhost:5123/` | **Public** prefix of the links, trailing slash included |
| `sqlalchemy.url` | `SQLALCHEMY_URL` | SQLite file under `var/` | Database |
| `urlshortener.code_length` | `URLSHORTENER_CODE_LENGTH` | `11` | Length of a fresh code |
| `urlshortener.code_max_attempts` | `URLSHORTENER_CODE_MAX_ATTEMPTS` | `8` | Draws before giving up on a collision |
| `urlshortener.max_url_length` | `URLSHORTENER_MAX_URL_LENGTH` | `2048` | Longest accepted target |
| `urlshortener.max_body_bytes` | `URLSHORTENER_MAX_BODY_BYTES` | `16384` | Largest accepted request body (also caps waitress) |
| `urlshortener.default_scheme` | `URLSHORTENER_DEFAULT_SCHEME` | `http` | Scheme added when missing |
| `urlshortener.allowed_schemes` | `URLSHORTENER_ALLOWED_SCHEMES` | `http https` | Accepted schemes |
| `urlshortener.block_private_targets` | `URLSHORTENER_BLOCK_PRIVATE_TARGETS` | `true` | Refuse literal private addresses |
| `urlshortener.blocked_hosts` | `URLSHORTENER_BLOCKED_HOSTS` | empty | Hosts always refused, subdomains included |
| `urlshortener.count_hits` | `URLSHORTENER_COUNT_HITS` | `true` | Count redirects |
| `urlshortener.enable_legacy_get` | `URLSHORTENER_ENABLE_LEGACY_GET` | `true` | Serve `GET /?url=` (2016) |
| `urlshortener.throttle_max_creations` | `URLSHORTENER_THROTTLE_MAX` | `30` | Creations per window per address |
| `urlshortener.throttle_window_seconds` | `URLSHORTENER_THROTTLE_WINDOW` | `300` | Window length |
| `urlshortener.throttle_max_reads` | `URLSHORTENER_THROTTLE_MAX_READS` | `0` | API reads per window (0 = unlimited) |
| `urlshortener.cors_origins` | `URLSHORTENER_CORS_ORIGINS` | empty | Origins allowed on the API |

### Start-up refuses an impossible configuration

A configuration that cannot work **fails to start**, with the whole
list of problems at once:

```
refusing to start, 2 problem(s) in the configuration:
  - code_length must be between 1 and 32 (got 0)
  - default_scheme 'ftp' is not in allowed_schemes ['http', 'https'] —
    a URL submitted without a scheme could never be accepted
```

Checked: `base_url` absolute, http(s), ending in `/`; the bounds of
`code_length` and `code_max_attempts`; the consistency of
`max_body_bytes` ≥ `max_url_length` + envelope (two values each valid
and jointly impossible); no dangerous scheme in `allowed_schemes`;
`default_scheme` present in that list; a non-zero throttling window
when throttling is on; and the shape of the `cors_origins` entries.

Before, `code_length = 0` started cleanly and failed hours later on the
first shortening, with a `ValueError` about an alphabet — a message
produced by a typo in an .ini file, in a place that says nothing about
where the typo is.

**`base_url` is the one setting that cannot be corrected afterwards
without damage**: it is what gets printed into the links handed out.
Setting it wrong means handing out dead links.
