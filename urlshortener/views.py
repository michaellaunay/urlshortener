# -*- coding: utf-8 -*-
# Copyright (c) 2016 Ecreall — Copyright (c) 2026 Logikascium
# Licensed under the GNU Affero General Public License v3 or later.
"""HTML views and the two legacy-compatible entry points.

Compatibility contract with the 2016 service, kept deliberately:

* `GET /?url=<target>` answers JSON
  `{"short_url": ..., "code": "SUCCESS", "original_url": ...}`,
  and on refusal `{"code": "ERROR", "error": ..., "original_url": ...}`;
* `POST /` with a form field `url` answers the HTML page carrying the
  short link;
* `GET /<code>` answers 302 to the target.

One documented change: an unknown code answers **404** instead of the
old 200-with-an-error-page. A monitor could not previously tell a dead
link from a working one.
"""
from __future__ import annotations

import logging

from pyramid.httpexceptions import HTTPFound, HTTPNotFound, HTTPSeeOther
from pyramid.view import notfound_view_config, view_config

from .constants_and_globals import (
    AVAILABLE_LANGUAGES,
    LANGUAGE_NAMES,
    LOCALE_COOKIE,
    LOCALE_COOKIE_MAX_AGE,
    _,
)
from .services import CodeExhausted, count_links, create_link, find_by_code, record_hit
from .urlvalidation import InvalidURL

log = logging.getLogger(__name__)

#: Message shown for each refusal reason. The keys are the `msgid`
#: values raised by `urlvalidation`, so a new refusal reason without a
#: message here fails `tests/test_i18n.py`.
ERROR_MESSAGES = {
    "error_url_required": _("error_url_required", default="Enter a web address to shorten."),
    "error_url_too_long": _("error_url_too_long", default="That address is too long."),
    "error_url_scheme": _(
        "error_url_scheme", default="Only http:// and https:// addresses can be shortened."
    ),
    "error_url_host": _("error_url_host", default="That address has no host name."),
    "error_url_credentials": _(
        "error_url_credentials",
        default="Addresses carrying a user name and password are not accepted.",
    ),
    "error_url_private": _(
        "error_url_private", default="That address points to a private network."
    ),
    "error_url_blocked": _("error_url_blocked", default="That host is not accepted."),
    "error_url_control_characters": _(
        "error_url_control_characters", default="That address contains invalid characters."
    ),
    "error_code_exhausted": _(
        "error_code_exhausted", default="No short code is available. Contact the administrator."
    ),
    "error_rate_limited": _(
        "error_rate_limited", default="Too many links created from here. Try again shortly."
    ),
}


def _page_context(request, **extra):
    """Values every rendering of the page needs."""
    context = {
        "settings": request.app_settings,
        "languages": [(code, LANGUAGE_NAMES[code]) for code in AVAILABLE_LANGUAGES],
        "current_locale": request.locale_name,
        "link_count": count_links(request.dbsession),
        "submitted_url": "",
        "short_url": None,
        "short_base": request.app_settings.base_url,
        "short_code": None,
        "error": None,
        "already_existed": False,
    }
    context.update(extra)
    return context


def _client_key(request) -> str:
    """Throttling key. `client_addr` honours the trusted-proxy config."""
    return request.client_addr or "unknown"


@view_config(route_name="home", request_method="GET", renderer="templates/home.pt")
def home(request):
    """The form, or -- when `?url=` is present -- the legacy JSON reply."""
    raw_url = request.params.get("url")
    if raw_url is not None:
        return _legacy_get_json(request, raw_url)
    return _page_context(request)


def _legacy_get_json(request, raw_url):
    """`GET /?url=...` -- the 2016 JSON shape, character for character."""
    request.override_renderer = "json"
    if not request.throttle.allow(_client_key(request)):
        request.response.status_int = 429
        return {
            "code": "ERROR",
            "error": "rate limited",
            "original_url": raw_url,
        }
    try:
        link, _created = create_link(request.dbsession, raw_url, request.app_settings)
    except InvalidURL as invalid:
        request.response.status_int = 400
        return {
            "code": "ERROR",
            "error": invalid.msgid,
            "original_url": raw_url,
        }
    except CodeExhausted:
        log.error("code space exhausted at length %d", request.app_settings.code_length)
        request.response.status_int = 503
        return {
            "code": "ERROR",
            "error": "error_code_exhausted",
            "original_url": raw_url,
        }
    return {
        "short_url": request.app_settings.short_url(link.code),
        "code": "SUCCESS",
        "original_url": link.url,
    }


@view_config(route_name="home", request_method="POST", renderer="templates/home.pt")
def shorten_form(request):
    """`POST /` from the page's own form."""
    raw_url = request.POST.get("url", "")
    if not request.throttle.allow(_client_key(request)):
        request.response.status_int = 429
        return _page_context(
            request, submitted_url=raw_url, error=ERROR_MESSAGES["error_rate_limited"]
        )
    try:
        link, created = create_link(request.dbsession, raw_url, request.app_settings)
    except InvalidURL as invalid:
        request.response.status_int = 400
        return _page_context(
            request,
            submitted_url=raw_url,
            error=ERROR_MESSAGES.get(invalid.msgid, ERROR_MESSAGES["error_url_required"]),
        )
    except CodeExhausted:
        log.error("code space exhausted at length %d", request.app_settings.code_length)
        request.response.status_int = 503
        return _page_context(
            request, submitted_url=raw_url, error=ERROR_MESSAGES["error_code_exhausted"]
        )
    return _page_context(
        request,
        submitted_url=link.url,
        short_url=request.app_settings.short_url(link.code),
        short_code=link.code,
        already_existed=not created,
    )


@view_config(route_name="redirect", request_method=("GET", "HEAD"))
def redirect(request):
    """`GET /<code>` -- the whole point of the service."""
    code = request.matchdict["code"]
    link = find_by_code(request.dbsession, code)
    if link is None:
        raise HTTPNotFound()
    record_hit(request.dbsession, link, request.app_settings)
    response = HTTPFound(location=link.url)
    # Do not leak the short link (and therefore the visitor's path) to
    # the destination site.
    response.headers["Referrer-Policy"] = "no-referrer"
    # A short link is permanent in fact but not in law: keep it
    # revocable by telling caches not to keep the redirect.
    response.headers["Cache-Control"] = "no-store"
    return response


@view_config(route_name="set_locale")
def set_locale(request):
    """Remember an explicit language choice and return where we came from."""
    locale = request.matchdict.get("locale")
    came_from = request.params.get("came_from") or request.route_path("home")
    # Never bounce to an absolute URL taken from the query string: that
    # is how a language switcher becomes an open redirect.
    if not came_from.startswith("/") or came_from.startswith("//"):
        came_from = request.route_path("home")
    response = HTTPSeeOther(location=came_from)
    if locale in AVAILABLE_LANGUAGES:
        response.set_cookie(
            LOCALE_COOKIE,
            value=locale,
            max_age=LOCALE_COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=request.scheme == "https",
        )
    return response


@view_config(route_name="healthz", renderer="json")
def healthz(request):
    """Liveness plus a real database round-trip, for the container check."""
    from sqlalchemy import text

    request.dbsession.execute(text("SELECT 1"))
    return {"status": "ok", "links": count_links(request.dbsession)}


@notfound_view_config(renderer="templates/notfound.pt")
def notfound(request):
    """Unknown code, or unknown path. 404 either way."""
    request.response.status_int = 404
    return _page_context(request)
