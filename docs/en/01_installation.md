# 01 — Installation

## Requirements

Python 3.11 or 3.12. Nothing else: no compiler, no system library, and
no database server for as long as SQLite is enough.

## Development

```bash
git clone https://github.com/michaellaunay/urlshortener.git
cd urlshortener
python3 -m venv .venv
. .venv/bin/activate

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

## Running the tests

```bash
pytest -q
pytest -q --cov=urlshortener --cov-report=term-missing
```

170 tests, 89% coverage. The three exact quality-CI commands — run
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
└── etc/          # production.ini and .env, outside git, 0640
```

```bash
sudo useradd --system --home /srv/urlshortener --shell /usr/sbin/nologin urlshortener
sudo -u urlshortener python3 -m venv /srv/urlshortener/app/.venv
sudo -u urlshortener /srv/urlshortener/app/.venv/bin/pip \
     install --require-hashes -r /srv/urlshortener/app/requirements.lock
sudo -u urlshortener /srv/urlshortener/app/.venv/bin/pip \
     install --no-deps /srv/urlshortener/app
```

A minimal systemd unit:

```ini
[Unit]
Description=urlshortener
After=network-online.target

[Service]
User=urlshortener
WorkingDirectory=/srv/urlshortener/app
ExecStartPre=/srv/urlshortener/app/.venv/bin/python -m urlshortener.upgrades /srv/urlshortener/etc/production.ini
ExecStart=/srv/urlshortener/app/.venv/bin/pserve /srv/urlshortener/etc/production.ini
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/srv/urlshortener/var
UMask=0027

[Install]
WantedBy=multi-user.target
```

`ExecStartPre` is not decorative: the schema must be ready before the
first request, or the first visitor of a fresh deployment gets a 500.

Careful with `ProtectHome=true` if the clone lives under `/home`: the
unit will not see it. Either follow the layout above, or adjust
`WorkingDirectory`, `ExecStart` and `ProtectHome` together.

## Configuration

Every `urlshortener.*` key of the `.ini` can be overridden by the
matching environment variable. Precedence is
`environment > .ini > default`.

| `.ini` key | Variable | Default | Purpose |
| --- | --- | --- | --- |
| `urlshortener.base_url` | `URLSHORTENER_BASE_URL` | `http://localhost:5123/` | **Public** prefix of the links, trailing slash included |
| `sqlalchemy.url` | `SQLALCHEMY_URL` | SQLite file under `var/` | Database |
| `urlshortener.code_length` | `URLSHORTENER_CODE_LENGTH` | `11` | Length of a fresh code |
| `urlshortener.max_url_length` | `URLSHORTENER_MAX_URL_LENGTH` | `2048` | Longest accepted target |
| `urlshortener.max_body_bytes` | `URLSHORTENER_MAX_BODY_BYTES` | `16384` | Largest accepted request body (also caps waitress) |
| `urlshortener.default_scheme` | `URLSHORTENER_DEFAULT_SCHEME` | `http` | Scheme added when missing |
| `urlshortener.allowed_schemes` | `URLSHORTENER_ALLOWED_SCHEMES` | `http https` | Accepted schemes |
| `urlshortener.block_private_targets` | `URLSHORTENER_BLOCK_PRIVATE_TARGETS` | `true` | Refuse literal private addresses |
| `urlshortener.blocked_hosts` | `URLSHORTENER_BLOCKED_HOSTS` | empty | Hosts always refused, subdomains included |
| `urlshortener.count_hits` | `URLSHORTENER_COUNT_HITS` | `true` | Count redirects |
| `urlshortener.throttle_max_creations` | `URLSHORTENER_THROTTLE_MAX` | `30` | Creations per window per address |
| `urlshortener.throttle_window_seconds` | `URLSHORTENER_THROTTLE_WINDOW` | `300` | Window length |
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
