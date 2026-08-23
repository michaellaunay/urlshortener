# -*- coding: utf-8 -*-
"""Classification of legacy rows against today's rules (train 0006).

External audit 2026-08-22, finding C-10: the import applied a fraction
of the 2.x policy, so a migration could quietly reintroduce what the
running service refuses — and, worse, could mint a link nobody can
reach.

The migration contract is unchanged and is what the first test here
pins: URLs are stored VERBATIM. What this train adds is knowing which
rows today's rules would refuse, and saying so.
"""
import os
import sqlite3

import pytest

from urlshortener.constants_and_globals import AppSettings
from urlshortener.models import Link
from urlshortener.services import find_by_code
from urlshortener.urlvalidation import to_wire_url
from urlshortener.tools.import_legacy import (
    ALWAYS_REFUSED,
    NEVER_IMPORTED_SCHEMES,
    ImportReport,
    classify,
    import_rows,
    read_legacy_rows,
)

LEGACY_SCHEMA = """
CREATE TABLE WEB_URL(
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    NUM TEXT NOT NULL UNIQUE,
    URL TEXT NOT NULL UNIQUE)
"""

STRICT = AppSettings(block_private_targets=True, blocked_hosts=("evil.test",))
LENIENT = AppSettings(block_private_targets=False)


def _legacy_file(tmp_path, rows, name="urls.db"):
    path = tmp_path / name
    connection = sqlite3.connect(str(path))
    connection.execute(LEGACY_SCHEMA)
    connection.executemany("INSERT INTO WEB_URL (NUM, URL) VALUES (?, ?)", rows)
    connection.commit()
    connection.close()
    return str(path)


# -- C-10 -- a reserved code imports into a link nobody can follow --------

def test_c10_a_legacy_code_that_a_route_shadows_is_refused():
    """`healthz` is seven characters of the alphabet, so `is_valid_code`
    called it legal and it imported cleanly — into a row the redirect
    view can never be asked about, because `/healthz` is a route."""
    reason, always = classify("healthz", "https://example.org/", LENIENT)
    assert reason == "reserved_code"
    assert always is True


@pytest.mark.parametrize("code", sorted({"api", "healthz", "static", "locale"}))
def test_c10_every_reserved_code_is_refused_on_import(code):
    reason, _always = classify(code, "https://example.org/", LENIENT)
    assert reason == "reserved_code"


def test_c10_no_flag_can_import_a_reserved_code():
    """Renaming it would kill the link; importing it would hide it.
    Only the operator can weigh those, so the tool reports and stops."""
    reason, always = classify("healthz", "https://example.org/", LENIENT, allow_unsafe=True)
    assert reason == "reserved_code" and always is True
    assert "reserved_code" in ALWAYS_REFUSED


def test_c10_the_reserved_row_does_not_reach_the_database(tmp_path, dbsession):
    path = _legacy_file(tmp_path, [
        ("healthz", "https://example.org/shadowed"),
        ("ok1", "https://example.org/fine"),
    ])
    report = import_rows(dbsession, read_legacy_rows(path), LENIENT)
    assert report.imported == 1
    assert dbsession.query(Link).count() == 1
    assert find_by_code(dbsession, "ok1") is not None


# -- the two kinds of refusal ---------------------------------------------

@pytest.mark.parametrize("scheme", sorted(NEVER_IMPORTED_SCHEMES))
def test_a_dangerous_scheme_is_never_imported(scheme):
    """A flag that can import an XSS vector is not a flag, it is a trap
    laid for a future operator in a hurry."""
    url = "%s:alert(1)" % scheme
    for unsafe in (False, True):
        reason, always = classify("aa1", url, LENIENT, allow_unsafe=unsafe)
        assert reason == "scheme:%s" % scheme
        assert always is True


@pytest.mark.parametrize("code,url,expected", [
    ("bad/code", "https://example.org/", "bad_code"),
    ("aa1", "", "empty_url"),
    ("aa1", "https://example.org/\r\nX: y", "control_chars"),
])
def test_unfixable_rows_are_refused_whatever_the_flag(code, url, expected):
    for unsafe in (False, True):
        reason, always = classify(code, url, LENIENT, allow_unsafe=unsafe)
        assert (reason, always) == (expected, True)


