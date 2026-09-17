# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Validate query encoding at the HTTP boundary, not while rendering errors."""
from __future__ import annotations

from pyramid.response import Response


def utf8_query_tween_factory(handler, registry):
    """Reject non-UTF-8 query names/values without inspecting the body.

    WebOb decodes the whole query lazily, including unrelated parameter
    names. A query such as ``%AD=x`` must not turn a 404 into a 500 via
    locale negotiation. Reuse WebOb's parser and its cached result rather
    than introducing a second parser or repairing invalid bytes.

    Only decoding the client input is guarded. UnicodeDecodeError raised
    inside application code must still surface as a server-side defect.
    """
    def utf8_query_tween(request):
        try:
            # GET means QUERY_STRING, even when the HTTP method is POST.
            # params would also read the body before its size/CSRF guards.
            _ = request.GET
        except UnicodeDecodeError:
            # A fixed response cannot recurse into locale negotiation,
            # render a template, or reflect attacker-controlled input.
            response = Response(
                status=400,
                content_type="text/plain",
                charset="UTF-8",
                text="Invalid UTF-8 in query string.\n",
            )
            # Response(headers=...) replaces the entire header list after
            # content_type/text have set Content-Type and Content-Length.
            # Add this header to the existing mapping instead.
            response.headers["Cache-Control"] = "no-store"
            return response
        return handler(request)

    return utf8_query_tween
