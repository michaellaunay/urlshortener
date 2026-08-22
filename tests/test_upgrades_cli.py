"""The CLI upgrade path, characterised end to end.

``python -m urlshortener.upgrades <config.ini>`` is the deployment
gesture — the container entrypoint and the bare-metal runbook both run
it before the first request. It bootstraps the full application, which
wires pyramid_tm's EXPLICIT transaction manager (models.includeme):
outside a request nothing has begun a transaction, so the CLI must
drive the manager itself. Regression pinned here: before the fix, the
first session read raised ``transaction.interfaces.NoTransaction`` on
every fresh bare-metal install following the README.
"""
import sqlite3

from urlshortener.upgrades import SCHEMA_VERSION, main


def _write_ini(tmp_path):
    database = tmp_path / "cli.sqlite"
    ini = tmp_path / "cli.ini"
    ini.write_text(
        f"""[app:main]
use = egg:urlshortener

sqlalchemy.url = sqlite:///{database}

urlshortener.base_url = http://short.test/
urlshortener.block_private_targets = false
urlshortener.throttle_max_creations = 0
urlshortener.cors_origins =

[server:main]
use = egg:waitress#main
listen = localhost:0

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(message)s
"""
    )
    return ini, database


def _stamped_version(database):
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "select version from schema_version"
        ).fetchone()
    return row[0]


def test_cli_creates_schema_and_stamps_it(tmp_path):
    ini, database = _write_ini(tmp_path)
    assert main(["upgrades", str(ini)]) == 0
    assert _stamped_version(database) == SCHEMA_VERSION


def test_cli_is_idempotent(tmp_path):
    ini, database = _write_ini(tmp_path)
    assert main(["upgrades", str(ini)]) == 0
    assert main(["upgrades", str(ini)]) == 0
    assert _stamped_version(database) == SCHEMA_VERSION
