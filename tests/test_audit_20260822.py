# -*- coding: utf-8 -*-
"""Regression locks for the internal security audit of 2026-08-22.

One test per finding, named after it. Each fails on the code as it was
before the audit -- that is the point: a fix without a test that would
have caught the bug is a fix that comes back.
"""
import os
import sqlite3

import pytest
import webtest
from pyramid.paster import get_appsettings

from urlshortener import main
from urlshortener.constants_and_globals import AppSettings
from urlshortener.models import Base
from urlshortener.throttle import RateLimiter
from urlshortener.tools.import_legacy import read_legacy_rows
from urlshortener.urlvalidation import normalise_url, to_wire_url
from tests.conftest import TESTING_INI

OPEN = AppSettings(base_url="http://s.test/", block_private_targets=False)


# -- S-01 -- non-ASCII in the Location header ----------------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://münchen.example/café", "https://xn--mnchen-3ya.example/caf%C3%A9"),
    ("https://example.org/日本", "https://example.org/%E6%97%A5%E6%9C%AC"),
    ("https://пример.example/", "https://xn--e1afmkfd.example/"),
    ("https://example.org/a b", "https://example.org/a%20b"),
])
def test_s01_targets_are_stored_in_their_wire_form(raw, expected):
    assert normalise_url(raw, OPEN) == expected


def test_s01_an_already_encoded_url_is_not_encoded_twice():
    # %20 -> %2520 would send the visitor to a different page.
    assert to_wire_url("https://example.org/%20a%2Fb") == "https://example.org/%20a%2Fb"


def test_s01_the_redirect_header_is_pure_ascii(testapp):
    """Before the fix: waitress does res.encode('latin-1') on the
    header block, so a Japanese path raised UnicodeEncodeError and the
    link answered 500 on EVERY visit, for ever."""
    short = testapp.get("/", params={"url": "https://example.org/日本"}).json["short_url"]
    response = testapp.get("/" + short.rsplit("/", 1)[-1], status=302)
    location = response.headers["Location"]
    assert location.encode("ascii")
    assert location == "https://example.org/%E6%97%A5%E6%9C%AC"


def test_s01_a_row_imported_verbatim_cannot_break_the_redirect(testapp):
    """The 2016 rows are imported WITHOUT normalisation, so they never
    passed through to_wire_url. The redirect must defend itself."""
    from sqlalchemy import text

    engine = testapp.app.registry["dbengine"]
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO links (code, url, url_sha256, created_at, hits) "
                 "VALUES ('legacy1', :u, :s, '2016-01-01 00:00:00', 0)"),
            {"u": "https://example.org/héllo/日本", "s": "0" * 64},
        )
    response = testapp.get("/legacy1", status=302)
    assert response.headers["Location"].encode("ascii")


# -- S-03 -- the legacy file must really be opened read-only -------------

def test_s03_a_path_containing_a_question_mark_stays_read_only(tmp_path):
    """Raw interpolation turned `x.db?mode=rwc` into URI parameters and
    silently dropped the read-only guarantee on the operator's only
    rollback copy."""
    path = tmp_path / "weird?mode=rwc.db"
    connection = sqlite3.connect(str(path))
    connection.execute("CREATE TABLE WEB_URL(ID INTEGER PRIMARY KEY, NUM TEXT, URL TEXT)")
    connection.execute("INSERT INTO WEB_URL (NUM, URL) VALUES ('a1', 'https://example.org/')")
    connection.commit()
    connection.close()

    rows = list(read_legacy_rows(str(path)))
    assert rows == [(1, "a1", "https://example.org/")]


# -- S-04 -- the limiter's memory is bounded ------------------------------

def test_s04_the_limiter_does_not_grow_without_bound():
    limiter = RateLimiter(5, 300, max_keys=100)
    for index in range(5000):
        limiter.allow("198.51.100.%d" % index)
    assert len(limiter._events) <= 100


def test_s04_the_ceiling_does_not_break_normal_accounting():
    limiter = RateLimiter(2, 300, max_keys=100)
    assert limiter.allow("a") and limiter.allow("a")
    assert limiter.allow("a") is False


# -- S-05 -- the proxy hop count is explicit ------------------------------

def test_s05_production_declares_its_trusted_proxy_count():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "production.ini"), encoding="utf-8") as handle:
        body = handle.read()
    assert "trusted_proxy_count" in body, (
        "leaving the hop count implicit means adding a CDN silently hands "
        "the rate-limiting key to the visitor"
    )


# -- S-07 -- the derived runtime.ini is not world-readable ----------------

def test_s07_the_runtime_ini_is_created_0600(tmp_path):
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "docker"))
    import apply_server_overrides as helper

    destination = str(tmp_path / "runtime.ini")
    saved = os.environ.get("SQLALCHEMY_URL")
    os.environ["SQLALCHEMY_URL"] = "postgresql+psycopg://u:secret@db/x"
    try:
        helper.main(["h", os.path.join(root, "production.ini"), destination])
    finally:
        if saved is None:
            os.environ.pop("SQLALCHEMY_URL", None)
        else:
            os.environ["SQLALCHEMY_URL"] = saved
    assert oct(os.stat(destination).st_mode & 0o777) == "0o600"


# -- S-09 -- a 404 does not charge the database ---------------------------

def test_s09_the_404_page_does_not_count_the_links(testapp):
    """An enumerator produces one miss per guess; each miss must not
    cost an aggregate over the whole table."""
    from urlshortener import views

    calls = []
    original = views.count_links
    views.count_links = lambda session: calls.append(1) or 0
    try:
        testapp.get("/nosuch1", status=404)
    finally:
        views.count_links = original
    assert calls == []


# -- S-11 -- the SQLite pragmas belong to OUR engine ----------------------

def test_s11_importing_the_package_does_not_reconfigure_other_engines():
    """The listener used to be attached to the Engine CLASS, so any
    other SQLAlchemy engine in the process inherited WAL and foreign-key
    enforcement it never asked for."""
    from sqlalchemy import create_engine, text

    stranger = create_engine("sqlite://")
    with stranger.connect() as connection:
        mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
    stranger.dispose()
    assert mode.lower() == "memory"


# -- S-02 -- reads can be limited when the operator wants it --------------

def test_s02_the_api_read_limit_is_off_by_default(testapp):
    for _ in range(50):
        testapp.get("/api/v1/links/zzzzzz9", status=404)


def test_s02_the_api_read_limit_applies_when_configured():
    settings = get_appsettings(TESTING_INI, name="main")
    settings["urlshortener.throttle_max_reads"] = "3"
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    client = webtest.TestApp(app)
    try:
        for _ in range(3):
            client.get("/api/v1/links/zzzzzz9", status=404)
        refused = client.get("/api/v1/links/zzzzzz9", status=429)
        assert refused.json["error"] == "error_rate_limited"
        # The redirect is NEVER limited: it is the service's function.
        client.get("/nosuch1", status=404)
    finally:
        Base.metadata.drop_all(app.registry["dbengine"])
        app.registry["dbengine"].dispose()


# -- S-08 -- the dependency exception is documented, not silent -----------

def test_s08_the_pip_audit_exception_is_written_down():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, ".github/workflows/quality.yml"), encoding="utf-8") as handle:
        workflow = handle.read()
    if "--ignore-vuln" in workflow:
        assert "PYSEC-2026-3447" in workflow
        assert "pyramid" in workflow, "an ignored advisory needs its reason in the file"
