# -*- coding: utf-8 -*-
"""The runtime .ini derivation."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docker"))

import apply_server_overrides as helper  # noqa: E402


def _run(tmp_path, environ):
    source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "production.ini")
    destination = str(tmp_path / "runtime.ini")
    saved = dict(os.environ)
    os.environ.update(environ)
    try:
        assert helper.main(["apply_server_overrides.py", source, destination]) == 0
    finally:
        os.environ.clear()
        os.environ.update(saved)
    with open(destination, encoding="utf-8") as handle:
        return handle.read()


def test_listen_is_overridden_from_the_environment(tmp_path):
    body = _run(tmp_path, {"URLSHORTENER_LISTEN": "0.0.0.0:5123"})
    assert "listen = 0.0.0.0:5123" in body


def test_the_database_url_is_overridden(tmp_path):
    body = _run(tmp_path, {"SQLALCHEMY_URL": "sqlite:////data/x.sqlite"})
    assert "sqlalchemy.url = sqlite:////data/x.sqlite" in body


def test_here_is_resolved_against_the_source_directory(tmp_path):
    """The copy lives in var/, so an unresolved %(here)s would make
    pserve build the database path from the WRONG directory."""
    body = _run(tmp_path, {})
    assert "%(here)s" not in body
    assert "/var/urlshortener.sqlite" in body


def test_an_absent_variable_changes_nothing(tmp_path):
    body = _run(tmp_path, {})
    assert "listen = localhost:5123" in body


def test_the_source_file_is_never_modified(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = os.path.join(root, "production.ini")
    with open(source, encoding="utf-8") as handle:
        before = handle.read()
    _run(tmp_path, {"URLSHORTENER_LISTEN": "0.0.0.0:5123"})
    with open(source, encoding="utf-8") as handle:
        assert handle.read() == before


def test_a_database_password_is_not_printed(tmp_path, capsys):
    _run(tmp_path, {"SQLALCHEMY_URL": "postgresql+psycopg://u:secret@db/urlshortener"})
    assert "secret" not in capsys.readouterr().out
