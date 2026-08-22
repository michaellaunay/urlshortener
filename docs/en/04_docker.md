# 04 — Docker and operations

## Starting

Every command is run from the **repository root**.

```bash
./docker/init.sh          # creates docker/.env — once
$EDITOR docker/.env       # URLSHORTENER_BASE_URL above all
docker compose --env-file docker/.env -f docker/docker-compose.yaml up -d --build
docker compose -f docker/docker-compose.yaml logs -f
```

## What the image does

A two-stage build:

- **builder**: venv, runtime lock installed in `--require-hashes` mode
  (a substituted package fails the build), then the application
  installed **as a wheel**;
- **runtime**: receives only the venv and an explicit allowlist of
  configuration files — never `COPY .`.

Points fixed on purpose:

- base image pinned by **digest**, not by tag. The digest is the one
  already verified and in production in the AlirPunkto stack: both
  services sit on one identical, known base;
- `--only-binary=:all:` with **one** named exception,
  `pyramid-chameleon`, which is sdist-only on PyPI but pure python. No
  compiler in any stage; a future sdist outside that list fails the
  build instead of quietly dragging a toolchain in;
- runs as the unprivileged `urlshortener` user (uid 1002), with
  `no-new-privileges`;
- `HEALTHCHECK` on `/healthz`, which does a real database round-trip;
- optional strict reproducibility: `URLSHORTENER_UBUNTU_SNAPSHOT` pins
  apt against `snapshot.ubuntu.com`.

## The entrypoint

`docker/start_urlshortener.sh`:

1. moves into `APP_HOME` — not decorative. `find_dotenv()` walks up
   from the **calling file**; with the application installed as a
   wheel, that walk would start inside `site-packages` and never cross
   the deployment's `.env`. That is exactly the failure that stopped
   AlirPunkto from booting after its switch to a wheel. The code uses
   `find_dotenv(usecwd=True)`, and the `cd` supplies the expected
   working directory;
2. derives `var/runtime.ini` from `production.ini` through
   `docker/apply_server_overrides.py`. PasteDeploy does **not** pass
   `global_conf` down to `[server:main]` — a dead end proven elsewhere
   — so `listen` is rewritten in a copy rather than frozen into the
   versioned file, which stays correct for bare metal;
3. applies the schema steps **before** serving. Done lazily, the first
   visitor of a fresh deployment would get a 500;
4. `exec pserve`, so waitress is PID 1 and receives signals.

`tests/test_docker_conventions.py` locks all of it: digest present,
`--require-hashes` present, test and quality locks **absent** from the
image, `USER` after the last `chown`, migration-before-service order,
loopback-only publishing, and above all: **`.dockerignore` does not
exclude `docker/`**. That is the exact latent failure AlirPunkto
shipped — the directory was ignored, the helper called at start-up was
therefore never copied, and the container died on its first launch,
long after the build had been declared green.

## Networking

The service is published on `127.0.0.1:5123` only. What faces the
network is the reverse proxy.

```nginx
location / {
    proxy_pass http://127.0.0.1:5123;
    proxy_http_version 1.1;
    proxy_set_header Host              $http_host;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_redirect off;
}

# The real rate limit belongs here, not in the application process
# (see 06_security.md).
limit_req_zone $binary_remote_addr zone=shorten:10m rate=10r/m;
location = / {
    limit_req zone=shorten burst=20 nodelay;
    proxy_pass http://127.0.0.1:5123;
}
```

So that `request.client_addr` is the visitor and not the proxy,
`production.ini` already carries `trusted_proxy`,
`trusted_proxy_headers` and `clear_untrusted_proxy_headers = true`.
Without those three lines the limiter counts every request against one
address: the proxy's.

## Backups

The whole state of the service is one file. Losing it kills every link
ever handed out.

```bash
./docker/backup.sh urlshortener ./backups
# restore
sqlite3 urlshortener.sqlite < backups/urlshortener-20260822T101500Z.sqlite
```

The script goes through `sqlite3 .backup` rather than `cp`: copying a
file while it is being written yields a snapshot that may not be
consistent. And a backup nobody has restored is not a backup — rehearse
the restore, outside an incident.

## Monitoring

```bash
curl -fsS http://127.0.0.1:5123/healthz
docker inspect --format '{{.State.Health.Status}}' urlshortener
docker compose -f docker/docker-compose.yaml logs --since 1h
```

The application log is at INFO; `sqlalchemy.engine` is at WARN (setting
it to INFO writes out every statement, shortened URLs included).

## Upgrading

```bash
git fetch && git reset --hard <sha>
docker compose --env-file docker/.env -f docker/docker-compose.yaml up -d --build
```

The volume survives. Schema steps apply themselves at start-up.
Rolling back means restarting on the previous SHA — but **only** if no
schema step was crossed in between; otherwise restore the backup.
