# -*- coding: utf-8 -*-
"""Regression locks for the EXTERNAL audit of 2026-08-22 (train 0002).

Host canonicalisation. Every test here fails on the code as it stood
before the train: the bypasses were real, reproduced against the
running validator, not deduced from reading.
"""
import ipaddress

import pytest

from urlshortener.constants_and_globals import AppSettings
from urlshortener.urlvalidation import (
    InvalidURL,
    canonical_host,
    normalise_url,
    parse_browser_ipv4,
    to_wire_url,
)

GUARDED = AppSettings(base_url="http://s.test/", block_private_targets=True)
OPEN = AppSettings(base_url="http://s.test/", block_private_targets=False)


# -- C-02 -- the four browser spellings of one address --------------------

@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", "127.0.0.1"),
    ("2130706433", "127.0.0.1"),      # decimal
    ("0x7f000001", "127.0.0.1"),      # hexadecimal
    ("0177.0.0.1", "127.0.0.1"),      # octal
    ("127.1", "127.0.0.1"),           # two parts, the last one absorbing
    ("127.0.1", "127.0.0.1"),         # three parts
    ("0", "0.0.0.0"),
    ("192.168.1.1", "192.168.1.1"),
])
def test_c02_browser_ipv4_spellings_are_all_read(host, expected):
    assert parse_browser_ipv4(host) == ipaddress.IPv4Address(expected)


@pytest.mark.parametrize("host", [
    "example.org", "1.2.3.4.5", "256.0.0.1", "127.0.0.999",
    "0x1g", "1..2", "",
])
def test_c02_what_is_not_an_address_is_not_read_as_one(host):
    assert parse_browser_ipv4(host) is None


@pytest.mark.parametrize("raw", [
    "http://127.0.0.1/",
    "http://2130706433/",
    "http://0x7f000001/",
    "http://0177.0.0.1/",
    "http://127.1/",
    "http://017700000001/",
    "http://0x7f.1/",
])
def test_c02_every_spelling_of_the_loopback_is_refused(raw):
    """Before the train only the first one was refused; the other six
    were stored, and a browser sent the visitor to 127.0.0.1."""
    with pytest.raises(InvalidURL) as caught:
        normalise_url(raw, GUARDED)
    assert caught.value.msgid == "error_url_private"


def test_c02_the_guard_covers_the_cloud_metadata_address_in_decimal():
    # 169.254.169.254 written as one number.
    with pytest.raises(InvalidURL) as caught:
        normalise_url("http://2852039166/", GUARDED)
    assert caught.value.msgid == "error_url_private"


def test_c02_with_the_guard_off_the_address_is_still_canonicalised():
    """Whatever the spelling submitted, ONE spelling is stored -- so a
    later blocklist or audit sees the address, not a disguise."""
    assert normalise_url("http://2130706433:8080/x", OPEN) == "http://127.0.0.1:8080/x"
    assert normalise_url("http://0x7f000001/", OPEN) == "http://127.0.0.1/"


def test_c02_de_duplication_now_sees_through_the_spelling(dbsession):
    from urlshortener.services import count_links, create_link

    first, created_first = create_link(dbsession, "http://2130706433/x", OPEN)
    second, created_second = create_link(dbsession, "http://127.0.0.1/x", OPEN)
    assert created_first is True and created_second is False
    assert first.code == second.code
    assert count_links(dbsession) == 1


@pytest.mark.parametrize("raw", ["http://1.2.3.4.5/", "https://example.0x1/", "http://256.1.1.1/"])
def test_c02_a_numeric_host_that_is_not_an_address_is_refused(raw):
    """A browser rejects these outright, so storing one mints a link
    nobody can follow."""
    with pytest.raises(InvalidURL) as caught:
        normalise_url(raw, OPEN)
    assert caught.value.msgid == "error_url_host"


