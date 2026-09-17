# -*- coding: utf-8 -*-
"""How the admin hash travels (train 0028).

A real deployment refused to start: the hash reached the container as
`pbkdf200000…`, because the hash was embedded in an unquoted shell
assignment. `$600000` is `$6` followed by `00000`; each hexadecimal
field expands differently depending on its first character. The exact
corrupted value is not a constant. The hypothesis on the field was
"the container has different seeds" — worth pinning the refutation:
the salt travels IN the string, so the same value verifies anywhere,
and what failed was the SHAPE check on an altered string.
"""
import shlex
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


@pytest.mark.parametrize("salt", [
    pytest.param(b"\xce" * 16, id="letter-salt-letter-digest"),
    pytest.param(b"\xab" * 16, id="letter-salt-digit-digest"),
    pytest.param(b"\x14" * 16, id="digit-salt-letter-digest"),
    pytest.param(b"\x12" * 16, id="digit-salt-digit-digest"),
    pytest.param(b"\x00" * 16, id="zero-salt"),
    pytest.param(b"\xae" * 16, id="zero-digest"),
])
def test_an_unquoted_shell_eats_the_hash_and_validate_refuses(monkeypatch, salt):
    """Test corruption, not one accidental result of random hex prefixes."""
    def fixed_salt(size):
        assert size == len(salt)
        return salt

    # Only this test fixes the salt; production still uses secrets.
    monkeypatch.setattr(
        "urlshortener.tools.hash_password.secrets.token_bytes", fixed_salt
    )
    real = hash_password("x")
    AppSettings(admin_password_hash=real).validate()

    def through_shell(assignment):
        return subprocess.run(
            [
                "bash", "--noprofile", "--norc", "-c",
                'H=%s; printf "%%s\\n" "$H"' % assignment,
                "hash-transit-test",  # Explicit $0 for hex fields starting in 0.
            ],
            # Do not inherit BASH_ENV, shell options, or variables whose
            # names happen to match one of the generated hex fields.
            env={}, capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()

    mangled = through_shell(real)
    assert mangled.startswith("pbkdf200000")
    assert mangled != real
    assert "$" not in mangled
    with pytest.raises(ConfigurationError) as caught:
        AppSettings(admin_password_hash=mangled).validate()
    assert "pbkdf2$iterations$salt$hash" in str(caught.value)

    # Positive control: protect the assignment, not just the later print.
    preserved = through_shell(shlex.quote(real))
    assert preserved == real
    AppSettings(admin_password_hash=preserved).validate()


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
