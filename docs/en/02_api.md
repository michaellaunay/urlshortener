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

It is a **GET that writes**, and three things followed:

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

Since train 0024, the form's `Sec-Fetch-Site` guard (D-02) applies
here too: a **browser-borne cross-site** call — a third-party page's
`<img>` tag, a prefetch — gets `403` with the `error_cross_site`
identifier, in the 2016 body shape, and neither creates anything nor
spends the visitor's budget. A server-side caller (KuneAgi, `curl`)
sends no such header and passes as before. Refusals log a line of
their own (`legacy GET /?url= refused: cross-site`) and do not count
as uses: the switch-off criterion below stays clean. What remains,
unfixable while keeping it: the side-effecting GET for non-browser
clients, and the query-string target (2).

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
known (`created: false`).

**`Content-Type: application/json` is required.** A `POST` in
`application/x-www-form-urlencoded` answers `415`. This is not a
formality: form encodings are CORS-*simple* content types, so a
third-party page can post them **with no preflight** — and the
preflight is exactly where the origin list is enforced. Requiring JSON
is what makes `urlshortener.cors_origins` mean something.

The one-line curl stays one line:

```bash
curl -X POST https://example.org/api/v1/shorten \
     -H 'Content-Type: application/json' -d '{"url":"https://example.org/x"}'
```

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
| `error_cross_site` | 403 | Creation submitted from another site (`Sec-Fetch-Site`) |
| `error_url_not_whitelisted` | 403 | Target outside the allow-list (API/legacy; the form offers e-mail delivery) |
| `error_email_invalid` | 400 | Malformed e-mail address (form) |
| `error_mail_failed` | 503 | The SMTP relay refused; nothing was delivered |
| `error_content_type_required` | 415 | API called without `Content-Type: application/json` |
| `error_body_too_large` | 413 | Request body beyond `max_body_bytes` |
| `error_rate_limited` | 429 | Creation limit reached |
| `error_code_exhausted` | 503 | No free code — raise `code_length` |
| `error_unknown_code` | 404 | Unknown code (API v1) |
| `error_link_blocked` | 410 | Link stopped by the administrator |
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


## Allow-list and delivery by e-mail

As soon as `urlshortener.whitelist` is non-empty, a target outside the
list no longer gets its link on screen: the form asks for an e-mail
address and **the link goes to the mailbox**, not to the page — showing
it would make the field decorative. The three entry forms and the
"empty list allows everything" semantics are in
[Installation](01_installation.md); matching runs on the **canonical**
form, so the IDNA rules apply to the list exactly as to the target.

The API and `GET /?url=` offer no e-mail step: an integration belongs
**on** the list, which is what the list is for. Answer: `403`
`error_url_not_whitelisted`.

The delivered address is **stored** on the link (`requested_by_email`)
and visible to the administrator: that is the accountability the step
exists to provide, and it is a personal datum — said here rather than
discovered.

## Administration

`GET /admin` — list, search (`?q=`: exact code or target fragment),
pagination. `POST /admin/action` with `code` and `action` (`block`,
`unblock`, `delete`).

Authentication is **HTTP Basic** against
`urlshortener.admin_password_hash` (produced by
`python -m urlshortener.tools.hash_password`); no hash configured = the
area answers **404**, not 401 — a login door that exists is a door to
knock on. TLS is assumed: the whole service is documented behind nginx.

**Blocking beats deleting**, and is the recommended action for a
litigious link: the row stays, the redirect answers `410`, and
de-duplication hands the *blocked* link back to whoever re-shortens the
same URL — after a delete, the same target is one `POST` away from a
fresh code.

On `/admin/action` the `Sec-Fetch-Site` guard **fails closed**, unlike
public creation: Basic credentials ride on any request a hostile page
makes the browser send. A script driving the admin must say
`-H 'Sec-Fetch-Site: none'` on purpose.
