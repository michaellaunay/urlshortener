# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Which language a given request is answered in.

Order of precedence, most explicit first:

1. `?_LOCALE_=fr` in the query string -- a link can carry its language;
2. the `_LOCALE_` cookie, set by the language switcher;
3. `Accept-Language`, intersected with the languages actually offered;
4. `DEFAULT_LOCALE`.

Only codes marked `selectable` in the registry are ever returned, so a
request for a declared-but-unwritten language falls back instead of
rendering a half-empty page.
"""
from __future__ import annotations

from .constants_and_globals import (
    AVAILABLE_LANGUAGES,
    DEFAULT_LOCALE,
    LOCALE_COOKIE,
)


def parse_accept_language(header: str):
    """Yield language tags from an `Accept-Language` header, best first.

    Malformed q-values are treated as q=1 rather than rejecting the
    whole header: a broken client should still get its best guess.
    """
    if not header:
        return []
    entries = []
    for index, chunk in enumerate(header.split(",")):
        parts = chunk.strip().split(";")
        tag = parts[0].strip().lower()
        if not tag:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            parameter = parameter.strip()
            if parameter.startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 1.0
        # index keeps the header's own order stable among equal q values
        entries.append((-quality, index, tag))
    return [tag for _q, _i, tag in sorted(entries)]


def negotiate(request) -> str:
    requested = request.params.get(LOCALE_COOKIE)
    if requested in AVAILABLE_LANGUAGES:
        return requested

    cookie = request.cookies.get(LOCALE_COOKIE)
    if cookie in AVAILABLE_LANGUAGES:
        return cookie

    for tag in parse_accept_language(request.headers.get("Accept-Language", "")):
        if tag in AVAILABLE_LANGUAGES:
            return tag
        # 'fr-BE' should reach the 'fr' catalogue.
        primary = tag.split("-", 1)[0]
        if primary in AVAILABLE_LANGUAGES:
            return primary

    return DEFAULT_LOCALE


def locale_negotiator(request):
    return negotiate(request)
