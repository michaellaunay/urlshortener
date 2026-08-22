# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""URL map.

Order matters: Pyramid tries routes in registration order and
`/{code}` matches almost anything, so it is registered last. Every
name it would otherwise swallow is also listed in
`codec.RESERVED_CODES`, and `tests/test_routes.py` checks the two lists
against each other -- adding a top-level route without reserving its
name fails the suite instead of silently shadowing links.
"""


def includeme(config):
    config.add_static_view("static", "static", cache_max_age=3600)

    # Specific paths first.
    config.add_route("healthz", "/healthz")
    config.add_route("set_locale", "/locale/{locale}")
    config.add_route("api_shorten", "/api/v1/shorten")
    config.add_route("api_link", "/api/v1/links/{code}")
    config.add_route("home", "/")

    # Catch-all LAST: this is the redirect.
    config.add_route("redirect", "/{code}")
