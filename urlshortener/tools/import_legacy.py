# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Import the 2016 SQLite database into the current schema.

The old service kept everything in one table:

    WEB_URL(ID INTEGER PRIMARY KEY AUTOINCREMENT,
            NUM TEXT NOT NULL UNIQUE,
            URL TEXT NOT NULL UNIQUE)

`NUM` is the short code that is printed on other people's pages, in
other people's emails and in KuneAgi content. It is imported VERBATIM:
codes are never re-minted, because a re-minted code is a dead link.

URLs are imported verbatim too, deliberately. Running them through
`normalise_url` would "fix" some of them -- and a fixed URL is a
different destination from the one the link has been promising for ten
years. Rows whose URL cannot be served safely (a scheme outside the
allowed list, control characters) are REPORTED and skipped rather than
silently altered; the operator decides what to do with the list.

Usage:

    python -m urlshortener.tools.import_legacy production.ini var/urls.db
    python -m urlshortener.tools.import_legacy production.ini var/urls.db --dry-run

Idempotent: a code already present is left untouched and counted as
`skipped_existing`, so an interrupted import is resumed by re-running it.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from urllib.parse import quote, urlsplit

from pyramid.paster import bootstrap, setup_logging
from sqlalchemy import select

from ..codec import is_valid_code
from ..models import Link, url_digest, utcnow

LEGACY_QUERY = "SELECT ID, NUM, URL FROM WEB_URL ORDER BY ID"


class ImportReport:
    def __init__(self):
        self.read = 0
        self.imported = 0
        self.skipped_existing = 0
        self.skipped_duplicate_url = 0
        self.rejected = []

    def reject(self, code, url, reason):
        self.rejected.append((code, url, reason))

    def as_text(self) -> str:
        lines = [
            "rows read              : %d" % self.read,
            "imported               : %d" % self.imported,
            "already present        : %d" % self.skipped_existing,
            "duplicate target URL   : %d" % self.skipped_duplicate_url,
            "rejected               : %d" % len(self.rejected),
        ]
        for code, url, reason in self.rejected:
            lines.append("  REJECTED %-12s %-8s %s" % (code, reason, url[:100]))
        return "\n".join(lines)


def read_legacy_rows(path):
    """Yield `(id, code, url)` from the legacy file, opened read-only.

    AUDIT 2026-08-22, finding S-03: the path used to be interpolated
    into the URI raw. A path containing '?' -- or worse, a crafted one
    ending in `?mode=rwc` -- turned the read-only guarantee off without
    a word, and the tool would then be writing to the very file the
    operator still needs for a rollback. Quoting the path keeps '?' a
    character of the FILENAME rather than the start of URI parameters.
    """
    uri = "file:%s?mode=ro" % quote(os.path.abspath(path))
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.text_factory = str
        for row in connection.execute(LEGACY_QUERY):
            yield row
    finally:
        connection.close()


def _acceptable(code, url, allowed_schemes):
    if not is_valid_code(code):
        return "bad_code"
    if not url:
        return "empty_url"
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        return "control_chars"
    scheme = (urlsplit(url).scheme or "").lower()
    if scheme not in allowed_schemes:
        return "scheme:%s" % (scheme or "none")
    return None


def import_rows(dbsession, rows, allowed_schemes, report=None):
    """Insert legacy rows. Returns an `ImportReport`."""
    report = report or ImportReport()
    for _legacy_id, code, url in rows:
        report.read += 1
        reason = _acceptable(code, url, allowed_schemes)
        if reason:
            report.reject(code, url or "", reason)
            continue

        if dbsession.execute(
            select(Link.id).where(Link.code == code)
        ).scalar_one_or_none() is not None:
            report.skipped_existing += 1
            continue

        digest = url_digest(url)
        if dbsession.execute(
            select(Link.id).where(Link.url_sha256 == digest)
        ).scalar_one_or_none() is not None:
            # The old UNIQUE(URL) made this impossible inside one file,
            # but two files merged into one database can collide.
            report.skipped_duplicate_url += 1
            continue

        dbsession.add(
            Link(code=code, url=url, url_sha256=digest, created_at=utcnow(), hits=0)
        )
        dbsession.flush()
        report.imported += 1
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import a 2016 urlshortener database.")
    parser.add_argument("config_uri", help="e.g. production.ini")
    parser.add_argument("legacy_db", help="path to the old var/urls.db")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read, report, write nothing",
    )
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)

    setup_logging(arguments.config_uri)
    env = bootstrap(arguments.config_uri)
    try:
        request = env["request"]
        settings = request.app_settings
        report = import_rows(
            request.dbsession,
            read_legacy_rows(arguments.legacy_db),
            settings.allowed_schemes,
        )
        if arguments.dry_run:
            request.tm.abort()
            print("DRY RUN — nothing written")
        else:
            request.tm.commit()
        print(report.as_text())
    finally:
        env["closer"]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
