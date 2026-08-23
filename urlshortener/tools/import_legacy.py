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

from ..codec import RESERVED_CODES, is_valid_code
from ..models import Link, url_digest, utcnow
from ..urlvalidation import InvalidURL, canonical_host, normalise_url

LEGACY_QUERY = "SELECT ID, NUM, URL FROM WEB_URL ORDER BY ID"

#: Schemes never imported, whatever the operator asks for.
#:
#: These are the ones that turn a redirect into an attack: the service
#: would be putting `javascript:` into a `Location:` header under its
#: own domain. `--allow-unsafe-legacy` deliberately does NOT reach
#: them -- a flag that can import an XSS vector is not a flag, it is a
#: trap laid for a future operator in a hurry.
#:
#: `file` joined the set in train 0021 (audit N-03): a
#: `Location: file://...` under this service's domain is indefensible
#: -- no current browser follows it, and on an intranet it is a prompt
#: at a path an attacker chose. A functional 2016 scheme (`ftp:`)
#: remains a POLICY refusal; a file path was never a link this service
#: should hand out.
NEVER_IMPORTED_SCHEMES = frozenset({"javascript", "data", "vbscript", "file"})

#: Refusals `--allow-unsafe-legacy` cannot lift, and why.
#:
#: The rule dividing these from the rest: a row is refused ALWAYS when
#: importing it would produce something that cannot work or must not
#: work -- an unreachable code, an attack vector. It is refused BY
#: POLICY when the link works perfectly well and it is only the 2.x
#: rules that would not have created it today. The operator can
#: overrule policy; they cannot overrule arithmetic.
ALWAYS_REFUSED = {
    "bad_code": "not a legal short code",
    "reserved_code": "a route already answers on this path",
    "empty_url": "no target",
    "control_chars": "control characters become header injection",
    # Train 0021 (audit N-03). These three used to be liftable, on the
    # theory that they were policy. They are arithmetic -- see
    # `_always_refused` for the mechanism behind each.
    "bad_port": "no client accepts it, and the redirect would drop it",
    "bad_host": "no client reaches it, and serving it can 500 forever",
    "credentials": "userinfo is a disguise, or a republished secret",
}


class ImportReport:
    """What happened, in enough detail to decide what to do next.

    Refusals are split in two because they call for different actions:
    a row refused ALWAYS needs a decision about that link (accept
    losing it, or move the route that shadows it); a row refused BY
    POLICY can be imported with `--allow-unsafe-legacy` once the
    operator has read the list and is willing to own it.
    """

    def __init__(self):
        self.read = 0
        self.imported = 0
        self.skipped_existing = 0
        self.skipped_duplicate_url = 0
        self.refused_always = []
        self.refused_by_policy = []

    def reject(self, code, url, reason, always):
        entry = (code, url, reason)
        if always:
            self.refused_always.append(entry)
        else:
            self.refused_by_policy.append(entry)

    @property
    def rejected(self):
        """Every refusal, both kinds. Kept for callers that only count."""
        return self.refused_always + self.refused_by_policy

    def _rows(self, entries, label):
        lines = []
        for code, url, reason in entries:
            lines.append("  %-8s %-14s %-28s %s" % (label, code, reason, url[:80]))
        return lines

    def as_text(self) -> str:
        lines = [
            "rows read              : %d" % self.read,
            "imported               : %d" % self.imported,
            "already present        : %d" % self.skipped_existing,
            "duplicate target URL   : %d" % self.skipped_duplicate_url,
            "refused (unfixable)    : %d" % len(self.refused_always),
            "refused (policy)       : %d" % len(self.refused_by_policy),
        ]
        lines += self._rows(self.refused_always, "REFUSED")
        lines += self._rows(self.refused_by_policy, "POLICY")
        if self.refused_by_policy:
            lines.append("")
            lines.append(
                "The POLICY rows are links that work; the 2.x rules simply "
                "would not create them today."
            )
            lines.append(
                "Read the list, then re-run with --allow-unsafe-legacy to "
                "import them anyway."
            )
        if self.refused_always:
            lines.append("")
            lines.append(
                "The REFUSED rows cannot be imported by any flag. A "
                "reserved_code is shadowed by a route: either that link is "
                "lost, or the route moves."
            )
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