@pytest.mark.parametrize("url", [
    "ftp://example.org/file",
    "http://127.0.0.1/admin",
    "http://2130706433/admin",          # the same host, other spelling
    "https://evil.test/x",
    "https://deep.evil.test/x",
    "https://example.org/?q=" + "a" * 4000,
])
def test_a_row_today_s_rules_would_refuse_is_classified_as_policy(url):
    reason, always = classify("aa1", url, STRICT)
    assert reason is not None
    assert always is False, "%s is a working link, only the policy refuses it" % url


@pytest.mark.parametrize("url", [
    "ftp://example.org/file",
    "http://127.0.0.1/admin",
    "https://evil.test/x",
    "https://example.org/?q=" + "a" * 4000,
])
def test_the_flag_lifts_exactly_the_policy_refusals(url):
    reason, _always = classify("aa1", url, STRICT, allow_unsafe=True)
    assert reason is None


def test_a_conforming_row_is_never_refused():
    assert classify("aa1", "https://example.org/page", STRICT) == (None, False)


# -- the contract that must not move --------------------------------------

def test_urls_are_still_stored_verbatim(tmp_path, dbsession):
    """The whole point of the migration: a corrected URL is a different
    destination from the one the link has promised for ten years.
    `normalise_url` is used as a judge, never as a transformer."""
    original = "http://EXAMPLE.org/Path%20With%20Escapes?a=1#frag"
    path = _legacy_file(tmp_path, [("aa1", original)])
    import_rows(dbsession, read_legacy_rows(path), LENIENT)
    assert find_by_code(dbsession, "aa1").url == original


def test_codes_are_still_imported_verbatim(tmp_path, dbsession):
    path = _legacy_file(tmp_path, [("0", "https://example.org/a"), ("4f2", "https://example.org/b")])
    import_rows(dbsession, read_legacy_rows(path), LENIENT)
    assert {link.code for link in dbsession.query(Link).all()} == {"0", "4f2"}


# -- the report ------------------------------------------------------------

def test_the_report_separates_the_two_kinds(tmp_path, dbsession):
    path = _legacy_file(tmp_path, [
        ("aa1", "https://example.org/fine"),
        ("healthz", "https://example.org/shadowed"),
        ("bb2", "javascript:alert(1)"),
        ("cc3", "ftp://example.org/file"),
        ("dd4", "http://127.0.0.1/admin"),
    ])
    report = import_rows(dbsession, read_legacy_rows(path), STRICT)
    assert report.imported == 1
    assert {code for code, _u, _r in report.refused_always} == {"healthz", "bb2"}
    assert {code for code, _u, _r in report.refused_by_policy} == {"cc3", "dd4"}


def test_the_report_tells_the_operator_what_to_do(tmp_path, dbsession):
    path = _legacy_file(tmp_path, [("cc3", "ftp://example.org/file")])
    text = import_rows(dbsession, read_legacy_rows(path), STRICT).as_text()
    assert "--allow-unsafe-legacy" in text
    assert "refused (policy)       : 1" in text


def test_the_report_does_not_suggest_a_flag_that_would_not_help(tmp_path, dbsession):
    path = _legacy_file(tmp_path, [("healthz", "https://example.org/x")])
    text = import_rows(dbsession, read_legacy_rows(path), STRICT).as_text()
    assert "--allow-unsafe-legacy" not in text
    assert "route moves" in text


def test_the_rejected_property_still_counts_everything():
    report = ImportReport()
    report.reject("a", "u", "bad_code", True)
    report.reject("b", "u", "error_url_scheme", False)
    assert len(report.rejected) == 2


# -- the flag, end to end --------------------------------------------------

def test_the_flag_imports_the_policy_rows_and_only_those(tmp_path, dbsession):
    path = _legacy_file(tmp_path, [
        ("aa1", "https://example.org/fine"),
        ("cc3", "ftp://example.org/file"),
        ("dd4", "http://127.0.0.1/admin"),
        ("bb2", "javascript:alert(1)"),
        ("healthz", "https://example.org/shadowed"),
    ])
    report = import_rows(dbsession, read_legacy_rows(path), STRICT, allow_unsafe=True)
    assert report.imported == 3
    assert find_by_code(dbsession, "cc3").url == "ftp://example.org/file"
    assert find_by_code(dbsession, "dd4").url == "http://127.0.0.1/admin"
    assert find_by_code(dbsession, "bb2") is None
    assert dbsession.query(Link).filter(Link.code == "healthz").count() == 0


