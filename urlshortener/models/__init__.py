# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Database wiring: engine, session factory, per-request session.

Standard Pyramid/SQLAlchemy arrangement: `pyramid_tm` opens a
transaction around the request, `zope.sqlalchemy` joins the session to
it, so a view that raises leaves nothing half-written and a view that
returns commits once.
"""
from __future__ import annotations

import zope.sqlalchemy
from sqlalchemy import engine_from_config, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .link import Link, SchemaVersion, url_digest, utcnow  # noqa: F401  (re-export)
from .meta import Base

__all__ = [
    "Base",
    "Link",
    "SchemaVersion",
    "url_digest",
    "utcnow",
    "get_engine",
    "get_session_factory",
    "get_tm_session",
    "includeme",
]


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite ignores foreign keys unless asked, once per connection."""
    module = type(dbapi_connection).__module__
    if module.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL lets a redirect read while a creation writes, instead of
        # the whole file being locked. Harmless on a fresh file, and a
        # no-op for a non-file database.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


event.listen(Engine, "connect", _enable_sqlite_foreign_keys)


def get_engine(settings, prefix="sqlalchemy."):
    return engine_from_config(settings, prefix)


def get_session_factory(engine):
    factory = sessionmaker()
    factory.configure(bind=engine)
    return factory


def get_tm_session(session_factory, transaction_manager, request=None):
    """A session joined to `transaction_manager` for this request."""
    dbsession = session_factory(info={"request": request})
    zope.sqlalchemy.register(dbsession, transaction_manager=transaction_manager)
    return dbsession


def includeme(config):
    """Register `request.dbsession`, created lazily, closed by Pyramid."""
    settings = config.get_settings()
    settings.setdefault("tm.manager_hook", "pyramid_tm.explicit_manager")

    config.include("pyramid_tm")
    config.include("pyramid_retry")

    engine = get_engine(settings)
    session_factory = get_session_factory(engine)
    config.registry["dbsession_factory"] = session_factory
    config.registry["dbengine"] = engine

    config.add_request_method(
        lambda request: get_tm_session(
            session_factory, request.tm, request=request
        ),
        "dbsession",
        reify=True,
    )
