# -*- coding: utf-8 -*-
"""Internationalised host names, encoded the way a browser encodes them.

External audit, second pass, finding D-01. Python's built-in `idna`
codec implements RFC 3490 (IDNA2003); a browser follows the URL
Standard, which is UTS #46 with non-transitional processing. The two
disagree on names that exist, and a shortener that resolves a host
differently from the browser which will follow the link sends people
to a domain they did not ask for.

The same class of defect as the non-ASCII `Location:` of 2.0.1 — and
it was introduced by the canonicalisation train meant to close that
class, which is why these tests exist rather than a comment.
"""
import pytest

from urlshortener.constants_and_globals import AppSettings
from urlshortener.urlvalidation import InvalidURL, canonical_host, normalise_url

OPEN = AppSettings(base_url="http://s.test/", block_private_targets=False)
GUARDED = AppSettings(base_url="http://s.test/", block_private_targets=True)


# -- D-01 -- the names the two standards disagree about -------------------

@pytest.mark.parametrize("host,browser,codec", [
    # The example the Unicode consortium itself uses.
    ("faß.de", "xn--fa-hia.de", "fass.de"),
    ("faß.example", "xn--fa-hia.example", "fass.example"),
    # Greek final sigma: the codec rewrites the whole label.
    ("βόλος.com", "xn--nxasmm1c.com", "xn--nxasmq6b.com"),
])
def test_d01_a_disputed_name_is_encoded_as_a_browser_does(host, browser, codec):
    assert canonical_host(host)[0] == browser
    # And the old behaviour really was the other one, so this test
    # describes a difference rather than a preference.
    assert host.encode("idna").decode("ascii") == codec
    assert browser != codec


def test_d01_the_stored_url_is_the_one_the_visitor_will_reach():
    """`fass.de` and `faß.de` can have different owners. Storing the
    wrong one means the shortener redirects somewhere else than the
    address it was handed."""
    assert normalise_url("https://faß.de/x", OPEN) == "https://xn--fa-hia.de/x"


def test_d01_the_redirect_matches_what_was_shortened(testapp):
    short = testapp.get("/", params={"url": "https://faß.de/x"}).json["short_url"]
    response = testapp.get("/" + short.rsplit("/", 1)[-1], status=302)
    assert response.headers["Location"] == "https://xn--fa-hia.de/x"


def test_d01_the_punycode_form_and_the_unicode_form_are_one_link(dbsession):
    """They are the same host, so they must de-duplicate to one code —
    which they only do if both spellings canonicalise the same way."""
    from urlshortener.services import count_links, create_link

    first, created_first = create_link(dbsession, "https://faß.de/x", OPEN)
    second, created_second = create_link(dbsession, "https://xn--fa-hia.de/x", OPEN)
    assert created_first is True and created_second is False
    assert first.code == second.code
    assert count_links(dbsession) == 1


def test_d01_blocked_hosts_use_the_browser_encoding_too():
    """The blocklist canonicalises both sides; under IDNA2003 a list
    entry written `faß.de` produced `fass.de` and blocked the wrong
    domain while letting the right one through."""
    settings = AppSettings(blocked_hosts=("faß.de",), block_private_targets=False)
    with pytest.raises(InvalidURL) as caught:
        normalise_url("https://xn--fa-hia.de/x", settings)
    assert caught.value.msgid == "error_url_blocked"
    # ... and `fass.de`, a DIFFERENT domain, is not caught by that entry.
    assert normalise_url("https://fass.de/x", settings)


# -- names that already worked and must keep working ----------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://münchen.example/", "https://xn--mnchen-3ya.example/"),
    ("https://bücher.example/", "https://xn--bcher-kva.example/"),
    ("https://BÜCHER.example./x", "https://xn--bcher-kva.example/x"),
    ("https://ΣΊΣΥΦΟΣ.gr/", "https://xn--kxa6akbbkh.gr/"),
    ("https://EXAMPLE.ORG/x", "https://example.org/x"),
    ("http://sub.domain.example.co.uk/p", "http://sub.domain.example.co.uk/p"),
    ("http://a-b.example.org/", "http://a-b.example.org/"),
    ("http://xn--bcher-kva.example/", "http://xn--bcher-kva.example/"),
])
def test_ordinary_names_are_unchanged(raw, expected):
    assert normalise_url(raw, OPEN) == expected


@pytest.mark.parametrize("raw", ["http://intranet/", "http://localhost/"])
def test_a_single_label_host_is_still_accepted(raw):
    """An intranet name has no dot; the encoder must not treat that as
    a malformed name."""
    assert normalise_url(raw, OPEN)


def test_the_private_guard_still_sees_localhost():
    with pytest.raises(InvalidURL) as caught:
        normalise_url("http://localhost/", GUARDED)
    assert caught.value.msgid == "error_url_private"


@pytest.mark.parametrize("raw", [
    "<script>alert(1)</script>",
    "http://exa mple.org/",
    "http://-example.org/",
    "http://exam_ple.org/",
    "http://.example.org/",
])
def test_malformed_hosts_are_still_refused(raw):
    with pytest.raises(InvalidURL) as caught:
        normalise_url(raw, OPEN)
    assert caught.value.msgid == "error_url_host"


def test_the_lenient_mode_never_raises():
    """`to_wire_url` runs against rows imported verbatim from 2016 and
    must survive whatever they carry, including a name no encoder
    accepts."""
    for host in ("", "-bad-", "xn--", "a" * 300, "exa mple.org"):
        value, _address = canonical_host(host, strict=False)
        assert isinstance(value, str)


def test_the_dependency_is_declared_and_locked():
    """The built-in codec needed no dependency, so replacing it adds
    one — an unlocked import would fail only in the container."""
    import os
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as handle:
        assert re.search(r'^\s*"idna[><=]', handle.read(), re.MULTILINE)
    for lock in ("requirements.lock", "requirements-test.lock"):
        with open(os.path.join(root, lock), encoding="utf-8") as handle:
            assert re.search(r"^idna==", handle.read(), re.MULTILINE), lock
