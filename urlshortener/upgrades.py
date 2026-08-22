# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Schema version stamp and upgrade steps.

Same contract as AlirPunkto: every change to a persisted structure ADDS
a numbered step, steps are contiguous, each stamps itself, and running
them twice is a no-op. Version 1 is the schema created by this release;
it has no data migration to perform because there is nothing before it
in THIS database -- the 2016 data arrives through
`tools/import_legacy.py`, which is a different operation with a
different failure mode.

Run against a stopped application:

    python -m urlshortener.upgrades production.ini
"""
from __future__ import annotations

import os
import sys

from pyramid.paster import bootstrap, setup_logging
from sqlalchemy import select

from .models import Base, SchemaVersion, utcnow

#: Bump when a step is added. Must equal the highest step number.
SCHEMA_VERSION = 1


def _step_1(dbsession) -> None:
    """Initial schema. Tables are created by `create_all`; this stamps."""
    return None


#: Step number -> callable. Contiguity is asserted at import time, so a
#: missing number is a failure here and not a silent skip in production.
UPGRADE_STEPS = {
    1: _step_1,
}

assert sorted(UPGRADE_STEPS) == list(range(1, SCHEMA_VERSION + 1)), (
    "UPGRADE_STEPS must be contiguous from 1 to SCHEMA_VERSION"
)


def get_schema_version(dbsession) -> int:
    """Current stamp; 0 when the table is empty or absent."""
    row = dbsession.execute(select(SchemaVersion).limit(1)).scalar_one_or_none()
    return 0 if row is None else int(row.version)


def set_schema_version(dbsession, version: int) -> None:
    row = dbsession.execute(select(SchemaVersion).limit(1)).scalar_one_or_none()
    if row is None:
        dbsession.add(SchemaVersion(id=1, version=version, updated_at=utcnow()))
    else:
        row.version = version
        row.updated_at = utcnow()
    dbsession.flush()


def create_schema(engine) -> None:
    """Create any missing table. Existing tables are left untouched."""
    Base.metadata.create_all(engine)


def run_pending_upgrades(dbsession, commit_each=None) -> int:
    """Run every step above the current stamp. Returns the new version.

    Each step stamps itself, so a failure halfway leaves the stamp at
    the last step that actually succeeded -- a rerun resumes there
    instead of replaying what already worked.
    """
    current = get_schema_version(dbsession)
    for version in range(current + 1, SCHEMA_VERSION + 1):
        UPGRADE_STEPS[version](dbsession)
        set_schema_version(dbsession, version)
        if commit_each is not None:
            commit_each()
    return get_schema_version(dbsession)


def ensure_database_directory(engine) -> None:
    """Create the directory an SQLite file needs, if it is missing.

    The README's first gesture is `python -m urlshortener.upgrades
    development.ini`, and `development.ini` points at
    `%(here)s/var/urlshortener.sqlite`. `var/` is gitignored, so on a
    fresh clone it does not exist and SQLite answers `unable to open
    database file` -- the second way in a row that the documented first
    command failed on a fresh install. The container entrypoint already
    did `mkdir -p var`; bare metal was the odd one out.

    Only for an on-disk SQLite file: an in-memory database has no
    directory, and a PostgreSQL URL has no business making the client
    create anything.
    """
    url = engine.url
    if url.get_backend_name() != "sqlite" or not url.database:
        return
    if url.database == ":memory:":
        return
    directory = os.path.dirname(os.path.abspath(url.database))
    if directory:
        os.makedirs(directory, exist_ok=True)


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) < 2:
        print("usage: python -m urlshortener.upgrades <config_uri>", file=sys.stderr)
        return 2
    config_uri = argv[1]
    setup_logging(config_uri)
    env = bootstrap(config_uri)
    try:
        ensure_database_directory(env["registry"]["dbengine"])
        create_schema(env["registry"]["dbengine"])
        request = env["request"]
        dbsession = request.dbsession
        # The app runs under pyramid_tm's EXPLICIT manager (see
        # models.includeme): outside a request, nothing has begun a
        # transaction yet, and the first session read would raise
        # transaction.interfaces.NoTransaction. The CLI therefore
        # drives the manager itself: begin, commit-and-begin after
        # each step (keeping the resume-on-failure property), final
        # commit for the last segment.
        manager = getattr(request, "tm", None)
        if manager is not None:
            manager.begin()

            def commit_each():
                manager.commit()
                manager.begin()
        else:  # pragma: no cover - no transaction manager wired
            commit_each = None
        version = run_pending_upgrades(dbsession, commit_each=commit_each)
        if manager is not None:
            manager.commit()
        print("schema version: %d" % version)
    finally:
        env["closer"]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
