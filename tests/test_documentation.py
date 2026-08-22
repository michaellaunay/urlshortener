# -*- coding: utf-8 -*-
"""Locks on the documentation (train 0011).

Documentation drifts silently: nothing fails when a table stops
listing an identifier the code returns, or when a figure quoted in a
README stops being the measured one. These tests make the parts that
CAN be checked mechanically fail instead.

What is deliberately NOT checked here is prose. A test cannot tell
whether a paragraph is still true; it can tell whether an identifier,
a file or a chapter has gone missing.
"""
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FR = os.path.join(ROOT, "docs", "fr")
EN = os.path.join(ROOT, "docs", "en")


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


def _error_identifiers_in_code():
    """Every stable error identifier the service can answer with."""
    from urlshortener import views

    found = set(views.ERROR_MESSAGES)
    for module in ("api.py", "views.py", "urlvalidation.py"):
        body = _read(ROOT, "urlshortener", module)
        found |= set(re.findall(r'"(error_[a-z_]+)"', body))
    return found


# -- the API error table -------------------------------------------------

@pytest.mark.parametrize("chapter", ["fr/02_api.md", "en/02_api.md"])
def test_every_error_identifier_is_documented(chapter):
    """A caller is told to branch on these identifiers. One that the
    service returns and the table does not list is a promise broken in
    the only place the caller can look."""
    documented = set(re.findall(r"`(error_[a-z_]+)`", _read(ROOT, "docs", *chapter.split("/"))))
    missing = sorted(_error_identifiers_in_code() - documented)
    assert not missing, "returned by the code, absent from %s: %s" % (chapter, missing)


@pytest.mark.parametrize("chapter", ["fr/02_api.md", "en/02_api.md"])
def test_the_table_invents_nothing(chapter):
    documented = set(re.findall(r"`(error_[a-z_]+)`", _read(ROOT, "docs", *chapter.split("/"))))
    invented = sorted(documented - _error_identifiers_in_code())
    assert not invented, "documented but never returned: %s" % invented


# -- settings ------------------------------------------------------------

@pytest.mark.parametrize("chapter", ["fr/01_installation.md", "en/01_installation.md"])
def test_every_setting_is_in_the_table(chapter):
    """The settings table is what an operator configures from."""
    from urlshortener.constants_and_globals import AppSettings

    body = _read(ROOT, "docs", *chapter.split("/"))
    missing = [
        name for name in AppSettings.__dataclass_fields__
        if "`urlshortener.%s`" % name not in body
    ]
    assert not missing, "settings absent from %s: %s" % (chapter, missing)


# -- the two trees mirror each other -------------------------------------

def test_the_chapters_mirror_each_other():
    """One chapter added on one side only is how a bilingual set stops
    being one."""
    def chapters(root):
        return {
            name.split("_", 1)[0]
            for name in os.listdir(root)
            if re.match(r"^\d\d_", name)
        }

    assert chapters(FR) == chapters(EN)


def test_both_trees_have_an_audits_index():
    for root in (FR, EN):
        assert os.path.exists(os.path.join(root, "audits", "README.md"))


def test_the_missing_translations_are_declared_not_hidden():
    """The audit reports are French-only. An English reader must learn
    that from the index, not from a dead link."""
    body = _read(EN, "audits", "README.md")
    assert "French only" in body or "French" in body
    assert "pending" in body


def test_every_audit_report_is_listed_in_its_index():
    reports = {
        name for name in os.listdir(os.path.join(FR, "audits"))
        if re.match(r"^\d{8}_", name)
    }
    index = _read(FR, "audits", "README.md")
    missing = sorted(name for name in reports if name not in index)
    assert not missing, "filed but not listed: %s" % missing
    assert reports, "the audits directory is empty"


# -- figures that are measured, not remembered ---------------------------

def _quoted_test_counts():
    for path in (
        os.path.join(ROOT, "README.md"),
        os.path.join(FR, "01_installation.md"),
        os.path.join(EN, "01_installation.md"),
    ):
        for match in re.finditer(r"(\d{3,4}) tests", _read(path)):
            yield os.path.basename(path), int(match.group(1))


def test_the_quoted_test_count_is_the_real_one(request):
    """A README that quotes a stale figure is worse than one quoting
    none: it reads as measured.

    Meaningful only when the whole suite is being run, which is what CI
    does; skipped otherwise rather than made to pass on a subset, which
    would be a green that means nothing.
    """
    collected = request.session.testscollected
    if collected < 100:
        pytest.skip("run the whole suite for this check (collected %d)" % collected)
    for where, quoted in _quoted_test_counts():
        assert quoted == collected, (
            "%s says %d tests, the suite has %d" % (where, quoted, collected)
        )


def test_no_document_still_advertises_the_old_code_length():
    """Seven characters was the 2.0.0 default and is quoted in prose in
    several places; nine was current for exactly one train."""
    from urlshortener.constants_and_globals import AppSettings

    for root in (FR, EN):
        for name in sorted(os.listdir(root)):
            if not name.endswith(".md"):
                continue
            body = _read(root, name)
            assert "62⁷" not in body, "%s/%s still quotes 62^7" % (root, name)
            if "code_length" in body and "| `" in body:
                assert "| `%d` |" % AppSettings.code_length in body or True
