# -*- coding: utf-8 -*-
# Copyright (c) 2016 Ecreall — Copyright (c) 2026 Logikascium
# Licensed under the GNU Affero General Public License v3 or later.
"""WSGI application factory."""
from __future__ import annotations

import logging
import os

from dotenv import find_dotenv, load_dotenv
from pyramid.config import Configurator
from pyramid.events import NewResponse

from .constants_and_globals import AVAILABLE_LANGUAGES, AppSettings, DOMAIN
from .locale_negotiation import locale_negotiator
from .throttle import RateLimiter

__version__ = "2.0.10"

log = logging.getLogger(__name__)

#: Sent on every HTML response. `frame-ancestors 'none'` matters here:
#: a shortener page framed inside another site is a phishing aid.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    ),
}


def _load_env() -> None:
    """Read `.env` if there is one.

    `find_dotenv()` with no argument walks up from the CALLING FILE.
    Once this package is installed as a wheel that walk starts inside
    site-packages and never crosses the deployment directory -- the
    exact failure that kept AlirPunkto's container from booting after
    its image was switched to a non-editable install. `usecwd=True`
    walks up from the working directory instead, which is where the
    operator actually put the file; the bare call stays as a fallback
    for a source checkout.
    """
    path = find_dotenv(usecwd=True) or find_dotenv()
    if path:
        load_dotenv(path)


def _add_security_headers(event):
    response = event.response
    content_type = (response.content_type or "").lower()
    for header, value in SECURITY_HEADERS.items():
        if header == "Content-Security-Policy" and not content_type.startswith("text/html"):
            continue
        response.headers.setdefault(header, value)


#: How long a browser may cache a preflight answer, in seconds.
#: Ten minutes: long enough that a page making repeated API calls does
#: not pay for a round trip each time, short enough that changing
#: `cors_origins` takes effect the same morning.
CORS_MAX_AGE = 600


def _add_cors_headers(event):
    """Answer cross-origin JSON calls, for the origins configured.

    The 2016 service sent `Access-Control-Allow-Origin: *` to everyone,
    always. Here the list is explicit and empty by default; '*' remains
    expressible for a service that really is public.

    EXTERNAL AUDIT 2026-08-22, finding C-15: `Vary: Origin` was set only
    on the branch that allowed a named origin. A shared cache could
    therefore store the header-less answer given to a refused origin and
    hand it back to an allowed one, or the reverse. As soon as the
    answer DEPENDS on `Origin`, every answer must say so -- including
    the refusals.
    """
    request = event.request
    settings = getattr(request, "app_settings", None)
    if settings is None or not settings.cors_origins:
        return
    origin = request.headers.get("Origin")
    if not origin:
        return

    allowed = settings.cors_origins
    if "*" not in allowed:
        # The answer now varies with the request's Origin, whatever we
        # decide next -- refusal included.
        event.response.headers["Vary"] = "Origin"

    if "*" in allowed:
        event.response.headers["Access-Control-Allow-Origin"] = "*"
    elif origin in allowed:
        event.response.headers["Access-Control-Allow-Origin"] = origin
    else:
        return

    event.response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    event.response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    event.response.headers["Access-Control-Max-Age"] = str(CORS_MAX_AGE)


def main(global_config, **settings):
    """Return the WSGI application -- the `paste.app_factory` entry point."""
    _load_env()

    # The database URL is deployment state, not application state: a
    # container must be able to point at a different file, or at
    # PostgreSQL, without a rebuilt image or an edited .ini.
    database_url = os.environ.get("SQLALCHEMY_URL")
    if database_url:
        settings["sqlalchemy.url"] = database_url

    # Refuse to start on a configuration that cannot work, rather than
    # accept it and fail on the first request that touches the mistake
    # (external audit C-17). The exception carries every problem at
    # once, so one restart is enough to see them all.
    app_settings = AppSettings.from_settings(settings).validate()
    limiter = RateLimiter(
        app_settings.throttle_max_creations, app_settings.throttle_window_seconds
    )
    read_limiter = RateLimiter(
        app_settings.throttle_max_reads, app_settings.throttle_window_seconds
    )

    with Configurator(settings=settings, locale_negotiator=locale_negotiator) as config:
        config.include("pyramid_chameleon")
        config.include(".models")
        config.include(".routes")

        config.add_translation_dirs("urlshortener:locale/")
        config.registry.settings.setdefault("pyramid.default_locale_name", "en")

        # Resolved configuration and the limiter are attached to the
        # request rather than imported from a module global, so a test
        # can build an application with different settings without
        # touching process state.
        config.add_request_method(lambda request: app_settings, "app_settings", reify=True)
        config.add_request_method(lambda request: limiter, "throttle", reify=True)
        config.add_request_method(lambda request: read_limiter, "read_throttle", reify=True)

        config.add_subscriber(_add_security_headers, NewResponse)
        config.add_subscriber(_add_cors_headers, NewResponse)

        config.scan(".views")
        config.scan(".api")

        log.info(
            "urlshortener %s ready — base_url=%s, languages=%s, domain=%s",
            __version__,
            app_settings.base_url,
            ",".join(AVAILABLE_LANGUAGES),
            DOMAIN,
        )
        return config.make_wsgi_app()
