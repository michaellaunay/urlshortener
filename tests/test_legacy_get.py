# -*- coding: utf-8 -*-
"""The 2016 `GET /?url=` entry point, and its way out (train 0010).

External audit 2026-08-22, finding C-09. Three defects, none fixable
while keeping the endpoint: a GET that writes, the target in a query
string and therefore in every access log, and no preflight between a
third-party page and it.

It stays ON by default, because KuneAgi calls it and the first promise
of this project is that nothing written against the 2016 service
breaks. What this train adds is the ability to switch it off, and the
means to know when that is safe.
"""
import logging

import pytest
import webtest
from pyramid.paster import get_appsettings

from urlshortener import main
from urlshortener.constants_and_globals import AppSettings
from urlshortener.models import Base
from tests.conftest import TESTING_INI


def _app_with(**overrides):
    settings = get_appsettings(TESTING_INI, name="main")
    settings.update(overrides)
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    return app


@pytest.fixture
def disabled_app():
    app = _app_with(**{"urlshortener.enable_legacy_get": "false"})
    yield webtest.TestApp(app)
    Base.metadata.drop_all(app.registry["dbengine"])
    app.registry["dbengine"].dispose()


# -- the default does not move --------------------------------------------

def test_it_is_on_by_default():
    """KuneAgi calls it. Turning it off by default would be this
    project breaking its own first promise."""
    assert AppSettings.enable_legacy_get is True


def test_the_shipped_configuration_leaves_it_on():
    import os
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in ("production.ini", "development.ini"):
        with open(os.path.join(root, path), encoding="utf-8") as handle:
            body = handle.read()
        assert re.search(r"^urlshortener\.enable_legacy_get = true", body, re.MULTILINE)


def test_it_still_answers_the_2016_shape(testapp):
    payload = testapp.get("/", params={"url": "https://example.org/page"}).json
    assert set(payload) == {"short_url", "code", "original_url"}
    assert payload["code"] == "SUCCESS"


# -- the deprecation signal ------------------------------------------------

def test_every_answer_says_it_is_deprecated(testapp):
    response = testapp.get("/", params={"url": "https://example.org/a"})
    assert response.headers["Deprecation"] == "true"
    assert 'rel="successor-version"' in response.headers["Link"]
    assert "/api/v1/shorten" in response.headers["Link"]


def test_a_refusal_says_it_too(testapp):
    """A client that only ever sends bad input must still learn that
    the endpoint is going away."""
    response = testapp.get("/", params={"url": "javascript:alert(1)"}, status=400)
    assert response.headers["Deprecation"] == "true"


def test_the_successor_link_follows_the_public_base_url(testapp):
    """Behind a prefix mount the successor is under that prefix too."""
    response = testapp.get("/", params={"url": "https://example.org/b"})
    assert response.headers["Link"].startswith("<http://short.test/api/v1/shorten>")


def test_the_modern_endpoint_is_not_marked_deprecated(testapp):
    response = testapp.post_json("/api/v1/shorten", {"url": "https://example.org/c"})
    assert "Deprecation" not in response.headers


# -- knowing when it is safe to switch off --------------------------------

def test_each_use_is_logged(testapp, caplog):
    """The only way to find out whether the callers have moved."""
    with caplog.at_level(logging.INFO, logger="urlshortener.views"):
        testapp.get("/", params={"url": "https://example.org/d"})
    assert any("legacy GET /?url= used" in record.getMessage()
               for record in caplog.records)


def test_the_log_line_does_not_repeat_the_target(testapp, caplog):
    """It is already in the query string of the access log; putting it
    in a second place buys nothing and costs a second place."""
    secret = "https://example.org/reset?token=SHOULD-NOT-BE-LOGGED"
    with caplog.at_level(logging.INFO, logger="urlshortener.views"):
        testapp.get("/", params={"url": secret})
    for record in caplog.records:
        assert "SHOULD-NOT-BE-LOGGED" not in record.getMessage()


# -- switched off ----------------------------------------------------------

def test_it_answers_410_when_disabled(disabled_app):
    """410 rather than 404: the endpoint existed, and the answer is
    that it is over."""
    response = disabled_app.get(
        "/", params={"url": "https://example.org/e"}, status=410
    )
    assert response.json["code"] == "ERROR"
    assert response.json["error"] == "error_legacy_get_disabled"
    assert response.json["original_url"] == "https://example.org/e"


