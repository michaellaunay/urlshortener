# -*- coding: utf-8 -*-
"""The first command of the README, on a tree that has never run.

Train 0017 fixed the transaction the CLI never opened. This file
characterises the OTHER half of the same gesture: on a fresh clone
`var/` does not exist — it is gitignored — so SQLite answered `unable to
open database file` and the documented first step still failed, for a
second reason, on exactly the installs the first fix was written for.
"""
import os

import pytest
from sqlalchemy import create_engine

from urlshortener.upgrades import ensure_database_directory, main


def _ini(tmp_path, database):
    ini = tmp_path / "fresh.ini"
    ini.write_text(
        "[app:main]\nuse = egg:urlshortener\n"
        "sqlalchemy.url = sqlite:///%s\n"
        "urlshortener.base_url = http://short.test/\n"
        "urlshortener.throttle_max_creations = 0\n"
        "urlshortener.cors_origins =\n\n"
        "[server:main]\nuse = egg:waitress#main\nlisten = localhost:0\n\n"
        "[loggers]\nkeys = root\n\n[handlers]\nkeys = console\n\n"
        "[formatters]\nkeys = generic\n\n"
        "[logger_root]\nlevel = WARN\nhandlers = console\n\n"
        "[handler_console]\nclass = StreamHandler\nargs = (sys.stderr,)\n"
        "level = NOTSET\nformatter = generic\n\n"
        "[formatter_generic]\nformat = %%(message)s\n" % database,
        encoding="utf-8",
    )
    return str(ini)


def test_the_directory_is_created_when_it_is_missing(tmp_path):
    missing = tmp_path / "var" / "sub"
    engine = create_engine("sqlite:///%s" % (missing / "urlshortener.sqlite"))
    assert not missing.exists()
    ensure_database_directory(engine)
    assert missing.is_dir()
    engine.dispose()


def test_an_existing_directory_is_left_alone(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "x.sqlite"))
    ensure_database_directory(engine)
    ensure_database_directory(engine)      # twice: no error
    engine.dispose()


@pytest.mark.parametrize("url", [
    "sqlite://",
    "sqlite:///:memory:",
    "postgresql+psycopg://user:secret@db.example/urlshortener",
])
def test_nothing_is_created_for_a_database_without_a_file(url):
    """An in-memory database has no directory, and a PostgreSQL URL has
    no business making the client create anything on disk."""
    engine = create_engine(url) if not url.startswith("postgresql") else None
    if engine is None:
        from sqlalchemy.engine import make_url

        class _Fake:
            pass

        fake = _Fake()
        fake.url = make_url(url)
        ensure_database_directory(fake)
        return
    ensure_database_directory(engine)
    engine.dispose()


def test_the_readme_first_command_works_on_a_tree_that_has_never_run(tmp_path):
    """End to end, through the real CLI and the real bootstrap: a
    database path whose parent does not exist yet."""
    database = tmp_path / "var" / "urlshortener.sqlite"
    assert not database.parent.exists()
    assert main(["upgrades", _ini(tmp_path, database)]) == 0
    assert database.exists()


def test_it_is_still_idempotent_from_a_fresh_tree(tmp_path):
    database = tmp_path / "var" / "urlshortener.sqlite"
    ini = _ini(tmp_path, database)
    assert main(["upgrades", ini]) == 0
    assert main(["upgrades", ini]) == 0
    assert os.path.exists(database)
