# -*- coding: utf-8 -*-
"""Import of the 2016 SQLite file.

The rule under test everywhere here: a code that has been published
must keep resolving to the same target, unchanged.
"""
import sqlite3

import pytest

from urlshortener.models import Link
from urlshortener.tools.import_legacy import import_rows, read_legacy_rows

LEGACY_SCHEMA = """
CREATE TABLE WEB_URL(
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    NUM TEXT NOT NULL UNIQUE,
    URL TEXT NOT NULL UNIQUE)
"""

ALLOWED = ("http", "https")


@pytest.fixture
def legacy_db(tmp_path):
    """A file with the exact 2016 schema and a few realistic rows."""
    path = tmp_path / "urls.db"
    connection = sqlite3.connect(str(path))
    connection.execute(LEGACY_SCHEMA)
    connection.executemany(
        "INSERT INTO WEB_URL (NUM, URL) VALUES (?, ?)",
        [
            ("0", "http://example.org/first"),
            ("1", "http://example.org/second"),
            ("4f2", "https://example.org/deep/page?a=b"),
            ("Z", "http://example.org/last-single-char"),
        ],
    )
    connection.commit()
    connection.close()
    return str(path)


def test_rows_are_read_from_the_legacy_file(legacy_db):
    rows = list(read_legacy_rows(legacy_db))
    assert len(rows) == 4
    assert rows[0][1] == "0"


def test_the_legacy_file_is_opened_read_only(legacy_db, dbsession):
    import_rows(dbsession, read_legacy_rows(legacy_db), ALLOWED)
    connection = sqlite3.connect("file:%s?mode=ro" % legacy_db, uri=True)
    try:
        assert connection.execute("SELECT count(*) FROM WEB_URL").fetchone()[0] == 4
    finally:
        connection.close()


def test_codes_are_imported_verbatim(legacy_db, dbsession):
    report = import_rows(dbsession, read_legacy_rows(legacy_db), ALLOWED)
    assert report.imported == 4
    codes = {link.code: link.url for link in dbsession.query(Link).all()}
    assert codes["0"] == "http://example.org/first"
    assert codes["4f2"] == "https://example.org/deep/page?a=b"
    assert codes["Z"] == "http://example.org/last-single-char"


def test_a_short_link_still_resolves_after_import(legacy_db, dbsession):
    from urlshortener.services import find_by_code

    import_rows(dbsession, read_legacy_rows(legacy_db), ALLOWED)
    assert find_by_code(dbsession, "4f2").url == "https://example.org/deep/page?a=b"


def test_the_import_is_idempotent(legacy_db, dbsession):
    import_rows(dbsession, read_legacy_rows(legacy_db), ALLOWED)
    second = import_rows(dbsession, read_legacy_rows(legacy_db), ALLOWED)
    assert second.imported == 0
    assert second.skipped_existing == 4
    assert dbsession.query(Link).count() == 4


def test_unservable_rows_are_reported_not_silently_fixed(tmp_path, dbsession):
    path = tmp_path / "dirty.db"
    connection = sqlite3.connect(str(path))
    connection.execute(LEGACY_SCHEMA)
    connection.executemany(
        "INSERT INTO WEB_URL (NUM, URL) VALUES (?, ?)",
        [
            ("aa1", "https://example.org/fine"),
            ("bb2", "javascript:alert(1)"),
            ("cc3", "ftp://example.org/file"),
            ("dd/4", "https://example.org/bad-code"),
        ],
    )
    connection.commit()
    connection.close()

    report = import_rows(dbsession, read_legacy_rows(str(path)), ALLOWED)
    assert report.imported == 1
    reasons = {code: reason for code, _url, reason in report.rejected}
    assert reasons["bb2"] == "scheme:javascript"
    assert reasons["cc3"] == "scheme:ftp"
    assert reasons["dd/4"] == "bad_code"
    # Nothing was rewritten to make it pass.
    assert dbsession.query(Link).count() == 1


def test_the_report_reads_as_an_operator_would_expect(legacy_db, dbsession):
    report = import_rows(dbsession, read_legacy_rows(legacy_db), ALLOWED)
    text = report.as_text()
    assert "rows read" in text and "imported" in text and "rejected" in text
