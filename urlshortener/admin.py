# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""The administrator's page: see every link, stop the litigious ones.

Authentication is HTTP Basic against a PBKDF2 hash from the
configuration — no session, no account table, one operator. TLS is
assumed, since the whole service is documented behind nginx.

Two deliberate asymmetries with the public side:

* the Sec-Fetch-Site guard here fails CLOSED. Public creation fails
  open because curl sends no such header and the attack lives in
  browsers; an ADMIN action is exactly the case the security chapter
  warned about, and a script driving it must say `-H 'Sec-Fetch-Site:
  none'` on purpose rather than benefit from silence.
* with no `admin_password_hash` configured the area answers 404, not
  401: a login door that exists is a door to knock on.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging

from pyramid.httpexceptions import HTTPForbidden, HTTPNotFound, HTTPSeeOther
from pyramid.view import view_config

from .constants_and_globals import AVAILABLE_LANGUAGES, LANGUAGE_NAMES
from .services import block_link, delete_link, find_by_code, list_links, unblock_link
from .views import ALLOWED_FETCH_SITES

log = logging.getLogger(__name__)

#: One page of links. Deliberately modest: this is a reading room, not
#: an export facility.
PAGE_SIZE = 50


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of `password` against `pbkdf2$iter$salt$hex`."""
    try:
        scheme, iterations, salt, expected = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def require_admin(request) -> None:
    """Raise unless the request carries the admin credential.

    404 when the feature is off, 401 with a challenge when it is on and
    the credential is wrong or absent. The username half of Basic is
    ignored on purpose: there is one administrator, and pretending
    otherwise would only invent a second secret to mismanage.
    """
    stored = request.app_settings.admin_password_hash
    if not stored:
        raise HTTPNotFound()
    header = request.headers.get("Authorization", "")
    password = None
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
            password = decoded.split(":", 1)[1] if ":" in decoded else decoded
        except (binascii.Error, UnicodeDecodeError):
            password = None
    if password is None or not verify_password(password, stored):
        response = HTTPForbidden()
        response.status_int = 401
        response.headers["WWW-Authenticate"] = 'Basic realm="urlshortener admin"'
        raise response


def _admin_context(request, **extra):
    query = (request.params.get("q") or "").strip()
    try:
        page = max(0, int(request.params.get("page", "0")))
    except ValueError:
        page = 0
    links = list_links(
        request.dbsession, query=query, limit=PAGE_SIZE + 1, offset=page * PAGE_SIZE
    )
    context = {
        # The layout macro's own needs.
        "languages": [(code, LANGUAGE_NAMES[code]) for code in AVAILABLE_LANGUAGES],
        "current_locale": request.locale_name,
        "settings": request.app_settings,
        "link_count": None,
        "links": links[:PAGE_SIZE],
        "query": query,
        "page": page,
        "has_next": len(links) > PAGE_SIZE,
        "page_size": PAGE_SIZE,
        "short_url": request.app_settings.short_url,
        "admin_error": None,
    }
    context.update(extra)
    return context


@view_config(route_name="admin", request_method="GET", renderer="templates/admin.pt")
def admin_page(request):
    require_admin(request)
    return _admin_context(request)


@view_config(route_name="admin_action", request_method="POST",
             renderer="templates/admin.pt")
def admin_action(request):
    """Block, unblock or delete one link.

    POST only, and the Sec-Fetch-Site guard FAILS CLOSED: Basic
    credentials are attached by the browser to any request a hostile
    page makes it send, which is the textbook CSRF this project's own
    security chapter says the public guard is no substitute against.
    """
    require_admin(request)
    site = (request.headers.get("Sec-Fetch-Site") or "").strip().lower()
    if site not in ALLOWED_FETCH_SITES:
        log.info("admin action refused: Sec-Fetch-Site=%r", site)
        raise HTTPForbidden("cross-site or unstated origin")

    code = (request.POST.get("code") or "").strip()
    action = (request.POST.get("action") or "").strip()
    link = find_by_code(request.dbsession, code)
    if link is None:
        request.response.status_int = 404
        return _admin_context(request, admin_error="unknown code %r" % code)
    if action == "block":
        block_link(request.dbsession, link)
        log.info("admin blocked %s", link.code)
    elif action == "unblock":
        unblock_link(request.dbsession, link)
        log.info("admin unblocked %s", link.code)
    elif action == "delete":
        delete_link(request.dbsession, link)
        log.info("admin deleted %s", link.code)
    else:
        request.response.status_int = 400
        return _admin_context(request, admin_error="unknown action %r" % action)
    # RETURNED, not raised: pyramid_tm reads a raised exception —
    # HTTP redirects included — as a failure and ABORTS the
    # transaction, which silently undoes the very block or delete the
    # administrator just performed. Returned, it is a response like any
    # other and the transaction commits.
    return HTTPSeeOther(
        request.route_path("admin", _query={"q": request.POST.get("q", "")})
    )
