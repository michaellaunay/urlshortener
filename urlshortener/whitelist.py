# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Which targets may be shortened without the e-mail step.

Three entry forms, chosen by shape:

    example.coop  *.example.coop    fnmatch against the CANONICAL host
    https://example.org/docs/*      fnmatch against the canonical URL
    re:^https://ex\\.org/\\d+$        regular expression, fullmatch

Everything is matched against the CANONICAL form — the one
`normalise_url` stores — so `*.example.coop` and a visitor writing
`HTTP://WWW.EXAMPLE.COOP` meet on the same spelling, and the IDNA rules
of train 0012 apply to the list exactly as they apply to the target.

An EMPTY list allows everything. That is the compatibility stance: the
2016 contract and KuneAgi both expect a URL in and a short URL out, so
gating is opt-in. `AppSettings.validate()` refuses a non-empty list
without a mail relay, because a gate whose other door leads nowhere is
a wall.
"""
from __future__ import annotations

import re
from fnmatch import fnmatchcase
from urllib.parse import urlsplit


def is_whitelisted(canonical_url: str, settings) -> bool:
    """True when `canonical_url` may be shortened without an e-mail.

    `canonical_url` must be the output of `normalise_url`: this module
    deliberately performs no normalisation of its own, so there is
    exactly one place where a URL gets a canonical spelling.
    """
    entries = settings.whitelist
    if not entries:
        return True
    host = (urlsplit(canonical_url).hostname or "").lower()
    for entry in entries:
        if entry.startswith("re:"):
            if re.fullmatch(entry[3:], canonical_url):
                return True
        elif "://" in entry:
            if fnmatchcase(canonical_url, entry):
                return True
        else:
            if fnmatchcase(host, entry.lower()):
                return True
    return False
