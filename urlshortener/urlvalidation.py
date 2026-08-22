# -*- coding: utf-8 -*-
# Copyright (c) 2016 Ecreall — Copyright (c) 2026 Logikascium
# Licensed under the GNU Affero General Public License v3 or later.
"""Validation and normalisation of a submitted target URL.

The 2016 service did one thing to the submitted string: if
`urlparse(url).scheme` was empty it prepended `http://`. Everything else
went straight into an f-string-built SQL statement and, later, into a
302 `Location:` header. `javascript:alert(1)` was a valid short link;
so was `file:///etc/passwd`; so was `http://127.0.0.1:6543/admin`.

Nothing here talks to the network: no DNS lookup, no HEAD request. A
resolution performed at creation time says nothing about where the name
points at redirect time, so paying for it would buy a false sense of
safety. What is enforced is what stays true: the scheme, the shape of
the authority, and literal addresses that are private by definition.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

#: One DNS label: letters, digits and hyphens, never leading or
#: trailing, at most 63 characters.
_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")

#: Hostnames that always designate the machine itself.
LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})


class InvalidURL(ValueError):
    """A submitted URL was refused.

    `msgid` is a translation string identifier, not a sentence: the
    view decides how to render it, and the JSON API returns it as-is so
    a client can branch on the reason rather than parse English prose.
    """

    def __init__(self, msgid: str, detail: str = ""):
        super().__init__(msgid if not detail else "%s: %s" % (msgid, detail))
        self.msgid = msgid
        self.detail = detail


def _host_is_private(host: str) -> bool:
    """True for a LITERAL address inside a private/loopback/reserved range.

    A name is never resolved here (see the module docstring), so
    `internal.example.com` passes; only addresses written out as
    numbers, and the well-known local names, are caught.
    """
    cleaned = host.strip("[]").lower()
    if cleaned in LOCAL_HOSTNAMES:
        return True
    try:
        address = ipaddress.ip_address(cleaned)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _split(candidate):
    """`urlsplit`, but a malformed authority is a refusal, not a crash.

    Since Python 3.11 `urlsplit` validates a bracketed literal itself
    and raises `ValueError` for `http://[not-an-ipv6]/` -- before any
    check of ours ever runs. Left alone that surfaces as a 500 on a
    request the service is supposed to answer with a polite refusal.
    """
    try:
        return urlsplit(candidate)
    except ValueError:
        raise InvalidURL("error_url_host") from None


def _is_valid_hostname(host: str) -> bool:
    """True when `host` is a syntactically usable authority.

    Without this, `<script>alert(1)</script>` is a valid target: the
    default scheme gets prepended, `urlsplit` happily reports a netloc,
    and the string ends up stored and later echoed. Internationalised
    names are accepted through their IDNA form, so `münchen.example`
    passes while `<script>` does not.
    """
    if not host:
        return False
    # An IPv6 literal: `parts.hostname` has already removed the brackets.
    if ":" in host:
        try:
            ipaddress.IPv6Address(host.strip("[]"))
        except ValueError:
            return False
        return True
    candidate = host.rstrip(".")
    if not candidate or len(candidate) > 253:
        return False
    try:
        ascii_host = candidate.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        return False
    return all(_LABEL.match(label) for label in ascii_host.split("."))


def _host_is_blocked(host: str, blocked) -> bool:
    """True when `host` is, or is a subdomain of, a blocked name."""
    host = host.lower().rstrip(".")
    for blocked_host in blocked:
        blocked_host = blocked_host.lower().rstrip(".")
        if host == blocked_host or host.endswith("." + blocked_host):
            return True
    return False


def normalise_url(raw, settings) -> str:
    """Return the URL to store, or raise `InvalidURL`.

    `settings` is an `AppSettings`. The 2016 behaviour of supplying a
    missing scheme is kept -- `example.org/x` still works in the form --
    but the resulting scheme must then be in the allowed list like any
    other.
    """
    if raw is None:
        raise InvalidURL("error_url_required")
    candidate = str(raw).strip()
    if not candidate:
        raise InvalidURL("error_url_required")
    # A newline in a stored URL becomes a header-injection attempt the
    # day it is written into `Location:`; refuse control characters
    # outright rather than stripping them and storing something the
    # submitter did not type.
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate):
        raise InvalidURL("error_url_control_characters")
    if len(candidate) > settings.max_url_length:
        raise InvalidURL("error_url_too_long")

    parts = _split(candidate)
    if not parts.scheme:
        candidate = "%s://%s" % (settings.default_scheme, candidate)
        parts = _split(candidate)

    scheme = parts.scheme.lower()
    if scheme not in settings.allowed_schemes:
        raise InvalidURL("error_url_scheme", scheme)

    if not parts.netloc:
        raise InvalidURL("error_url_host")

    # Credentials in the authority are the classic dress-up trick
    # (`https://www.your-bank.example@evil.test/`): the visitor reads
    # the part before the '@', the browser goes to the part after it.
    if "@" in parts.netloc:
        raise InvalidURL("error_url_credentials")

    host = parts.hostname or ""
    if not _is_valid_hostname(host):
        raise InvalidURL("error_url_host", host)

    if settings.blocked_hosts and _host_is_blocked(host, settings.blocked_hosts):
        raise InvalidURL("error_url_blocked", host)

    if settings.block_private_targets and _host_is_private(host):
        raise InvalidURL("error_url_private", host)

    # Rebuild from the parsed pieces: this drops nothing meaningful and
    # guarantees what is stored is what was parsed and checked.
    normalised = urlunsplit(
        (scheme, parts.netloc, parts.path, parts.query, parts.fragment)
    )
    if len(normalised) > settings.max_url_length:
        raise InvalidURL("error_url_too_long")
    return normalised
