# 02 — API and routes

Every route is served at the root of the service. Behind a reverse
proxy prefix (`location /urlmetadata/` at KuneAgi, which strips the
prefix before forwarding), the application still sees `/` and
`/<code>`; it is `urlshortener.base_url` that must then carry the
public prefix.

## Route order

`/{code}` matches almost anything, so it is registered **last**. Every
top-level path (`api`, `healthz`, `static`, `locale`) is also listed in
`codec.RESERVED_CODES` — otherwise, the day a draw produced the code
`api`, that link would be unreachable forever.
`tests/test_routes.py` compares the two lists.

## Entry points inherited from 2016

Kept character for character, and locked by
`tests/test_legacy_compat.py`. These are what already-written clients
read.

### `GET /?url=<target>`

Creates the link (or finds the existing one) and answers JSON.

```bash
curl 'https://example.org/?url=https://en.wikipedia.org/wiki/Cooperative'
```

```json
{
  "short_url": "https://example.org/k3Bq7xZ",
  "code": "SUCCESS",
  "original_url": "https://en.wikipedia.org/wiki/Cooperative"
}
```

On refusal, the 2016 shape is preserved:

```json
{ "code": "ERROR", "error": "error_url_scheme", "original_url": "javascript:alert(1)" }
```

Two deliberate departures: the HTTP status is now `400` (instead of
`200`), and `error` carries a stable identifier rather than an English
sentence — branch on the identifier, display the message.

#### This entry point is on its way out

It is a **GET that writes**, and three things follow, none of which is
fixable while keeping it:

1. browser prefetch, crawlers, scanners and a plain `<img src="…">` on
   any third-party page all create links — at the **visitor's** address
   rather than the author's, which also spreads the rate limit across
   strangers;
2. the target lands in a **query string**, and therefore in the nginx
   access log, the browser history, and whatever monitoring reads
   either. A password-reset URL shortened this way is written in the
   clear in three places. `POST /api/v1/shorten` puts it in a body,
   which none of the three records;
3. no preflight stands between a third-party page and it.

It stays **on by default**: KuneAgi calls it, and this project's first
promise is that nothing written against the 2016 service breaks. Every
answer therefore carries:

```http
Deprecation: true
Link: <https://example.org/api/v1/shorten>; rel="successor-version"
```

and every use logs a line at INFO. That is what makes switching it off
a decision rather than a gamble:

```bash
journalctl -u urlshortener --since '30 days ago' | grep -c 'legacy GET /?url= used'
```

Zero for a month? Then `urlshortener.enable_legacy_get = false`. The
entry point answers **410 Gone**, keeping the 2016 body shape so an old
client's parser reads the refusal instead of choking on it:

```json
{ "code": "ERROR", "error": "error_legacy_get_disabled", "original_url": "…" }
```

### `POST /` (form)

Field `url`. Answers the HTML page carrying the short link. This is
what the service's own form submits.

### `GET /<code>`

Answers `302` to the target, with `Referrer-Policy: no-referrer` (the
destination site does not learn which short link brought the visitor)
and `Cache-Control: no-store` (a link stays revocable).

Unknown code: `404`. In 2016 it was `200` with an error page, which no
monitor could tell apart from a success.

`HEAD` works too.

## JSON API v1

### `POST /api/v1/shorten`

```bash
curl -X POST https://example.org/api/v1/shorten \
     -H 'Content-Type: application/json' \
     -d '{"url": "https://example.org/a/very/long/page"}'
```

```json
{
  "code": "k3Bq7xZ",
  "short_url": "https://example.org/k3Bq7xZ",
  "url": "https://example.org/a/very/long/page",
  "created_at": "2026-08-22T10:15:00+00:00",
  "hits": 0,
  "created": true
}
```

`201` when the link was just created, `200` when the target was already
known (`created: false`). A `POST` in
`application/x-www-form-urlencoded` with a `url` field is accepted too:
`curl -d url=...` is every operator's first move.

### `GET /api/v1/links/{code}`

The public facts about one code. **Does not count as a visit**: a link
can be monitored without skewing its counter.

### `GET /healthz`

```json
{ "status": "ok", "links": 1428 }
```

Performs a real database round-trip (`SELECT 1`), so an unreachable
database shows. This is the image's `HEALTHCHECK` probe.

## Errors

| Identifier | Status | Cause |
| --- | --- | --- |
| `error_url_required` | 400 | Field absent or empty |
| `error_url_too_long` | 400 | Beyond `max_url_length` |
| `error_url_scheme` | 400 | Scheme outside the allowlist (`javascript:`, `data:`, `file:`, `ftp:`…) |
| `error_url_host` | 400 | Host absent, syntactically invalid, or numeric-looking without being an address |
| `error_url_port` | 400 | Port out of range or not a number |
| `error_url_credentials` | 400 | Credentials in the authority (`https://bank@evil.test/`) |
| `error_url_private` | 400 | Literal private, loopback or link-local address |
| `error_url_blocked` | 400 | Host on the block list |
| `error_url_control_characters` | 400 | Control characters |
| `error_body_too_large` | 413 | Request body beyond `max_body_bytes` |
| `error_rate_limited` | 429 | Creation limit reached |
| `error_code_exhausted` | 503 | No free code — raise `code_length` |
| `error_unknown_code` | 404 | Unknown code (API v1) |
| `error_legacy_get_disabled` | 410 | `GET /?url=` switched off by configuration |

These identifiers are also the `msgid` values of the translation
catalogue: the interface shows them translated, the API returns them
raw.

## CORS

Nothing is sent by default. In 2016 the service answered
`Access-Control-Allow-Origin: *` to everyone, always. Fill in
`urlshortener.cors_origins` with the list of origins — or `*` if the
service really is public.

## Language

`?_LOCALE_=fr` on any page, or `GET /locale/fr`, which sets a
`_LOCALE_` cookie for a year. Failing that, `Accept-Language` is
negotiated, then English.
