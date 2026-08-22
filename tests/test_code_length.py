# -*- coding: utf-8 -*-
"""The length of a freshly minted code (train 0007).

External audit 2026-08-22, finding C-14: seven characters is roughly
41.7 bits. Fine while a short code is public by nature; thin the moment
someone treats it as a secret, which is what everyone who pastes one
does whatever the service promises.

The tests here are about ONE property and its two boundaries: new codes
are longer, and nothing that already exists breaks.
"""
import math
import os
import re

import pytest

from urlshortener import codec
from urlshortener.constants_and_globals import AppSettings
from urlshortener.services import create_link, find_by_code

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

OPEN = AppSettings(block_private_targets=False)


def _read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        return handle.read()


# -- the floor -------------------------------------------------------------

def test_the_default_length_is_at_least_nine():
    """A ratchet, not an equality: raising it later must not fail here,
    lowering it must."""
    assert AppSettings.code_length >= 9


def test_the_entropy_is_worth_stating():
    bits = AppSettings.code_length * math.log2(len(codec.ALPHABET))
    assert bits >= 53, "%0.1f bits is below the floor this train set" % bits


def test_a_blind_probe_is_hopeless_at_a_realistic_corpus_size():
    """The number that matters is the hit rate of a random guess,
    `stored / 62**length`. At length 7 with a million links that was one
    hit per 3.5 million probes — a patient scraper's afternoon."""
    stored = 1_000_000
    probes_per_hit = len(codec.ALPHABET) ** AppSettings.code_length / stored
    assert probes_per_hit > 1e9


@pytest.mark.parametrize("path", ["production.ini", "development.ini"])
def test_the_shipped_configuration_matches_the_default(path):
    value = int(re.search(
        r"^urlshortener\.code_length\s*=\s*(\d+)", _read(path), re.MULTILINE
    ).group(1))
    assert value == AppSettings.code_length


def test_the_container_default_matches_too():
    match = re.search(
        r"URLSHORTENER_CODE_LENGTH: \$\{URLSHORTENER_CODE_LENGTH:-(\d+)\}",
        _read("docker/docker-compose.yaml"),
    )
    assert match and int(match.group(1)) == AppSettings.code_length


# -- new codes -------------------------------------------------------------

def test_a_minted_code_has_the_configured_length(dbsession):
    link, created = create_link(dbsession, "https://example.org/new", OPEN)
    assert created is True
    assert len(link.code) == OPEN.code_length


def test_the_length_is_still_configurable_downwards(dbsession):
    """An operator running a private instance may want short codes; the
    setting is theirs, the default is ours."""
    settings = AppSettings(code_length=4, block_private_targets=False)
    link, _created = create_link(dbsession, "https://example.org/short", settings)
    assert len(link.code) == 4


def test_the_new_length_is_within_the_codec_bounds():
    assert codec.MIN_CODE_LENGTH <= AppSettings.code_length <= codec.MAX_CODE_LENGTH


# -- nothing that exists breaks -------------------------------------------

@pytest.mark.parametrize("code", ["0", "9", "aZ", "4f2", "abcdefg"])
def test_an_existing_shorter_code_is_still_legal(code):
    """Length governs MINTING. Resolution accepts any legal code, and
    the 2016 corpus starts at one character."""
    assert codec.is_valid_code(code)


def test_a_short_legacy_row_still_resolves(testapp):
    from sqlalchemy import text

    engine = testapp.app.registry["dbengine"]
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO links (code, url, url_sha256, created_at, hits) "
                 "VALUES ('4f2', :u, :s, '2016-01-01 00:00:00', 0)"),
            {"u": "https://example.org/legacy", "s": "2" * 64},
        )
    response = testapp.get("/4f2", status=302)
    assert response.headers["Location"] == "https://example.org/legacy"


def test_short_and_long_codes_coexist(dbsession):
    from urlshortener.models import Link, url_digest, utcnow

    dbsession.add(Link(code="0", url="https://example.org/old",
                       url_sha256=url_digest("https://example.org/old"),
                       created_at=utcnow(), hits=0))
    dbsession.flush()
    fresh, _created = create_link(dbsession, "https://example.org/fresh", OPEN)
    assert len(fresh.code) == OPEN.code_length
    assert find_by_code(dbsession, "0") is not None
    assert find_by_code(dbsession, fresh.code) is not None


def test_the_de_duplication_is_unaffected(dbsession):
    first, created_first = create_link(dbsession, "https://example.org/same", OPEN)
    second, created_second = create_link(dbsession, "https://example.org/same", OPEN)
    assert created_first is True and created_second is False
    assert first.code == second.code


def test_the_retry_budget_still_covers_the_space(dbsession):
    """Collisions are absorbed by retry, so the budget only has to be
    sane; at this length the per-insert collision rate is negligible."""
    assert OPEN.code_max_attempts >= 4
