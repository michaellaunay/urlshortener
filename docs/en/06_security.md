# 06 — Security

This chapter says what is checked, and above all what is not. A
shortener is an open redirection tool: its attack surface is where it
sends people.

## What the 2016 service did

Four defects, all fixed, all named here because they describe exactly
what the tests protect today.

1. **SQL injection.** Statements were built with `.format()`:
   `INSERT INTO WEB_URL (URL, NUM) VALUES ('{url}', '{num}')`. One
   apostrophe in the URL was enough. Everything now goes through
   parameterised statements via SQLAlchemy.
2. **No target validation.** `javascript:alert(1)`,
   `data:text/html;base64,…`, `file:///etc/passwd`,
   `http://127.0.0.1:6543/admin` were accepted, stored, and later
   served in `Location:`.
3. **Sequential codes.** The counter went `0, 1, … 9, a, … z, A, …`.
   Knowing one code gave the next; the whole corpus could be walked in
   a few thousand requests.
4. **Third-party CDN.** The page pulled Bootstrap and Font Awesome from
   maxcdn on every view, which told a third party who was reading what.

## What is checked today

**Scheme**: `http` / `https` allowlist. Everything else is refused.

**Authority**: no credentials (`https://your-bank.example@evil.test/` —
the visitor reads what is before the `@`, the browser goes to what is
after). Hostname syntax checked, IDNA form accepted, IPv6 literal
validated.

**Control characters**: refused at the door. A carriage return in a
stored URL becomes a header-injection attempt the day it is written
into `Location:`.

**Private addresses**: `127.0.0.1`, `10/8`, `192.168/16`, `169.254/16`
(cloud metadata), `::1`, `localhost` are refused by default.
`urlshortener.block_private_targets = false` lifts the guard for a
purely internal service.

**Codes**: drawn from `secrets`, 62⁷ possibilities at the default
length, collisions handled with a SAVEPOINT and a fresh draw.

**Headers**: CSP with `frame-ancestors 'none'` (a shortener page framed
inside another site is a phishing aid), `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy: no-referrer` on the redirect,
`Cache-Control: no-store` so a link stays revocable.

**CORS**: nothing by default, an explicit list otherwise.

**Supply chain**: three hashed locks, installation with
`--require-hashes`, base image pinned by digest, `pip-audit` in CI.

## What is not checked — and why

**No DNS resolution, no request to the target.** A resolution performed
at creation time says nothing about where the name will point at
redirect time: paying for it would buy a false sense of safety. So
`http://internal.example.com` passes even if it resolves to
`10.0.0.5`. Only numeric literals are caught. That is an accepted
limit, tested explicitly (`test_a_name_is_never_resolved`).

**No reputation check.** The service does not know whether a target
hosts malware. A public shortener will eventually serve a phishing
link; plan a takedown procedure (`DELETE FROM links WHERE code = ?`),
not a magic filter.

**The built-in rate limit is a courtesy, not a defence.** It lives in
the process: N workers allow N times the advertised rate, and a restart
forgets everything. It stops a stuck script. The real limit is in the
reverse proxy — `limit_req`, example in chapter 04.

**No CSRF.** There is no session, no account, no privileged action: a
CSRF token would protect nothing and would break clients written
against `POST /` in 2016. That changes with Keycloak SSO (chapter 07):
the day an action is tied to an identity, the token becomes mandatory.

## Privacy

**No IP address is written to the database.** Otherwise the link table
would be a record of who published and read what. The throttling window
keeps addresses in memory for at most the window length, then drops
them.

What is kept per link: the target, the code, the creation date, a visit
counter, the date of the last visit. The counter can be switched off
(`urlshortener.count_hits = false`).

The application log does not write shortened URLs at INFO. Setting
`sqlalchemy.engine` to INFO would write all of them — avoid that in
production.

## Audits

- [22 August 2026 — internal audit](../fr/audits/20260822_audit_securite_interne.md)
  (French; English mirror pending): one high finding (S-01, a
  non-ASCII target served raw in `Location:` — a permanent 500 or a
  mangled redirect), three medium, six low, four accepted risks. Every
  fixable finding was fixed, each with its own regression test.

## Reporting a vulnerability

`michaellaunay@logikascium.com`. Please do not open a public issue
before a fix is available.
