# -*- coding: utf-8 -*-
"""CORS preflight (train 0009).

External audit 2026-08-22, finding C-15: the service advertised
`Access-Control-Allow-Methods: GET, POST, OPTIONS` and no view answered
OPTIONS, so a browser POSTing JSON — which always preflights — got a
404 on the preflight and never sent the request. Cross-origin access
was announced and did not work.
"""
import pytest
import webtest
from pyramid.paster import get_appsettings

from urlshortener import CORS_MAX_AGE, main
from urlshortener.models import Base
from tests.conftest import TESTING_INI

FRIEND = "https://friend.test"
STRANGER = "https://stranger.test"


@pytest.fixture
def cors_app():
    settings = get_appsettings(TESTING_INI, name="main")
    settings["urlshortener.cors_origins"] = FRIEND
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    yield webtest.TestApp(app)
    Base.metadata.drop_all(app.registry["dbengine"])
    app.registry["dbengine"].dispose()


PREFLIGHTED = ["/api/v1/shorten", "/api/v1/links/abc", "/"]


@pytest.mark.parametrize("path", PREFLIGHTED)
def test_c15_a_preflight_is_answered_at_all(cors_app, path):
    """This is the whole finding: it used to be a 404."""
    response = cors_app.options(path, headers={
        "Origin": FRIEND,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_int == 204


def test_c15_the_preflight_carries_what_the_browser_needs(cors_app):
    response = cors_app.options("/api/v1/shorten", headers={
        "Origin": FRIEND,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.headers["Access-Control-Allow-Origin"] == FRIEND
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert "Content-Type" in response.headers["Access-Control-Allow-Headers"]
    assert response.headers["Access-Control-Max-Age"] == str(CORS_MAX_AGE)
    assert "OPTIONS" in response.headers["Allow"]


def test_c15_the_actual_call_works_after_the_preflight(cors_app):
    """The pair, in the order a browser performs it."""
    cors_app.options("/api/v1/shorten", headers={
        "Origin": FRIEND, "Access-Control-Request-Method": "POST",
    })
    response = cors_app.post_json(
        "/api/v1/shorten", {"url": "https://example.org/x"},
        headers={"Origin": FRIEND}, status=201,
    )
    assert response.headers["Access-Control-Allow-Origin"] == FRIEND


def test_c15_a_stranger_gets_a_204_without_the_permission(cors_app):
    """204 rather than 403: the browser refuses the call itself when
    the headers are absent, and a refusal status gives caches one more
    case to get wrong."""
    response = cors_app.options("/api/v1/shorten", headers={
        "Origin": STRANGER, "Access-Control-Request-Method": "POST",
    })
    assert response.status_int == 204
    assert "Access-Control-Allow-Origin" not in response.headers


def test_c15_a_refusal_also_says_it_depends_on_the_origin(cors_app):
    """The Vary bug: it was set only on the allowing branch, so a shared
    cache could hand a refusal to an allowed origin, or the reverse."""
    refused = cors_app.options("/api/v1/shorten", headers={"Origin": STRANGER})
    assert refused.headers["Vary"] == "Origin"
    allowed = cors_app.options("/api/v1/shorten", headers={"Origin": FRIEND})
    assert allowed.headers["Vary"] == "Origin"


def test_c15_a_wildcard_origin_needs_no_vary():
    settings = get_appsettings(TESTING_INI, name="main")
    settings["urlshortener.cors_origins"] = "*"
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    client = webtest.TestApp(app)
    try:
        response = client.options("/api/v1/shorten", headers={"Origin": STRANGER})
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert "Vary" not in response.headers
    finally:
        Base.metadata.drop_all(app.registry["dbengine"])
        app.registry["dbengine"].dispose()


def test_c15_nothing_cross_origin_happens_when_cors_is_off(testapp):
    """Default configuration: the preflight is answered, and grants
    nothing."""
    response = testapp.options("/api/v1/shorten", headers={"Origin": FRIEND})
    assert response.status_int == 204
    assert "Access-Control-Allow-Origin" not in response.headers


def test_c15_the_redirect_is_not_preflightable(cors_app):
    """A short link is followed by navigation, never by a scripted
    fetch, so `/{code}` has no business answering OPTIONS."""
    cors_app.options("/abc", headers={"Origin": FRIEND}, status=404)


def test_c15_the_advertised_methods_are_the_ones_that_work(cors_app):
    """An advertised method nobody implements is what caused this
    finding in the first place."""
    advertised = cors_app.options(
        "/api/v1/shorten", headers={"Origin": FRIEND}
    ).headers["Access-Control-Allow-Methods"]
    for method in [m.strip() for m in advertised.split(",")]:
        if method == "OPTIONS":
            continue
        response = cors_app.request(
            "/api/v1/shorten", method=method,
            headers={"Origin": FRIEND}, expect_errors=True,
        )
        assert response.status_int != 405, "%s is advertised but refused" % method