def test_the_flag_is_offered_by_the_command_line():
    import argparse
    import inspect

    from urlshortener.tools import import_legacy

    source = inspect.getsource(import_legacy.main)
    assert "--allow-unsafe-legacy" in source
    assert "--dry-run" in source
    assert isinstance(argparse.ArgumentParser(), argparse.ArgumentParser)


def test_the_unsafe_run_says_so_out_loud():
    import inspect

    from urlshortener.tools import import_legacy

    assert "NOT applied" in inspect.getsource(import_legacy.main)


# -- N-03 -- the flag lifts policy, never arithmetic (train 0021) ---------
#
# External audit (Claude, 2026-08-23), finding N-03, sharpening point 5
# of the third ChatGPT pass. `allow_unsafe` used to short-circuit
# `normalise_url` entirely, so three refusals that are NOT policy were
# liftable. The rule dividing the two kinds is the module's own: the
# operator can overrule policy; they cannot overrule arithmetic.

@pytest.mark.parametrize("url,expected", [
    ("http://example.org:99999/", "bad_port"),
    ("http://example.org:abc/", "bad_port"),
    ("http://\u2603.example/x", "bad_host"),        # IDNA-disallowed
    ("http://999999999999/", "bad_host"),           # numeric, not an address
    ("http://[not-an-ipv6]/x", "bad_host"),
    ("http://bank.example@evil.test/", "credentials"),
    ("ftp://user:secret@mirror.example/pub", "credentials"),
])
def test_n03_arithmetic_refusals_survive_the_flag(url, expected):
    for unsafe in (False, True):
        reason, always = classify("aa1", url, LENIENT, allow_unsafe=unsafe)
        assert (reason, always) == (expected, True), url


def test_n03_an_at_sign_outside_the_authority_is_not_credentials():
    """`mailto:someone@example.org` has no netloc: the '@' lives in the
    path, and the row remains what it was — a policy refusal the flag
    can take back."""
    reason, always = classify(
        "aa1", "mailto:someone@example.org", LENIENT, allow_unsafe=True
    )
    assert (reason, always) == (None, False)


def test_n03_why_a_bad_port_is_arithmetic():
    """The mechanism, pinned: `to_wire_url` swallows the ValueError a
    bad port raises (the C-16 branch kept for rows already in the
    database) and rebuilds the netloc WITHOUT the port. A visitor is
    sent to a DIFFERENT destination from the stored one — the verbatim
    contract is exactly what such a row cannot keep."""
    assert to_wire_url("http://example.org:99999/x") == "http://example.org/x"


def test_n03_why_an_irrecoverable_host_is_arithmetic():
    """The other mechanism, pinned: a host IDNA cannot encode passes
    through `to_wire_url` unchanged, so the Location header carries
    non-ASCII — the S-01 500-on-every-visit, fixed everywhere else,
    would come back through the import flag."""
    assert not to_wire_url("http://\u2603.example/x").isascii()


def test_n03_the_flag_run_still_refuses_the_arithmetic_rows(tmp_path, dbsession):
    path = _legacy_file(tmp_path, [
        ("pp1", "http://example.org:99999/"),
        ("hh1", "http://\u2603.example/x"),
        ("uu1", "http://bank.example@evil.test/"),
        ("ok2", "http://127.0.0.1/admin"),
    ])
    report = import_rows(dbsession, read_legacy_rows(path), STRICT, allow_unsafe=True)
    assert report.imported == 1
    assert {code for code, _u, _r in report.refused_always} == {"pp1", "hh1", "uu1"}
    assert find_by_code(dbsession, "ok2") is not None


@pytest.mark.parametrize("chapter", ["fr/05_migration.md", "en/05_migration.md"])
def test_n03_every_unliftable_reason_is_documented(chapter):
    """`ALWAYS_REFUSED` stops being decorative: every reason the
    classifier can hand back without appeal must appear in the table
    the operator reads to decide what to do with the row."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "docs", *chapter.split("/")), encoding="utf-8") as handle:
        body = handle.read()
    missing = [reason for reason in ALWAYS_REFUSED if "`%s`" % reason not in body]
    assert not missing, "unliftable but undocumented in %s: %s" % (chapter, missing)
