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

from pyramid.view import view_config

from .services import CodeExhausted, create_link, find_by_code
from .views import body_too_large
from .urlvalidation import InvalidURL

log = logging.getLogger(__name__)


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

    if not request.throttle.allow(request.client_addr or "unknown"):
        return _error(request, 429, "error_rate_limited", "Too many requests.")

    try:
        body = request.json_body if request.body else {}
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_url = body.get("url")
    if raw_url is None:
        # Accept a plain form post too: curl -d url=... is the shape
        # every operator reaches for first.
        raw_url = request.POST.get("url") or request.params.get("url")

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
