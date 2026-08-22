# 07 — Keycloak SSO (next iteration)

Nothing in this chapter is implemented. It is written now so that the
structural decisions are taken before the code, not after it.

## The need

Today the service is entirely anonymous: anyone shortens, nobody
administers. Two things are missing:

- **administration** — list, search, revoke a link (phishing, mistake,
  takedown request);
- **attribution** — knowing which member created which link, for links
  created from KuneAgi or AlirPunkto.

Both needs have the same answer: the Keycloak already in place, the one
serving AlirPunkto and KuneAgi, with members federated from LDAP.

## What is already in place to receive it

- The service has **no session** today, so there is nothing to dismantle.
- The views are thin: the rules live in `services.py`, which knows
  nothing about HTTP. Adding an identity does not touch them.
- `RESERVED_CODES` and `tests/test_routes.py` guarantee that adding
  `/admin` will not make an existing link unreachable — provided
  `admin` is added to the list, which the test demands.

## Intended shape

Reuse the OIDC plugin written for KuneAgi (`novaideo/oidc_sso.py`):
authorisation code flow, cached `.well-known` discovery, single-use
`state` and `nonce`, validation of `iss` / `aud` / `exp` / `nonce`,
cross-checking the `sub` through UserInfo.

A principle already held in both projects, to hold here too: **the SSO
routes are registered only if `oidc_sso.*` is configured**. Without
configuration the plugin is inert and the service stays exactly what it
is today. A deployment with no Keycloak must see nothing change.

## Decisions to take before writing a line

1. **Does creation stay anonymous?** Three options: (a) anonymous as
   today, authentication only for administration; (b) authentication
   required, which breaks `GET /?url=` and therefore the current
   KuneAgi integration; (c) anonymous with a quota, authenticated
   without one. **(c) looks like the right trade-off, to be confirmed.**

2. **Which role model?** An `urlshortener-admin` role in Keycloak, or a
   derivation from the existing AlirPunkto groups? The second avoids
   one more directory, the first stays readable.

3. **What is stored about the creator?** The OIDC `sub` is a stable
   pseudonym and is enough to answer "who created this link". Adding
   the email or the pseudonym would turn the table into a directory.
   **Recommendation: the `sub` alone and nothing else**, with a
   dedicated schema step and a nullable column — links imported from
   2016 have no creator, and never will.

4. **CSRF becomes mandatory.** As soon as an action is tied to an
   identity, `POST /admin/...` must carry a token. The question is
   whether anonymous `POST /` stays exempt (probably yes, or the 2016
   clients break).

5. **Logout.** Local only, as in the KuneAgi plugin, or propagated to
   Keycloak?

## Planned steps

1. Schema step 2: nullable `created_by_sub` column, index included.
2. OIDC plugin, inert by default, routes `/oidcsso/login` and
   `/oidcsso/callback`.
3. Administration views behind a role check: list, search by code or by
   target, revoke.
4. A revocation log — who, when, why. A revocation without a trace is a
   failure indistinguishable from an incident.
5. Bilingual documentation and tests, including an end-to-end scenario
   against a test Keycloak.

## What will not change

The redirect stays anonymous, with no cookie and no session: a visitor
following a short link does not have to authenticate, and the service
does not have to know who they are.
