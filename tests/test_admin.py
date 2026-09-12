# -*- coding: utf-8 -*-
"""The administrator's page (train 0026).

One operator, one credential, and two deliberate asymmetries with the
public side, both pinned here: /admin answers 404 when the feature is
off, and the Sec-Fetch-Site guard on actions fails CLOSED.
"""
import base64

import pytest
import webtest
from pyramid.paster import get_appsettings

from urlshortener import main
from urlshortener.admin import verify_password
from urlshortener.models import Base
from urlshortener.tools.hash_password import hash_password
from tests.conftest import TESTING_INI

PASSWORD = "correct horse"
SAME = {"Sec-Fetch-Site": "same-origin"}


def _basic(password):
    token = base64.b64encode(("admin:%s" % password).encode()).decode()
    return {"Authorization": "Basic %s" % token}


def _app(**overrides):
    settings = get_appsettings(TESTING_INI, name="main")
    settings.update(overrides)
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    return webtest.TestApp(app)


@pytest.fixture
def admin_app():
    client = _app(**{"urlshortener.admin_password_hash": hash_password(PASSWORD)})
    yield client
    client.app.registry["dbengine"].dispose()


def _shorten(client, url):
    return client.post_json("/api/v1/shorten", {"url": url}).json["code"]


# -- the door --------------------------------------------------------------

def test_the_area_is_404_when_no_hash_is_configured(testapp):
    """A login door that exists is a door to knock on."""
    testapp.get("/admin", status=404)
    testapp.get("/admin", headers=_basic("anything"), status=404)


def test_no_credential_gets_a_challenge(admin_app):
    response = admin_app.get("/admin", status=401)
    assert response.headers["WWW-Authenticate"].startswith("Basic")


def test_a_wrong_password_is_refused(admin_app):
    admin_app.get("/admin", headers=_basic("wrong"), status=401)


def test_the_right_password_opens_the_page(admin_app):
    response = admin_app.get("/admin", headers=_basic(PASSWORD), status=200)
    assert "Administration" in response.text


def test_garbage_authorization_is_a_clean_401(admin_app):
    admin_app.get("/admin", headers={"Authorization": "Basic %%%"}, status=401)


def test_the_hash_roundtrip_is_constant_time_material():
    stored = hash_password("s3cret")
    assert verify_password("s3cret", stored)
    assert not verify_password("s3cret ", stored)
    assert not verify_password("", stored)
    assert not verify_password("s3cret", "not-a-hash")


# -- seeing ---------------------------------------------------------------

def test_the_admin_sees_the_links_and_who_asked(admin_app):
    code = _shorten(admin_app, "https://example.org/visible")
    engine = admin_app.app.registry["dbengine"]
    from sqlalchemy import text

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE links SET requested_by_email = 'who@example.net'")
        )
    page = admin_app.get("/admin", headers=_basic(PASSWORD))
    assert code in page.text
    assert "https://example.org/visible" in page.text
    assert "who@example.net" in page.text


def test_the_search_filters_on_code_or_target(admin_app):
    kept = _shorten(admin_app, "https://example.org/keep-me")
    _shorten(admin_app, "https://example.org/other")
    page = admin_app.get("/admin?q=keep-me", headers=_basic(PASSWORD))
    assert kept in page.text
    assert "/other" not in page.text


# -- blocking: the point of the page --------------------------------------

def _act(client, code, action, status="*"):
    return client.post(
        "/admin/action", {"code": code, "action": action},
        headers={**_basic(PASSWORD), **SAME}, status=status,
    )


def test_a_blocked_link_answers_410_and_stops_counting(admin_app):
    code = _shorten(admin_app, "https://example.org/litigious")
    admin_app.get("/" + code, status=302)
    _act(admin_app, code, "block", status=303)
    admin_app.get("/" + code, status=410)
    page = admin_app.get("/api/v1/links/" + code, status=410)
    assert page.json["error"] == "error_link_blocked"


def test_blocking_beats_deleting_against_recreation(admin_app):
    """The reason block exists: after a DELETE the same litigious URL
    is one POST away from a fresh code. After a BLOCK, de-duplication
    hands back the blocked link, and the 410 answers the new attempt
    exactly as it answers the old code."""
    code = _shorten(admin_app, "https://example.org/litigious")
    _act(admin_app, code, "block", status=303)
    again = admin_app.post_json(
        "/api/v1/shorten", {"url": "https://example.org/litigious"}
    ).json["code"]
    assert again == code
    admin_app.get("/" + again, status=410)


def test_unblock_restores_the_redirect(admin_app):
    code = _shorten(admin_app, "https://example.org/appealed")
    _act(admin_app, code, "block", status=303)
    _act(admin_app, code, "unblock", status=303)
    admin_app.get("/" + code, status=302)


def test_delete_removes_the_row(admin_app):
    code = _shorten(admin_app, "https://example.org/purge")
    _act(admin_app, code, "delete", status=303)
    admin_app.get("/" + code, status=404)
    assert admin_app.get("/healthz").json["links"] == 0


def test_an_unknown_code_is_a_404_with_the_page(admin_app):
    response = _act(admin_app, "nope", "block", status=404)
    assert "unknown code" in response.text


# -- the closed guard ------------------------------------------------------

def test_an_action_without_sec_fetch_site_is_refused(admin_app):
    """FAILS CLOSED, unlike public creation: Basic credentials ride on
    any request a hostile page makes the browser send. A script must
    say -H 'Sec-Fetch-Site: none' on purpose."""
    code = _shorten(admin_app, "https://example.org/x")
    admin_app.post(
        "/admin/action", {"code": code, "action": "block"},
        headers=_basic(PASSWORD), status=403,
    )
    admin_app.get("/" + code, status=302)      # still alive


def test_a_cross_site_action_is_refused_even_authenticated(admin_app):
    code = _shorten(admin_app, "https://example.org/x")
    admin_app.post(
        "/admin/action", {"code": code, "action": "block"},
        headers={**_basic(PASSWORD), "Sec-Fetch-Site": "cross-site"}, status=403,
    )


def test_actions_require_the_credential_too(admin_app):
    code = _shorten(admin_app, "https://example.org/x")
    admin_app.post(
        "/admin/action", {"code": code, "action": "block"},
        headers=SAME, status=401,
    )


def test_admin_is_a_reserved_code():
    from urlshortener.codec import RESERVED_CODES

    assert "admin" in RESERVED_CODES
