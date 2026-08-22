# -*- coding: utf-8 -*-
"""Structural locks on what actually reaches the container (train 0004).

External audit 2026-08-22, findings C-07 and C-12. The class of bug
here is a setting that exists in three places -- the .env example, the
override helper, the entrypoint -- and is passed in by none of them.
Nothing fails; the operator simply gets a different service from the
one they configured.
"""
import os
import re
import stat
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCKER = os.path.join(ROOT, "docker")

sys.path.insert(0, DOCKER)
import apply_server_overrides as helper  # noqa: E402


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


def _compose_environment():
    """The keys of the service's `environment:` block, from the text.

    Read as text rather than through PyYAML on purpose: a duplicate key
    is what we are guarding against elsewhere, and safe_load hides it.
    """
    body = _read(DOCKER, "docker-compose.yaml")
    block = body[body.index("environment:"):body.index("ports:")]
    return {
        match.group(1)
        for match in re.finditer(r"^\s{6}([A-Z][A-Z0-9_]*):", block, re.MULTILINE)
    }


# -- C-07 -- the stack could not serve a single request -------------------

def test_c07_the_listen_address_is_passed_into_the_container():
    """`production.ini` binds localhost, which is right on bare metal
    and unreachable in a container: Docker forwards the published port
    to the container's INTERFACE, not to the loopback of its namespace.
    Without this variable every connection was refused."""
    assert "URLSHORTENER_LISTEN" in _compose_environment()
    body = _read(DOCKER, "docker-compose.yaml")
    assert "URLSHORTENER_LISTEN: ${URLSHORTENER_LISTEN:-0.0.0.0:5123}" in body


def test_c07_every_override_the_helper_knows_is_actually_forwarded():
    """An override nobody passes in is a setting the operator believes
    in and that never arrives."""
    passed = _compose_environment()
    missing = sorted(
        name for name in helper.OVERRIDES
        if name.startswith("URLSHORTENER_") and name not in passed
    )
    assert not missing, "declared as overridable but never forwarded: %s" % missing


def test_c07_the_env_example_documents_what_is_forwarded():
    documented = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", _read(ROOT, ".env.example"), re.MULTILINE))
    for name in ("URLSHORTENER_LISTEN", "URLSHORTENER_TRUSTED_PROXY"):
        assert name in documented


# -- C-07 -- the gateway, so client_addr is the visitor -------------------

def test_c07_the_default_gateway_is_read_from_the_routing_table(tmp_path):
    table = tmp_path / "route"
    table.write_text(
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"
        "eth0\t00000000\t0100A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
        "eth0\t0000A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
    )
    assert helper.default_gateway(str(table)) == "192.168.0.1"


def test_c07_a_table_without_a_default_route_yields_nothing(tmp_path):
    table = tmp_path / "route"
    table.write_text(
        "Iface\tDestination\tGateway \tFlags\n"
        "eth0\t0000A8C0\t00000000\t0001\n"
    )
    assert helper.default_gateway(str(table)) is None


def test_c07_a_missing_routing_table_is_not_an_error():
    assert helper.default_gateway("/nonexistent/route") is None


def _parser_with(trusted_proxy):
    from configparser import RawConfigParser

    parser = RawConfigParser()
    parser.optionxform = str
    parser.add_section("server:main")
    if trusted_proxy is not None:
        parser.set("server:main", "trusted_proxy", trusted_proxy)
    return parser


def test_c07_the_bare_metal_default_is_replaced_by_the_gateway(tmp_path):
    """Inside a container `trusted_proxy = 127.0.0.1` is not useless,
    it is wrong: waitress then ignores X-Forwarded-For and every
    visitor shares one address -- and therefore one rate-limit budget."""
    table = tmp_path / "route"
    table.write_text(
        "Iface\tDestination\tGateway \tFlags\n"
        "eth0\t00000000\t0100A8C0\t0003\n"
    )
    value, reason = helper.resolve_trusted_proxy(
        _parser_with("127.0.0.1"), {}, str(table)
    )
    assert value == "192.168.0.1"
    assert "gateway" in reason


def test_c07_an_explicit_value_always_wins(tmp_path):
    value, _reason = helper.resolve_trusted_proxy(
        _parser_with("127.0.0.1"), {"URLSHORTENER_TRUSTED_PROXY": "10.0.0.9"}, str(tmp_path)
    )
    assert value == "10.0.0.9"


def test_c07_none_trusts_no_proxy(tmp_path):
    value, reason = helper.resolve_trusted_proxy(
        _parser_with("127.0.0.1"), {"URLSHORTENER_TRUSTED_PROXY": "none"}, str(tmp_path)
    )
    assert value == ""
    assert "no proxy" in reason


def test_c07_an_operator_written_value_is_not_overwritten(tmp_path):
    table = tmp_path / "route"
    table.write_text("Iface\tDestination\tGateway \tFlags\neth0\t00000000\t0100A8C0\t0003\n")
    value, reason = helper.resolve_trusted_proxy(_parser_with("10.1.2.3"), {}, str(table))
    assert value is None
    assert "already set" in reason


def test_c07_bare_metal_is_left_alone_when_there_is_no_gateway(tmp_path):
    value, _reason = helper.resolve_trusted_proxy(
        _parser_with("127.0.0.1"), {}, "/nonexistent/route"
    )
    assert value is None


def test_c07_the_derived_ini_carries_the_resolved_proxy(tmp_path, monkeypatch):
    destination = str(tmp_path / "runtime.ini")
    monkeypatch.setenv("URLSHORTENER_TRUSTED_PROXY", "10.9.9.9")
    monkeypatch.setenv("URLSHORTENER_LISTEN", "0.0.0.0:5123")
    assert helper.main(["h", os.path.join(ROOT, "production.ini"), destination]) == 0
    body = _read(destination)
    assert "trusted_proxy = 10.9.9.9" in body
    assert "listen = 0.0.0.0:5123" in body


# -- C-12 -- the backup carries every URL ---------------------------------

def test_c12_the_backup_script_is_private_from_the_first_byte():
    body = _read(DOCKER, "backup.sh")
    assert "umask 077" in body
    assert body.index("umask 077") < body.index("install -d"), (
        "the umask must be set before anything is created, not after"
    )
    assert "install -d -m 700" in body
    # A chmod after the fact leaves a window; there must not be one.
    assert "chmod" not in body


def test_c12_the_backup_is_not_assembled_in_memory():
    """`mem_limit: 512m` and a database of unknown size do not mix."""
    body = _read(DOCKER, "backup.sh")
    assert '":memory:"' not in body and "':memory:'" not in body
    assert ".backup(" in body or "source.backup" in body


def test_c12_the_source_database_is_opened_read_only():
    assert "mode=ro" in _read(DOCKER, "backup.sh")


def test_c12_the_script_is_executable():
    mode = os.stat(os.path.join(DOCKER, "backup.sh")).st_mode
    assert mode & stat.S_IXUSR


@pytest.mark.parametrize("script", ["backup.sh", "init.sh", "start_urlshortener.sh"])
def test_the_shell_scripts_are_strict(script):
    assert "set -euo pipefail" in _read(DOCKER, script)
