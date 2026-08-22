# -*- coding: utf-8 -*-
"""Request-body limits (train 0005).

External audit 2026-08-22, finding C-04: the URL was capped at 2 KiB
and the envelope carrying it was not. Waitress defaults
`max_request_body_size` to 1 GiB, in a container declared
`mem_limit: 512m`.
"""
import os
import re

import pytest
import webtest
from pyramid.paster import get_appsettings

from urlshortener import main
from urlshortener.constants_and_globals import AppSettings
from urlshortener.models import Base
from tests.conftest import TESTING_INI

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

OVERSIZED = "https://example.org/?q=" + "a" * 40000


def _read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        return handle.read()


def _app_with(**settings_overrides):
    settings = get_appsettings(TESTING_INI, name="main")
    settings.update(settings_overrides)
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    return app


# -- one number, three places ---------------------------------------------

def test_c04_the_default_is_sane_for_a_two_kilobyte_url():
    assert AppSettings.max_body_bytes >= 4096
    assert AppSettings.max_body_bytes <= 65536


@pytest.mark.parametrize("path", ["production.ini", "development.ini"])
def test_c04_the_server_limit_is_declared(path):
    """Left unset, waitress accepts 1 GiB."""
    body = _read(path)
    match = re.search(r"^max_request_body_size\s*=\s*(\d+)", body, re.MULTILINE)
    assert match, "%s does not cap the request body" % path
    assert int(match.group(1)) <= 65536


@pytest.mark.parametrize("path", ["production.ini", "development.ini"])
def test_c04_the_server_and_the_application_agree(path):
    """The anti-drift lock: two limits that can differ WILL differ, and
    the smaller one is then a surprise nobody documented."""
    body = _read(path)
    server = int(re.search(r"^max_request_body_size\s*=\s*(\d+)", body, re.MULTILINE).group(1))
    application = int(
        re.search(r"^urlshortener\.max_body_bytes\s*=\s*(\d+)", body, re.MULTILINE).group(1)
    )
    assert server == application == AppSettings.max_body_bytes


def test_c04_the_nginx_recipe_caps_the_body_too():
    for path in ("docs/fr/04_docker.md", "docs/en/04_docker.md"):
        assert "client_max_body_size" in _read(path)


def test_c04_one_variable_feeds_both_limits():
    """`URLSHORTENER_MAX_BODY_BYTES` must reach the server section as
    well, or a container raises one limit and not the other."""
    import sys

    sys.path.insert(0, os.path.join(ROOT, "docker"))
    import apply_server_overrides as helper

    assert helper.OVERRIDES["URLSHORTENER_MAX_BODY_BYTES"] == (
        "server:main", "max_request_body_size"
    )
    assert "URLSHORTENER_MAX_BODY_BYTES" in _read("docker/docker-compose.yaml")


def test_c04_the_environment_variable_drives_the_application(monkeypatch):
    monkeypatch.setenv("URLSHORTENER_MAX_BODY_BYTES", "999")
    assert AppSettings.from_settings({}).max_body_bytes == 999


# -- behaviour -------------------------------------------------------------

def test_c04_an_oversized_json_body_is_refused(testapp):
    response = testapp.post_json("/api/v1/shorten", {"url": OVERSIZED}, status=413)
    assert response.json["error"] == "error_body_too_large"


def test_c04_an_oversized_form_post_is_refused(testapp):
    response = testapp.post("/", {"url": OVERSIZED}, status=413)
    assert "too large" in response.text


def test_c04_the_refusal_is_translated(testapp):
    response = testapp.post(
        "/", {"url": OVERSIZED}, headers={"Accept-Language": "fr"}, status=413
    )
    assert "trop volumineuse" in response.text


def test_c04_the_body_is_refused_before_it_is_parsed(testapp):
    """Sent as broken JSON: a 400 would prove the parser ran, which is
    exactly the work the limit exists to avoid."""
    response = testapp.post(
        "/api/v1/shorten", "{" + "a" * 40000,
        content_type="application/json", status=413,
    )
    assert response.json["error"] == "error_body_too_large"


def test_c04_the_body_is_refused_before_the_throttle():
    """Refusing an oversized body must not cost a throttle slot, and
    must not depend on one being free."""
    app = _app_with(**{"urlshortener.throttle_max_creations": "1"})
    client = webtest.TestApp(app)
    try:
        client.post_json("/api/v1/shorten", {"url": "https://example.org/a"}, status=201)
        # Budget spent. An oversized body still answers 413, not 429.
        assert client.post_json(
            "/api/v1/shorten", {"url": OVERSIZED}, status=413
        ).json["error"] == "error_body_too_large"
    finally:
        Base.metadata.drop_all(app.registry["dbengine"])
        app.registry["dbengine"].dispose()


def test_c04_a_normal_request_is_untouched(testapp):
    assert testapp.post_json(
        "/api/v1/shorten", {"url": "https://example.org/normal"}, status=201
    ).json["created"] is True
    testapp.post("/", {"url": "https://example.org/normal-form"}, status=200)


def test_c04_a_url_over_max_url_length_is_still_a_400_not_a_413(testapp):
    """The two limits answer different questions: the envelope is too
    big (413), or the URL inside it is too long (400)."""
    long_url = "https://example.org/?q=" + "a" * 3000  # > 2048, < 16384
    response = testapp.post_json("/api/v1/shorten", {"url": long_url}, status=400)
    assert response.json["error"] == "error_url_too_long"


def test_c04_a_limit_of_zero_disables_the_application_check():
    app = _app_with(**{"urlshortener.max_body_bytes": "0"})
    client = webtest.TestApp(app)
    try:
        # Refused for being a long URL, not for being a big body.
        assert client.post_json(
            "/api/v1/shorten", {"url": OVERSIZED}, status=400
        ).json["error"] == "error_url_too_long"
    finally:
        Base.metadata.drop_all(app.registry["dbengine"])
        app.registry["dbengine"].dispose()


def test_c04_a_request_without_a_declared_length_falls_through():
    """Chunked transfer declares no length; the application cannot
    judge it and must not pretend to. The server's limit stops it."""
    from pyramid import testing

    from urlshortener.views import body_too_large

    request = testing.DummyRequest()
    request.app_settings = AppSettings(max_body_bytes=16384)
    request.content_length = None
    assert body_too_large(request) is False


def test_c04_reads_are_never_limited_by_this(testapp):
    testapp.get("/", status=200)
    testapp.get("/healthz", status=200)
    testapp.get("/api/v1/links/zzzzzz9", status=404)