def test_the_refusal_keeps_the_2016_body_shape(disabled_app):
    """An old client's parser must read the refusal, not choke on it."""
    payload = disabled_app.get(
        "/", params={"url": "https://example.org/f"}, status=410
    ).json
    assert set(payload) == {"code", "error", "original_url"}


def test_nothing_is_created_when_disabled(disabled_app):
    disabled_app.get("/", params={"url": "https://example.org/g"}, status=410)
    assert disabled_app.get("/healthz").json["links"] == 0


def test_the_rest_of_the_service_is_untouched(disabled_app):
    """Switching off the legacy GET must not touch the home page, the
    form, the API or the redirect."""
    disabled_app.get("/", status=200)
    disabled_app.post("/", {"url": "https://example.org/h"}, status=200)
    code = disabled_app.post_json(
        "/api/v1/shorten", {"url": "https://example.org/i"}, status=201
    ).json["code"]
    assert disabled_app.get("/" + code, status=302)


def test_the_switch_is_reachable_from_the_environment(monkeypatch):
    monkeypatch.setenv("URLSHORTENER_ENABLE_LEGACY_GET", "false")
    assert AppSettings.from_settings({}).enable_legacy_get is False


def test_the_container_forwards_the_switch():
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docker/docker-compose.yaml"), encoding="utf-8") as handle:
        assert "URLSHORTENER_ENABLE_LEGACY_GET" in handle.read()


# -- N-05 -- the browser's door closes, the caller's stays open (0024) ----
#
# External audit (Claude, 2026-08-23), finding N-05. Of the C-09
# triptych, this closes the one branch that can close while the
# endpoint lives: the drive-by. The D-02 guard was built precisely for
# sessionless creations — and it stood in front of every entry point
# except the one a third-party page can drive with a bare <img>.

def test_n05_a_cross_site_get_creates_nothing(testapp):
    before = testapp.get("/healthz").json["links"]
    response = testapp.get(
        "/", params={"url": "https://example.org/driveby"},
        headers={"Sec-Fetch-Site": "cross-site"}, status=403,
    )
    assert response.json == {
        "code": "ERROR",
        "error": "error_cross_site",
        "original_url": "https://example.org/driveby",
    }
    assert response.headers["Deprecation"] == "true"
    assert testapp.get("/healthz").json["links"] == before


@pytest.mark.parametrize("site", ["none", "same-origin", "same-site"])
def test_n05_a_legitimate_fetch_site_still_creates(testapp, site):
    payload = testapp.get(
        "/", params={"url": "https://example.org/ok-%s" % site},
        headers={"Sec-Fetch-Site": site},
    ).json
    assert payload["code"] == "SUCCESS"


def test_n05_the_server_side_caller_is_untouched(testapp):
    """KuneAgi calls server-to-server and sends no Sec-Fetch-Site; so
    does curl. The guard fails open for them by construction — the
    attack lives in current browsers, which always send the header and
    let a page neither remove nor choose it."""
    payload = testapp.get("/", params={"url": "https://example.org/kuneagi"}).json
    assert payload["code"] == "SUCCESS"


def test_n05_a_refused_drive_by_does_not_pollute_the_migration_signal(testapp, caplog):
    """`grep -c 'legacy GET /?url= used'` is the switch-off criterion.
    If a drive-by counted as a use, every scanner and every hostile
    page would keep the endpoint alive for ever. The refusal gets a
    line of its own instead."""
    with caplog.at_level(logging.INFO, logger="urlshortener.views"):
        testapp.get(
            "/", params={"url": "https://example.org/x"},
            headers={"Sec-Fetch-Site": "cross-site"}, status=403,
        )
    messages = [record.getMessage() for record in caplog.records]
    assert not any("legacy GET /?url= used" in message for message in messages)
    assert any("legacy GET /?url= refused: cross-site" in message
               for message in messages)


def test_n05_a_drive_by_does_not_spend_the_visitor_s_budget():
    """Part of C-09's harm was the rate limit spread across strangers:
    pages the visitor merely viewed spent the visitor's budget. The
    guard sits BEFORE the throttle, so a refused drive-by costs the
    visitor nothing."""
    app = _app_with(**{"urlshortener.throttle_max_creations": "1"})
    client = webtest.TestApp(app)
    try:
        client.get(
            "/", params={"url": "https://example.org/a"},
            headers={"Sec-Fetch-Site": "cross-site"}, status=403,
        )
        payload = client.get("/", params={"url": "https://example.org/b"}).json
        assert payload["code"] == "SUCCESS"
    finally:
        Base.metadata.drop_all(app.registry["dbengine"])
        app.registry["dbengine"].dispose()
