# -*- coding: utf-8 -*-
"""Start-up refuses a configuration that cannot work (train 0009).

External audit 2026-08-22, finding C-17: `from_settings` accepted
anything. `code_length = 0` started cleanly and failed hours later, on
the first attempt to shorten something, with a ValueError about an
alphabet — an error message produced by a typo in an .ini file, in a
place that says nothing about where the typo is.
"""
import pytest
from pyramid.paster import get_appsettings

from urlshortener import codec, main
from urlshortener.constants_and_globals import (
    MAX_CODE_LENGTH,
    MIN_CODE_LENGTH,
    AppSettings,
    ConfigurationError,
)
from urlshortener.models import Base
from tests.conftest import TESTING_INI


def _start_with(**overrides):
    settings = get_appsettings(TESTING_INI, name="main")
    settings.update(overrides)
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    app.registry["dbengine"].dispose()
    return app


# -- what must start -------------------------------------------------------

def test_the_defaults_are_valid():
    assert AppSettings().validate() is not None


@pytest.mark.parametrize("path", ["production.ini", "development.ini", "testing.ini"])
def test_every_shipped_configuration_is_valid(path):
    """A file we ship that would refuse to start is a trap."""
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings = get_appsettings(os.path.join(root, path), name="main")
    AppSettings.from_settings(dict(settings)).validate()


def test_the_bounds_mirror_the_codec():
    """Two copies of one number: a lock, so they cannot part ways."""
    assert (MIN_CODE_LENGTH, MAX_CODE_LENGTH) == (
        codec.MIN_CODE_LENGTH, codec.MAX_CODE_LENGTH
    )


# -- what must not ---------------------------------------------------------

@pytest.mark.parametrize("kwargs,marker", [
    ({"code_length": 0}, "code_length"),
    ({"code_length": 99}, "code_length"),
    ({"code_max_attempts": 0}, "code_max_attempts"),
    ({"max_url_length": 8}, "max_url_length"),
    ({"max_body_bytes": -1}, "negative"),
    ({"base_url": "example.org/"}, "absolute"),
    ({"base_url": "https://example.org"}, "must end with"),
    ({"base_url": "ftp://example.org/"}, "absolute"),
    ({"allowed_schemes": ()}, "cannot be empty"),
    ({"allowed_schemes": ("http", "javascript")}, "javascript"),
    ({"default_scheme": "gopher"}, "default_scheme"),
    ({"throttle_max_creations": 5, "throttle_window_seconds": 0}, "throttle_window_seconds"),
    ({"throttle_max_reads": 5, "throttle_window_seconds": 0}, "throttle_window_seconds"),
    ({"cors_origins": ("https://friend.test/",)}, "not an origin"),
    ({"cors_origins": ("friend.test",)}, "not an origin"),
])
def test_an_impossible_setting_is_refused(kwargs, marker):
    with pytest.raises(ConfigurationError) as caught:
        AppSettings(**kwargs).validate()
    assert marker in str(caught.value)


def test_two_settings_each_valid_and_jointly_impossible():
    """The cross-check: with these numbers a URL of the maximum allowed
    length can never be submitted, because its envelope is refused
    first. Neither value is wrong on its own."""
    with pytest.raises(ConfigurationError) as caught:
        AppSettings(max_url_length=2048, max_body_bytes=1024).validate()
    assert "could never be submitted" in str(caught.value)


def test_a_dangerous_scheme_cannot_be_allowed():
    """`Location: javascript:...` under our own domain."""
    for scheme in ("javascript", "data", "vbscript"):
        with pytest.raises(ConfigurationError):
            AppSettings(allowed_schemes=("http", scheme)).validate()


def test_the_wildcard_origin_is_still_expressible():
    AppSettings(cors_origins=("*",)).validate()
    AppSettings(cors_origins=("https://friend.test", "http://a.test:8080")).validate()


# -- the operator sees everything at once ---------------------------------

def test_every_problem_is_reported_together():
    """Fixing a deployment file one restart per mistake is how an
    evening disappears."""
    with pytest.raises(ConfigurationError) as caught:
        AppSettings(
            code_length=0, base_url="nope", default_scheme="ftp", code_max_attempts=0
        ).validate()
    message = str(caught.value)
    assert "4 problem(s)" in message or "5 problem(s)" in message
    for marker in ("code_length", "base_url", "default_scheme", "code_max_attempts"):
        assert marker in message


def test_the_message_says_why_it_matters_not_just_what_is_wrong():
    with pytest.raises(ConfigurationError) as caught:
        AppSettings(base_url="https://example.org").validate()
    assert "must end with" in str(caught.value)


# -- start-up itself -------------------------------------------------------

def test_the_application_refuses_to_start():
    with pytest.raises(ConfigurationError):
        _start_with(**{"urlshortener.code_length": "0"})


def test_a_good_configuration_still_starts():
    assert _start_with() is not None


def test_validation_is_not_run_at_construction():
    """Deliberate: a test building an odd settings object on purpose
    must stay free to do so. The gate is start-up, not the dataclass."""
    settings = AppSettings(code_length=0)
    assert settings.code_length == 0