def test_c02_documentation_ranges_are_not_public_either():
    """`is_global` replaces the hand-kept property list, which was
    short by construction: TEST-NET and 2001:db8:: are not reachable."""
    for raw in ("http://198.51.100.7/", "http://[2001:db8::1]/", "http://192.0.2.1/"):
        with pytest.raises(InvalidURL) as caught:
            normalise_url(raw, GUARDED)
        assert caught.value.msgid == "error_url_private"


def test_c02_a_real_public_address_still_passes():
    assert normalise_url("http://93.184.216.34/x", GUARDED) == "http://93.184.216.34/x"
    assert normalise_url("http://[2606:2800:220:1:248:1893:25c8:1946]/", GUARDED)


# -- C-08 -- one name, one spelling ---------------------------------------

def test_c08_a_blocklist_in_punycode_catches_the_unicode_form():
    settings = AppSettings(blocked_hosts=("xn--bcher-kva.example",), block_private_targets=False)
    for raw in ("https://xn--bcher-kva.example/", "https://bücher.example/",
                "https://BÜCHER.example/", "https://bücher.example./"):
        with pytest.raises(InvalidURL) as caught:
            normalise_url(raw, settings)
        assert caught.value.msgid == "error_url_blocked"


def test_c08_a_blocklist_in_unicode_catches_the_punycode_form():
    """The operator writes the list in whichever spelling they think
    in; both sides are canonicalised."""
    settings = AppSettings(blocked_hosts=("bücher.example",), block_private_targets=False)
    with pytest.raises(InvalidURL):
        normalise_url("https://xn--bcher-kva.example/", settings)


def test_c08_subdomains_of_a_unicode_blocked_host_are_caught():
    settings = AppSettings(blocked_hosts=("bücher.example",), block_private_targets=False)
    with pytest.raises(InvalidURL):
        normalise_url("https://deep.sub.bücher.example/x", settings)
    assert normalise_url("https://notbücher.example/x", settings)


def test_c08_the_stored_host_is_the_canonical_one():
    assert normalise_url("https://BÜCHER.example./x", OPEN) == "https://xn--bcher-kva.example/x"
    assert normalise_url("https://EXAMPLE.ORG/x", OPEN) == "https://example.org/x"


# -- C-16 -- the port ------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "http://example.org:99999/",
    "http://example.org:abc/",
    "http://example.org:-1/",
    "http://example.org:65536/",
])
def test_c16_an_invalid_port_is_refused_and_does_not_crash(raw):
    """`parts.port` is lazy and raises. My own 2.0.1 fix read it inside
    to_wire_url, so a bad port became a 500 instead of a refusal."""
    with pytest.raises(InvalidURL) as caught:
        normalise_url(raw, OPEN)
    assert caught.value.msgid == "error_url_port"


def test_c16_a_valid_port_survives_canonicalisation():
    assert normalise_url("http://example.org:8080/x", OPEN) == "http://example.org:8080/x"


def test_c16_to_wire_url_never_raises_on_a_legacy_row():
    """Rows imported verbatim from 2016 never went through creation, so
    the redirect view must survive whatever they carry."""
    assert to_wire_url("http://example.org:99999/x")
    assert to_wire_url("http://example.org:abc/x")
    assert to_wire_url("http://[not-an-ipv6]/x")
    assert to_wire_url("not a url at all")


def test_c16_the_redirect_answers_for_a_legacy_row_with_a_bad_port(testapp):
    from sqlalchemy import text

    engine = testapp.app.registry["dbengine"]
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO links (code, url, url_sha256, created_at, hits) "
                 "VALUES ('badport', :u, :s, '2016-01-01 00:00:00', 0)"),
            {"u": "http://example.org:99999/x", "s": "1" * 64},
        )
    testapp.get("/badport", status=302)


# -- the canonicaliser itself ---------------------------------------------

def test_canonical_host_is_lenient_when_asked():
    """`strict=False` is what to_wire_url uses: it must return
    something for every input, never raise."""
    for host in ("", "1.2.3.4.5", "not..a..host", "xn--", "münchen.example"):
        value, _address = canonical_host(host, strict=False)
        assert isinstance(value, str)


