# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""JSON API, version 1.

The 2016 service had exactly one machine-readable entry point, and it
was a GET with a side effect: `GET /?url=...` created a row. That
endpoint is kept for the clients already using it (see `views.py`), but
new integrations should use these:

    POST /api/v1/shorten      {"url": "..."} -> 201 (or 200 if known)
    GET  /api/v1/links/{code}                -> the link's public facts

Errors carry a stable `error` identifier plus a human-readable
`message`; branch on the identifier, show the message.
"""
from __future__ import annotations

import logging

from pyramid.httpexceptions import HTTPNoContent
from pyramid.view import view_config

from .services import CodeExhausted, create_link, find_by_code
from .views import body_too_large, cross_site_creation
from .urlvalidation import InvalidURL

log = logging.getLogger(__name__)


def _is_json_request(request) -> bool:
    """True when the caller declared a JSON body.

    Checked on the declared type rather than by sniffing the body: what
    matters is what the BROWSER was willing to send, and a browser only
    skips the preflight for the three simple content types.
    """
    declared = (request.content_type or "").split(";", 1)[0].strip().lower()
    return declared == "application/json" or declared.endswith("+json")


def _link_json(request, link, created=None):
    payload = {
        "code": link.code,
        "short_url": request.app_settings.short_url(link.code),
        "url": link.url,
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "hits": int(link.hits or 0),
    }
    if created is not None:
        payload["created"] = created
    return payload


def _error(request, status, identifier, message, **extra):
    request.response.status_int = status
    payload = {"error": identifier, "message": message}
    payload.update(extra)
    return payload


@view_config(route_name="api_shorten", request_method="POST", renderer="json")
def api_shorten(request):
    """Create (or find) a short link for a target URL."""
    # BEFORE the throttle, and long before `request.body` is touched:
    # an oversized body must cost nothing to refuse (external audit
    # C-04).
    if body_too_large(request):
        return _error(request, 413, "error_body_too_large", "That request is too large.")

    # JSON ONLY, from here on (external audit, second pass, D-02).
    #
    # Train 0009 documented `curl -d url=...` as a convenience, and it
    # was one — but `application/x-www-form-urlencoded` is a
    # CORS-simple content type, so a form on any third-party page could
    # post to this endpoint with no preflight, creating links at its
    # visitors' addresses. `application/json` cannot be sent
    # cross-origin without a preflight, and the preflight is where the
    # origin list is enforced. Requiring JSON is therefore not a
    # formality: it is what makes the CORS configuration mean
    # something.
    #
    # This is a break in a v1 API I shipped and documented. It is one
    # day old and has no known caller; the convenience is restored, for
    # the same one-line curl, by sending a Content-Type.
    if not _is_json_request(request):
        return _error(
            request, 415, "error_content_type_required",
            "Send application/json. Form encodings are refused because they "
            "can be posted cross-origin without a preflight.",
        )

    if cross_site_creation(request):
        return _error(
            request, 403, "error_cross_site",
            "Cross-site creation is refused.",
        )

    if not request.throttle.allow(request.client_addr or "unknown"):
        return _error(request, 429, "error_rate_limited", "Too many requests.")

    try:
        body = request.json_body if request.body else {}
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_url = body.get("url")

    try:
        link, created = create_link(request.dbsession, raw_url, request.app_settings)
    except InvalidURL as invalid:
        return _error(
            request, 400, invalid.msgid, "The submitted URL was refused.",
            detail=invalid.detail or None,
        )
    except CodeExhausted:
        log.error("code space exhausted at length %d", request.app_settings.code_length)
        return _error(
            request, 503, "error_code_exhausted", "No short code is available."
        )

    request.response.status_int = 201 if created else 200
    return _link_json(request, link, created=created)


@view_config(route_name="api_link", request_method="GET", renderer="json")
def api_link(request):
    """Public facts about one code. Does NOT count as a visit."""
    if not request.read_throttle.allow(request.client_addr or "unknown"):
        return _error(request, 429, "error_rate_limited", "Too many requests.")
    link = find_by_code(request.dbsession, request.matchdict["code"])
    if link is None:
        return _error(request, 404, "error_unknown_code", "No such short code.")
    return _link_json(request, link)


#: Routes a browser may preflight. `redirect` is absent on purpose: a
#: short link is followed by navigation, never by a scripted fetch that
#: would preflight it.
PREFLIGHTABLE_ROUTES = ("api_shorten", "api_link", "home")


@view_config(route_name="api_shorten", request_method="OPTIONS")
@view_config(route_name="api_link", request_method="OPTIONS")
@view_config(route_name="home", request_method="OPTIONS")
def preflight(request):
    """Answer the browser's CORS preflight.

    EXTERNAL AUDIT 2026-08-22, finding C-15. `Access-Control-Allow-
    Methods: GET, POST, OPTIONS` was advertised on every allowed
    response, and no view answered OPTIONS -- so a browser sending
    `POST` with `Content-Type: application/json`, which always
    preflights, got a **404 on the preflight** and never sent the POST
    at all. Cross-origin access was announced and did not work.

    The answer is 204 whatever the origin: the CORS headers are added
    by the subscriber only for an allowed one, and a browser reading a
    204 without them refuses the call itself. Refusing the preflight
    with a 403 would say the same thing less clearly and give a caching
    layer one more case to get wrong.
    """
    response = HTTPNoContent()
    response.headers["Allow"] = "GET, POST, OPTIONS"
    return response
