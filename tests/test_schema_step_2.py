# -*- coding: utf-8 -*-
"""Schema step 2: the columns land on a database that predates them."""
import sqlite3

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from urlshortener.upgrades import SCHEMA_VERSION, run_pending_upgrades


def _v1_database(path):
    """A links table as version 1 shipped it — no blocked_at, no
    requested_by_email — with one row, so data survival is visible."""
    connection = sqlite3.connect(str(path))
    connection.executescript(
        """
        CREATE TABLE links (
            id INTEGER PRIMARY KEY,
            code VARCHAR(32) NOT NULL UNIQUE,
            url TEXT NOT NULL,
            url_sha256 VARCHAR(64) NOT NULL,
            created_at TIMESTAMP NOT NULL,
            hits BIGINT NOT NULL,
            last_hit_at TIMESTAMP
        );
        CREATE TABLE schema_version (
            id INTEGER PRIMARY KEY, version INTEGER NOT NULL,
            updated_at TIMESTAMP NOT NULL
        );
        INSERT INTO schema_version VALUES (1, 1, '2026-01-01');
        INSERT INTO links VALUES
            (1, 'old', 'https://example.org/', 'a', '2026-01-01', 7, NULL);
        """
    )
    connection.commit()
    connection.close()


def test_step_2_adds_the_columns_and_keeps_the_rows(tmp_path):
    database = tmp_path / "v1.sqlite"
    _v1_database(database)
    engine = create_engine("sqlite:///%s" % database)
    with Session(engine) as dbsession:
        run_pending_upgrades(dbsession)
        dbsession.commit()
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT code, hits, blocked_at, requested_by_email FROM links")
        ).one()
        version = connection.execute(text("SELECT version FROM schema_version")).scalar_one()
    engine.dispose()
    assert row[:2] == ("old", 7)
    assert row[2] is None and row[3] is None
    assert version == SCHEMA_VERSION


def test_step_2_is_idempotent(tmp_path):
    database = tmp_path / "v1.sqlite"
    _v1_database(database)
    engine = create_engine("sqlite:///%s" % database)
    for _round in (1, 2):
        with Session(engine) as dbsession:
            run_pending_upgrades(dbsession)
            dbsession.commit()
    engine.dispose()
