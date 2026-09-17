# -*- coding: utf-8 -*-
"""How the admin hash travels (train 0028).

A real deployment refused to start: the hash reached the container as
`pbkdf200000…`, because an unquoted shell had expanded `$600000`,
`$salt` and `$hash` as empty variables. The hypothesis on the field was
"the container has different seeds" — worth pinning the refutation:
the salt travels IN the string, so the same value verifies anywhere,
and what failed was the SHAPE check on an altered string.
"""
import subprocess

import pytest

from urlshortener.constants_and_globals import AppSettings, ConfigurationError
from urlshortener.tools.hash_password import hash_password


def test_the_generator_and_the_validator_agree():
    """The exact class of the field incident, one remove away: the
    tool prints a shape validate() must accept, forever."""
    AppSettings(admin_password_hash=hash_password("any")).validate()


def test_the_hash_is_machine_independent():
    stored = hash_password("s3cret")
    from urlshortener.admin import verify_password

    assert verify_password("s3cret", stored)
    # Same string, "another machine": nothing but the string matters.
    assert verify_password("s3cret", str(stored))


def test_an_unquoted_shell_eats_the_hash_and_validate_refuses():
    """The reproduced field failure, end to end."""
    real = hash_password("x")
    mangled = subprocess.run(
        ["bash", "-c", "H=%s; echo $H" % real],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert mangled == "pbkdf200000"
    with pytest.raises(ConfigurationError) as caught:
        AppSettings(admin_password_hash=mangled).validate()
    assert "pbkdf2$iterations$salt$hash" in str(caught.value)


def test_the_file_form_resolves_to_the_hash(tmp_path):
    stored = hash_password("x")
    secret = tmp_path / "admin.hash"
    secret.write_text(stored + "\n", encoding="utf-8")
    settings = AppSettings.from_settings(
        {"urlshortener.admin_password_hash_file": str(secret)}
    )
    assert settings.admin_password_hash == stored
    settings.validate()


def test_both_sources_at_once_are_refused(tmp_path):
    secret = tmp_path / "admin.hash"
    secret.write_text(hash_password("x"), encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        AppSettings.from_settings({
            "urlshortener.admin_password_hash": hash_password("y"),
            "urlshortener.admin_password_hash_file": str(secret),
        })
    assert "choose one" in str(caught.value)


@pytest.mark.parametrize("content", [None, ""])
def test_a_missing_or_empty_file_is_refused_with_its_path(tmp_path, content):
    secret = tmp_path / "admin.hash"
    if content is not None:
        secret.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        AppSettings.from_settings(
            {"urlshortener.admin_password_hash_file": str(secret)}
        )
    assert str(secret) in str(caught.value)
