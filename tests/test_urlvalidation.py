# -*- coding: utf-8 -*-
"""What the 2016 service accepted, and what this one refuses."""
import pytest

from urlshortener.constants_and_globals import AppSettings
from urlshortener.urlvalidation import InvalidURL, normalise_url

OPEN = AppSettings(base_url="http://s.test/", block_private_targets=False)
GUARDED = AppSettings(base_url="http://s.test/", block_private_targets=True)


def test_absolute_url_passes_through():
    assert normalise_url("https://example.org/a/b?c=d#e", OPEN) == "https://example.org/a/b?c=d#e"


def test_missing_scheme_is_completed_like_2016():
    # The old code did exactly this and clients depend on it.
    assert normalise_url("example.org/x", OPEN) == "http://example.org/x"


def test_surrounding_whitespace_is_trimmed():
    assert normalise_url("  https://example.org/  ", OPEN) == "https://example.org/"


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_input_is_refused(raw):
    with pytest.raises(InvalidURL) as caught:
        normalise_url(raw, OPEN)
    assert caught.value.msgid == "error_url_required"


@pytest.mark.parametrize("raw", [
    "javascript:alert(document.cookie)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "file:///etc/passwd",
    "ftp://example.org/x",
])
def test_dangerous_schemes_are_refused(raw):
    # 2016 stored these verbatim and later emitted them in Location:.
    with pytest.raises(InvalidURL) as caught:
        normalise_url(raw, OPEN)
    assert caught.value.msgid == "error_url_scheme"


def test_credentials_in_the_authority_are_refused():
    with pytest.raises(InvalidURL) as caught:
        normalise_url("https://www.your-bank.example@evil.test/", OPEN)
    assert caught.value.msgid == "error_url_credentials"


def test_control_characters_are_refused():
    with pytest.raises(InvalidURL) as caught:
        normalise_url("https://example.org/\r\nLocation: https://evil.test", OPEN)
    assert caught.value.msgid == "error_url_control_characters"


def test_too_long_is_refused():
    settings = AppSettings(max_url_length=64, block_private_targets=False)
    with pytest.raises(InvalidURL) as caught:
        normalise_url("https://example.org/" + "a" * 200, settings)
    assert caught.value.msgid == "error_url_too_long"


@pytest.mark.parametrize("raw", [
    "http://127.0.0.1:6543/admin",
    "http://localhost/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
])
def test_private_targets_are_refused_when_guarded(raw):
    with pytest.raises(InvalidURL) as caught:
        normalise_url(raw, GUARDED)
    assert caught.value.msgid == "error_url_private"


def test_private_targets_pass_when_the_guard_is_off():
    assert normalise_url("http://127.0.0.1:6543/x", OPEN) == "http://127.0.0.1:6543/x"


def test_a_name_is_never_resolved():
    # Documented limit: only literal addresses are caught. A name that
    # happens to resolve to 127.0.0.1 passes, and that is on purpose --
    # see the module docstring.
    assert normalise_url("http://internal.example.com/", GUARDED)


def test_blocked_hosts_cover_subdomains():
    settings = AppSettings(blocked_hosts=("evil.test",), block_private_targets=False)
    with pytest.raises(InvalidURL) as caught:
        normalise_url("https://deep.sub.evil.test/x", settings)
    assert caught.value.msgid == "error_url_blocked"
    # A name that merely ends with the same letters is NOT a subdomain.
    assert normalise_url("https://notevil.test/x", settings)


def test_missing_host_is_refused():
    with pytest.raises(InvalidURL) as caught:
        normalise_url("http:///just/a/path", OPEN)
    assert caught.value.msgid == "error_url_host"


@pytest.mark.parametrize("raw", [
    "<script>alert(1)</script>",
    "http://exa mple.org/",
    "http://-example.org/",
    "http://exam_ple.org/",
    "http://.example.org/",
    "http://[not-an-ipv6]/",
])
def test_a_malformed_host_is_refused(raw):
    with pytest.raises(InvalidURL) as caught:
        normalise_url(raw, OPEN)
    assert caught.value.msgid == "error_url_host"


@pytest.mark.parametrize("raw", [
    "https://münchen.example/",
    "https://example.org./",
    "https://sub.domain.example.co.uk/path",
    "http://198.51.100.7:8080/x",
    "http://[2001:db8::1]/x",
])
def test_legitimate_hosts_pass(raw):
    assert normalise_url(raw, OPEN)
