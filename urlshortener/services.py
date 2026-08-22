# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Link creation and resolution, independent of HTTP.

Views call these; so do the import tool and the tests. Keeping the rules
out of the view layer is what makes it possible to test "shortening the
same URL twice returns the same code" without a request at all.
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .codec import generate_code, is_valid_code
from .models import Link, url_digest, utcnow
from .urlvalidation import normalise_url


class CodeExhausted(RuntimeError):
    """No free code found after `code_max_attempts` draws.

    In practice this means the table is saturated for the configured
    length, and `urlshortener.code_length` should be raised.
    """


def find_by_code(dbsession, code):
    """Return the `Link` for `code`, or None. No side effect."""
    if not is_valid_code(code):
        return None
    return dbsession.execute(
        select(Link).where(Link.code == code)
    ).scalar_one_or_none()


def find_by_url(dbsession, normalised_url: str):
    """Return the existing `Link` for an already-normalised URL, or None."""
    return dbsession.execute(
        select(Link).where(Link.url_sha256 == url_digest(normalised_url))
    ).scalar_one_or_none()


def create_link(dbsession, raw_url, settings):
    """Shorten `raw_url`. Returns `(link, created)`.

    `created` is False when the URL was already known: the 2016 service
    behaved this way (`SELECT NUM FROM WEB_URL WHERE URL=...` before
    inserting) and callers rely on it -- shortening the same page twice
    must not fill the table with synonyms.

    Raises `InvalidURL` if the target is refused, `CodeExhausted` if no
    free code can be drawn.
    """
    url = normalise_url(raw_url, settings)

    existing = find_by_url(dbsession, url)
    if existing is not None:
        return existing, False

    digest = url_digest(url)
    for _attempt in range(max(1, settings.code_max_attempts)):
        link = Link(
            code=generate_code(settings.code_length),
            url=url,
            url_sha256=digest,
            created_at=utcnow(),
            hits=0,
        )
        try:
            # SAVEPOINT, not a bare flush: a unique-constraint violation
            # inside the request transaction would otherwise poison it,
            # and pyramid_tm would refuse to commit anything afterwards.
            # begin_nested() rolls back to the savepoint and leaves the
            # outer transaction usable, so the retry below is real.
            with dbsession.begin_nested():
                dbsession.add(link)
                dbsession.flush()
        except IntegrityError:
            # Two ways to land here: the drawn code collided (retry with
            # a new draw), or a concurrent request inserted the same URL
            # first -- in which case the answer is its code, not ours.
            concurrent = find_by_url(dbsession, url)
            if concurrent is not None:
                return concurrent, False
            continue
        return link, True

    raise CodeExhausted(
        "no free code after %d attempts at length %d"
        % (settings.code_max_attempts, settings.code_length)
    )


def record_hit(dbsession, link, settings) -> None:
    """Count one redirect, if counting is enabled.

    Written as a single UPDATE rather than a read-modify-write so two
    simultaneous visitors cannot both read `hits=7` and both store 8.
    """
    if not settings.count_hits:
        return
    dbsession.execute(
        update(Link)
        .where(Link.id == link.id)
        .values(hits=Link.hits + 1, last_hit_at=utcnow())
    )


def count_links(dbsession) -> int:
    """Total number of stored links -- the figure the home page shows."""
    from sqlalchemy import func

    return int(dbsession.execute(select(func.count(Link.id))).scalar_one() or 0)
