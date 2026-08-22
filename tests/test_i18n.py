# -*- coding: utf-8 -*-
"""The locale registry, the catalogues on disk, and negotiation.

These are ratchets: they exist so that "we added a language" and "the
language actually works" cannot drift apart, which is the failure mode
every multilingual project eventually hits.
"""
import os
import struct

import pytest

from urlshortener import views
from urlshortener.constants_and_globals import (
    AVAILABLE_LANGUAGES,
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
)
from urlshortener.locale_negotiation import negotiate, parse_accept_language

HERE = os.path.dirname(os.path.abspath(__file__))
LOCALE_DIR = os.path.join(os.path.dirname(HERE), "urlshortener", "locale")


def _po_msgids(path):
    msgids = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith('msgid "') and line.strip() != 'msgid ""':
                msgids.add(line[len('msgid "'):].rstrip()[:-1])
    return msgids


def _mo_msgids(path):
    """Parse a compiled catalogue without gettext, so the test proves the
    .mo was really recompiled and is not a stale copy of an older .po."""
    with open(path, "rb") as handle:
        data = handle.read()
    magic = struct.unpack("<I", data[:4])[0]
    endian = "<" if magic == 0x950412DE else ">"
    count, original_offset = struct.unpack(endian + "II", data[8:16])
    msgids = set()
    for index in range(count):
        length, offset = struct.unpack(
            endian + "II", data[original_offset + index * 8: original_offset + index * 8 + 8]
        )
        msgid = data[offset:offset + length].decode("utf-8")
        if msgid:
            msgids.add(msgid.split("\x00", 1)[0])
    return msgids


def test_the_four_languages_of_this_iteration_are_offered():
    assert AVAILABLE_LANGUAGES == ["en", "fr", "de", "es"]
    assert DEFAULT_LOCALE in AVAILABLE_LANGUAGES


def test_every_registry_entry_is_well_formed():
    for code, spec in SUPPORTED_LOCALES.items():
        assert 2 <= len(code) <= 3, code
        assert spec["name"].strip(), code
        assert isinstance(spec["selectable"], bool), code
        assert spec["tier"] in (1, 2, 3), code


def test_registry_and_disk_agree():
    """A selectable language MUST have a catalogue, and a catalogue on
    disk MUST be declared. This is the bijection that stops a language
    from being offered as an empty page."""
    on_disk = {
        entry for entry in os.listdir(LOCALE_DIR)
        if os.path.isdir(os.path.join(LOCALE_DIR, entry))
    }
    assert on_disk == set(AVAILABLE_LANGUAGES), (
        "catalogues on disk and selectable languages differ: %s" % (on_disk ^ set(AVAILABLE_LANGUAGES))
    )


@pytest.mark.parametrize("language", ["en", "fr", "de", "es"])
def test_no_message_is_missing_from_a_catalogue(language):
    template = _po_msgids(os.path.join(LOCALE_DIR, "urlshortener.pot"))
    catalogue = os.path.join(LOCALE_DIR, language, "LC_MESSAGES", "urlshortener.po")
    assert template <= _po_msgids(catalogue), (
        "missing from %s: %s" % (language, sorted(template - _po_msgids(catalogue)))
    )


@pytest.mark.parametrize("language", ["en", "fr", "de", "es"])
def test_the_compiled_catalogue_is_up_to_date(language):
    directory = os.path.join(LOCALE_DIR, language, "LC_MESSAGES")
    source = _po_msgids(os.path.join(directory, "urlshortener.po"))
    compiled = _mo_msgids(os.path.join(directory, "urlshortener.mo"))
    assert source <= compiled, (
        "%s.mo is stale, recompile it: %s" % (language, sorted(source - compiled))
    )


@pytest.mark.parametrize("language", ["fr", "de", "es"])
def test_translations_are_not_copies_of_the_english(language):
    """A catalogue full of English fallbacks would pass every other
    test here while shipping an untranslated page."""
    english = os.path.join(LOCALE_DIR, "en", "LC_MESSAGES", "urlshortener.po")
    other = os.path.join(LOCALE_DIR, language, "LC_MESSAGES", "urlshortener.po")
    with open(english, encoding="utf-8") as handle:
        english_text = handle.read()
    with open(other, encoding="utf-8") as handle:
        other_text = handle.read()
    assert english_text != other_text


def test_every_refusal_reason_has_a_message():
    """Adding a reason to urlvalidation without a message here would
    show the visitor a blank error box."""
    import inspect

    from urlshortener import urlvalidation

    raised = set()
    source = inspect.getsource(urlvalidation)
    for line in source.splitlines():
        if 'InvalidURL("' in line:
            raised.add(line.split('InvalidURL("', 1)[1].split('"', 1)[0])
    assert raised, "no refusal reason found — did the module move?"
    assert raised <= set(views.ERROR_MESSAGES), sorted(raised - set(views.ERROR_MESSAGES))


def test_every_message_is_in_the_catalogue_template():
    template = _po_msgids(os.path.join(LOCALE_DIR, "urlshortener.pot"))
    assert set(views.ERROR_MESSAGES) <= template


class _Request:
    def __init__(self, params=None, cookies=None, headers=None):
        self.params = params or {}
        self.cookies = cookies or {}
        self.headers = headers or {}


def test_query_string_wins_over_everything():
    request = _Request(
        params={"_LOCALE_": "de"},
        cookies={"_LOCALE_": "fr"},
        headers={"Accept-Language": "es"},
    )
    assert negotiate(request) == "de"


def test_cookie_wins_over_the_browser():
    request = _Request(cookies={"_LOCALE_": "fr"}, headers={"Accept-Language": "es"})
    assert negotiate(request) == "fr"


def test_accept_language_is_honoured_with_quality_values():
    request = _Request(headers={"Accept-Language": "es;q=0.4, de;q=0.9"})
    assert negotiate(request) == "de"


def test_a_regional_tag_reaches_its_base_language():
    assert negotiate(_Request(headers={"Accept-Language": "fr-BE"})) == "fr"


def test_an_unoffered_language_falls_back():
    # 'it' is declared in the registry but not selectable yet.
    assert negotiate(_Request(headers={"Accept-Language": "it"})) == DEFAULT_LOCALE
    assert negotiate(_Request(cookies={"_LOCALE_": "it"})) == DEFAULT_LOCALE
    assert negotiate(_Request()) == DEFAULT_LOCALE


def test_a_malformed_quality_value_does_not_break_negotiation():
    assert negotiate(_Request(headers={"Accept-Language": "fr;q=oops"})) == "fr"


def test_parse_accept_language_keeps_header_order_among_equals():
    assert parse_accept_language("de, fr, es") == ["de", "fr", "es"]
