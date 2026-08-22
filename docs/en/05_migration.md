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
years. `normalise_url` is therefore used as a **judge** and never as a
transformer: its return value is discarded, only its verdict counts.

### Two kinds of refusal

They call for different actions, which is why the report separates
them.

**Unfixable** — the row cannot work, or must not. No flag lifts these:

| Reason | What it means |
| --- | --- |
| `bad_code` | Not in the code alphabet |
| `reserved_code` | **A route already answers on that path** |
| `empty_url` | No target |
| `control_chars` | A carriage return becomes header injection |
| `scheme:javascript` (and `data`, `vbscript`) | Would put an attack vector in a `Location:` under your own domain |

`reserved_code` deserves a word: `healthz` is seven characters of the
alphabet, so `is_valid_code` called it legal and it imported cleanly —
into a row the redirect view will never be asked about, because
`/healthz` is a route. `tests/test_routes.py` already asserts that no
route may shadow a code; the import was the door left open. The tool
**reports and stops** rather than renaming: a renamed code is a dead
link, and only you can weigh a dead link against an unreachable one.
The two ways out are accepting the loss, or moving the route.

**Policy** — the link works perfectly well; only the 2.x rules would
not have created it today: a scheme outside the allowlist (`ftp:`), a
private target, a blocked host, an invalid port, an over-long URL.
Those you can take back knowingly:

```bash
python -m urlshortener.tools.import_legacy production.ini urls.db --allow-unsafe-legacy
```

The flag lifts **exactly** the policy refusals and never the others: a
flag that can import an XSS vector is not a flag, it is a trap laid for
a future operator in a hurry.

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
refused (unfixable)    : 2
refused (policy)       : 2
  REFUSED  bb2            scheme:javascript            javascript:alert(1)
  REFUSED  healthz        reserved_code                https://example.org/x
  POLICY   cc3            error_url_scheme:ftp         ftp://example.org/file
  POLICY   dd4            error_url_private:127.0.0.1  http://127.0.0.1/admin
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