def test_canonical_host_compresses_an_ipv6_literal():
    value, address = canonical_host("2001:0db8:0000:0000:0000:0000:0000:0001")
    assert value == "[2001:db8::1]"
    assert address is not None


# -- C-01 -- the language switcher is not a redirector --------------------

OPEN_REDIRECT_ATTEMPTS = [
    r"/\evil.example",          # WHATWG reads the backslash as a separator
    r"/\/evil.example",
    r"/\\evil.example",
    "//evil.example",
    "///evil.example",
    "https://evil.example/",
    "http:evil.example",
    "//evil.example/%2e%2e",
    r"\\evil.example",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "/%5Cevil.example",         # arrives decoded as /\evil.example
    "/..//evil.example",
    "/\tevil.example",
    "/\r\nLocation: https://evil.example/",
    "/nosuch1",                 # a real path, but not a returnable route
    "/api/v1/links/abc",        # a real route, not a page
    "/healthz",                 # a real route, not a page
    "",
]


@pytest.mark.parametrize("attempt", OPEN_REDIRECT_ATTEMPTS)
def test_c01_the_switcher_never_leaves_the_site(testapp, attempt):
    response = testapp.get("/locale/fr", params={"came_from": attempt}, status=303)
    location = response.headers["Location"]
    assert "evil.example" not in location
    assert location.endswith("/")
    # Nothing the caller sent survives into the answer.
    assert "\\" not in location and "\r" not in location and "\n" not in location


def test_c01_the_backslash_case_specifically(testapp):
    """The one the string filter let through: it starts with '/' and
    does not start with '//', so the old guard was happy."""
    old_guard_would_accept = (
        "/\\evil.example".startswith("/") and not "/\\evil.example".startswith("//")
    )
    assert old_guard_would_accept, "the old guard really did accept this"
    response = testapp.get("/locale/fr", params={"came_from": "/\\evil.example"}, status=303)
    assert response.headers["Location"].endswith("/")


def test_c01_a_legitimate_return_still_works(testapp):
    response = testapp.get("/locale/fr", params={"came_from": "/"}, status=303)
    assert response.headers["Location"].endswith("/")
    assert "_LOCALE_=fr" in response.headers["Set-Cookie"]
    assert "Transformez une adresse longue" in testapp.get("/").text


def test_c01_the_answer_is_regenerated_not_echoed():
    """The location is built by route_path from a matched route name,
    so no character the caller supplied can reach it."""
    from pyramid import testing

    from urlshortener.views import safe_return_path

    config = testing.setUp()
    config.include("urlshortener.routes")
    try:
        request = testing.DummyRequest()
        request.registry = config.registry
        assert safe_return_path(request, "/") == "/"
        assert safe_return_path(request, "/?x=1#frag") == "/"
        assert safe_return_path(request, None) == "/"
    finally:
        testing.tearDown()


def test_c01_every_route_is_either_returnable_or_explicitly_refused():
    """A new route must not silently inherit a default. Either it is a
    page one can come back to, or the reason it is not is written down."""
    from pyramid.config import Configurator

    from urlshortener.views import NON_RETURNABLE_ROUTES, RETURNABLE_ROUTES

    config = Configurator()
    config.include("urlshortener.routes")
    config.commit()
    names = {route.name for route in config.get_routes_mapper().get_routes()}
    decided = RETURNABLE_ROUTES | set(NON_RETURNABLE_ROUTES)
    assert names <= decided, "undecided routes: %s" % sorted(names - decided)
    assert not (RETURNABLE_ROUTES & set(NON_RETURNABLE_ROUTES))


def test_c01_the_catch_all_redirect_is_never_returnable():
    from urlshortener.views import RETURNABLE_ROUTES

    assert "redirect" not in RETURNABLE_ROUTES, (
        "/{code} matches everything; returning to it would walk the "
        "visitor off the site under our own domain"
    )
