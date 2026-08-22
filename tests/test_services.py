# -*- coding: utf-8 -*-
"""Creation and resolution rules, without HTTP."""
import pytest

from urlshortener.codec import is_valid_code
from urlshortener.constants_and_globals import AppSettings
from urlshortener.services import (
    CodeExhausted,
    count_links,
    create_link,
    find_by_code,
    find_by_url,
    record_hit,
)
from urlshortener.urlvalidation import InvalidURL

OPEN = AppSettings(base_url="http://s.test/", block_private_targets=False)


def test_creating_a_link_returns_a_usable_code(dbsession):
    link, created = create_link(dbsession, "https://example.org/page", OPEN)
    assert created is True
    assert is_valid_code(link.code)
    assert link.url == "https://example.org/page"
    assert link.hits == 0


def test_the_same_url_always_gives_the_same_code(dbsession):
    # The 2016 service did a SELECT before INSERT; callers depend on it.
    first, created_first = create_link(dbsession, "https://example.org/x", OPEN)
    second, created_second = create_link(dbsession, "https://example.org/x", OPEN)
    assert created_first is True
    assert created_second is False
    assert first.code == second.code
    assert count_links(dbsession) == 1


def test_normalisation_happens_before_the_lookup(dbsession):
    # 'example.org/x' and 'http://example.org/x' are the same target.
    first, _ = create_link(dbsession, "example.org/x", OPEN)
    second, created = create_link(dbsession, "http://example.org/x", OPEN)
    assert created is False
    assert first.code == second.code


def test_different_urls_get_different_codes(dbsession):
    first, _ = create_link(dbsession, "https://example.org/a", OPEN)
    second, _ = create_link(dbsession, "https://example.org/b", OPEN)
    assert first.code != second.code
    assert count_links(dbsession) == 2


def test_an_invalid_url_never_reaches_the_database(dbsession):
    with pytest.raises(InvalidURL):
        create_link(dbsession, "javascript:alert(1)", OPEN)
    assert count_links(dbsession) == 0


def test_find_by_code_is_case_sensitive(dbsession):
    link, _ = create_link(dbsession, "https://example.org/", OPEN)
    assert find_by_code(dbsession, link.code) is not None
    assert find_by_code(dbsession, link.code.swapcase()) is None or link.code.isdigit()


def test_find_by_code_rejects_junk_without_querying(dbsession):
    assert find_by_code(dbsession, "no/such/thing") is None
    assert find_by_code(dbsession, "") is None


def test_find_by_url_needs_an_already_normalised_url(dbsession):
    create_link(dbsession, "https://example.org/z", OPEN)
    assert find_by_url(dbsession, "https://example.org/z") is not None
    assert find_by_url(dbsession, "https://example.org/other") is None


def test_collisions_are_retried(dbsession, monkeypatch):
    # Force the generator to hand out one code twice, then a new one:
    # the second creation must survive it instead of raising.
    from urlshortener import services

    draws = iter(["AAAAAAA", "AAAAAAA", "BBBBBBB"])
    monkeypatch.setattr(services, "generate_code", lambda length: next(draws))

    first, _ = create_link(dbsession, "https://example.org/1", OPEN)
    second, created = create_link(dbsession, "https://example.org/2", OPEN)
    assert first.code == "AAAAAAA"
    assert second.code == "BBBBBBB"
    assert created is True


def test_exhausted_code_space_raises_rather_than_looping(dbsession, monkeypatch):
    from urlshortener import services

    monkeypatch.setattr(services, "generate_code", lambda length: "COLLIDE")
    create_link(dbsession, "https://example.org/1", OPEN)
    with pytest.raises(CodeExhausted):
        create_link(dbsession, "https://example.org/2", OPEN)


def test_record_hit_increments(dbsession):
    link, _ = create_link(dbsession, "https://example.org/", OPEN)
    record_hit(dbsession, link, OPEN)
    record_hit(dbsession, link, OPEN)
    dbsession.expire(link)
    assert link.hits == 2
    assert link.last_hit_at is not None


def test_record_hit_does_nothing_when_counting_is_off(dbsession):
    settings = AppSettings(count_hits=False, block_private_targets=False)
    link, _ = create_link(dbsession, "https://example.org/", settings)
    record_hit(dbsession, link, settings)
    dbsession.expire(link)
    assert link.hits == 0
