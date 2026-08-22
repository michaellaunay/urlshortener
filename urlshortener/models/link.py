# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""The `links` table and the schema-version stamp.

The 2016 schema was:

    CREATE TABLE WEB_URL(
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        NUM TEXT NOT NULL UNIQUE,
        URL TEXT NOT NULL UNIQUE)

`NUM` becomes `code`, `URL` becomes `url`. The UNIQUE constraint on the
URL text is replaced by a unique index on its SHA-256: same effect (one
code per target, which is what made the old service return an existing
code instead of minting a new one), but the index stays 32 bytes wide
whatever the length of the URL.

Deliberately absent: the creator's IP address. A shortener does not need
to know who created a link in order to serve it, and storing that would
turn a link table into a log of who read and posted what. Rate limiting
works on an in-memory window instead (see `throttle.py`).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .meta import Base


def url_digest(url: str) -> str:
    """Stable fingerprint of a normalised URL, used for de-duplication."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    """Timezone-aware UTC now, so stored instants are unambiguous."""
    return datetime.now(timezone.utc)


class Link(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The public short code. Case-sensitive: 'aB' and 'Ab' differ.
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    #: Number of redirects served. Never decremented, never reset.
    hits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_hit_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    __table_args__ = (
        Index("uq_links_url_sha256", "url_sha256", unique=True),
        Index("ix_links_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return "<Link %s -> %s>" % (self.code, self.url[:60])


class SchemaVersion(Base):
    """One row, one integer: which upgrade steps have already run.

    Same contract as AlirPunkto's `upgrades.py`: any change to a
    persisted structure ADDS a step, and the step stamps itself.
    """

    __tablename__ = "schema_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
