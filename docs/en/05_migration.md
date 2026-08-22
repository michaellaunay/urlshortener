# 05 — Migrating from the 2016 service

## What is taken over

The 2016 service keeps everything in one table:

```sql
CREATE TABLE WEB_URL(
    ID  INTEGER PRIMARY KEY AUTOINCREMENT,
    NUM TEXT NOT NULL UNIQUE,
    URL TEXT NOT NULL UNIQUE)
```

`NUM` is the short code. It is printed on other people's pages, in
other people's emails, in KuneAgi content. **It is imported verbatim**:
a re-minted code is a dead link.

URLs are imported verbatim too, and that is a choice. Running them
through `normalise_url` would "fix" some of them — and a fixed URL is a
different destination from the one the link has been promising for ten
years. Unservable rows (scheme outside the allowlist, control
characters, illegal code) are **reported and skipped**, never silently
rewritten: the list goes back to the operator, who decides.

## Procedure

```bash
# 1. copy the production file; the old service may keep running
docker cp <legacy_container>:/app/var/urls.db ./urls.db
sha256sum urls.db | tee urls.db.sha256

# 2. rehearsal — writes nothing, says everything
python -m urlshortener.tools.import_legacy production.ini urls.db --dry-run

# 3. the real import
python -m urlshortener.tools.import_legacy production.ini urls.db
```

Output:

```
rows read              : 1428
imported               : 1425
already present        : 0
duplicate target URL   : 0
rejected               : 3
  REJECTED bb2          scheme:javascript  javascript:alert(1)
  REJECTED cc3          scheme:ftp         ftp://example.org/file
  REJECTED dd/4         bad_code           https://example.org/x
```

The import is **idempotent**: a code already present is left alone and
counted as `already present`. An interrupted import resumes by
re-running it.

The legacy file is opened `mode=ro`, so the old service can keep
serving during the operation.

## Checks before switching over

```bash
# the link count matches
curl -fsS http://127.0.0.1:5123/healthz

# an old code, picked at random, resolves to the right target
sqlite3 urls.db "SELECT NUM, URL FROM WEB_URL ORDER BY random() LIMIT 5"
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://127.0.0.1:5123/<NUM>
```

That check is the one that matters. The rest can wait; an old link that
no longer resolves cannot.

## Wiring KuneAgi

The existing vhost does:

```nginx
location /urlmetadata/ {
    rewrite    /urlmetadata/(.*) /$1 break;
    proxy_pass http://urlmetadataws;
}
upstream urlmetadataws { server 127.0.0.1:5123; }
```

The prefix is stripped before forwarding: the application sees `/` and
`/<code>` and needs to know nothing about the mount point.
`urlshortener.base_url`, however, must carry the **public** prefix:

```
URLSHORTENER_BASE_URL=https://publicpolicies.cosmopolitical.coop/urlmetadata/
```

Switching over: stop the old service, start the new one on the same
port, `upstream` unchanged. Rollback in ten seconds by restarting the
old container — which is why it should not be deleted straight away.

A related operational point: KuneAgi's legacy container hosts this
service on 5123. Until the switch-over has happened, shutting it down
takes `/urlmetadata/` with it.

## Visible differences after the switch

- An unknown code answers `404` instead of `200`. Monitoring that
  counted 200s will notice — that is the point.
- A refused URL answers `400`. The JSON body keeps its shape.
- No more `Access-Control-Allow-Origin: *`: fill in
  `urlshortener.cors_origins` if a third-party script called the
  service from a browser.
- New codes are 7 characters and drawn at random; old ones keep their
  original length. The two coexist without difficulty — same alphabet.