def _always_refused(code, url):
    """Refusals no flag can lift. Returns a reason, or None."""
    if not is_valid_code(code):
        return "bad_code"
    if code in RESERVED_CODES:
        # EXTERNAL AUDIT 2026-08-22, finding C-10. `is_valid_code` says
        # `healthz` is a legal code -- it is seven characters of the
        # alphabet -- so a 2016 row carrying it imported cleanly and
        # became a link nobody could ever follow, because `/healthz`
        # is a route. `tests/test_routes.py` already asserts that no
        # route may shadow a code; the import was the one door left
        # open. Reported rather than renamed: a renamed code is a dead
        # link, and only the operator can weigh a dead link against an
        # unreachable one.
        return "reserved_code"
    if not url:
        return "empty_url"
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        return "control_chars"
    try:
        parts = urlsplit(url)
    except ValueError:
        # Python 3.11+ validates a bracketed literal itself:
        # `http://[not-an-ipv6]/` raises here, before any check of
        # ours -- and no client resolves it either.
        return "bad_host"
    scheme = (parts.scheme or "").lower()
    if scheme in NEVER_IMPORTED_SCHEMES:
        return "scheme:%s" % scheme
    if parts.netloc:
        # EXTERNAL AUDIT (Claude, 2026-08-23), finding N-03 --
        # sharpening point 5 of the third ChatGPT pass. These three
        # were liftable, on the theory that they were policy. They are
        # arithmetic:
        #
        # * userinfo in the authority: for http(s), the part before
        #   '@' is what the visitor reads and the part after is where
        #   they go -- the dress-up refused at creation; for schemes
        #   where userinfo is real authentication, importing the row
        #   REPUBLISHES a credential to anyone who asks for the code;
        # * an invalid port: no client accepts `:99999` -- and worse,
        #   `to_wire_url` swallows the ValueError at redirect time
        #   (the C-16 branch kept for rows already in the database)
        #   and rebuilds the netloc WITHOUT the port, so the visitor
        #   is sent to a DIFFERENT destination from the stored one.
        #   The verbatim contract this tool exists to defend is
        #   exactly what such a row cannot keep;
        # * an irrecoverable host: a numeric-looking non-address is a
        #   URL every client refuses (a dead link, the C-10 class),
        #   and one carrying non-ASCII that IDNA cannot encode passes
        #   through `to_wire_url` unchanged into `Location:` -- the
        #   S-01 500-on-every-visit, fixed everywhere else, brought
        #   back by an import flag. The check is deliberately the
        #   creation-time one, `canonical_host` strict: one rule for
        #   what is minted and what is imported, not two. The cost,
        #   accepted: an ASCII host of unusual shape that some
        #   browsers tolerate (an underscore, say) is swept in --
        #   such a row is reported with its URL, and a hand decision
        #   per odd row beats a flag that also lifts the 500s.
        #
        # The dividing rule is unchanged: the operator can overrule
        # policy; they cannot overrule arithmetic. Private targets,
        # blocked hosts, over-long URLs and old functional schemes
        # remain theirs to take back.
        if "@" in parts.netloc:
            return "credentials"
        try:
            parts.port
        except ValueError:
            return "bad_port"
        try:
            canonical_host(parts.hostname or "", strict=True)
        except InvalidURL:
            return "bad_host"
    return None


def classify(code, url, settings, allow_unsafe=False):
    """Return `(reason, always)` for a legacy row, or `(None, False)`.

    `always` is True when the refusal is one `--allow-unsafe-legacy`
    cannot lift.

    `normalise_url` is used here as a JUDGE and never as a transformer:
    its return value is discarded. The migration contract says the 2016
    URLs are stored verbatim, because a corrected URL is a different
    destination from the one the link has been promising for ten years.
    What this adds is knowing WHICH rows today's rules would refuse, so
    the operator sees the list instead of discovering it in production.
    """
    reason = _always_refused(code, url)
    if reason is not None:
        return reason, True
    if allow_unsafe:
        return None, False
    try:
        normalise_url(url, settings)
    except InvalidURL as invalid:
        return (invalid.msgid if not invalid.detail
                else "%s:%s" % (invalid.msgid, invalid.detail)), False
    return None, False


def import_rows(dbsession, rows, settings, report=None, allow_unsafe=False):
    """Insert legacy rows. Returns an `ImportReport`.

    `settings` is an `AppSettings`: the same object the running service
    uses, so the classification below is the service's own policy and
    not a second copy of it drifting quietly out of step.
    """
    report = report or ImportReport()
    for _legacy_id, code, url in rows:
        report.read += 1
        reason, always = classify(code, url, settings, allow_unsafe=allow_unsafe)
        if reason:
            report.reject(code, url or "", reason, always)
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
    parser.add_argument(
        "--allow-unsafe-legacy",
        action="store_true",
        help=(
            "import rows the CURRENT rules would refuse (a scheme outside "
            "the allowlist, a private or blocked target, an over-long URL). "
            "Rows that cannot work or must not work are still refused. Run "
            "without this flag first and read the list."
        ),
    )
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)

    setup_logging(arguments.config_uri)
    env = bootstrap(arguments.config_uri)
    try:
        request = env["request"]
        settings = request.app_settings
        if arguments.allow_unsafe_legacy:
            print(
                "[import] --allow-unsafe-legacy: the current URL rules are "
                "NOT applied to these rows"
            )
        report = import_rows(
            request.dbsession,
            read_legacy_rows(arguments.legacy_db),
            settings,
            allow_unsafe=arguments.allow_unsafe_legacy,
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
