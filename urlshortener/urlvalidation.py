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
from urllib.parse import quote, urlsplit, urlunsplit

import idna

#: One DNS label: letters, digits and hyphens, never leading or
#: trailing, at most 63 characters.
_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")

#: Hostnames that always designate the machine itself.
LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})

#: A label that a browser will try to read as a number. `ipaddress`
#: refuses every one of these spellings; a browser accepts them all.
_NUMERIC_LABEL = re.compile(r"^(0[xX][0-9a-fA-F]+|[0-9]+)$")


def _parse_ipv4_part(part: str):
    """Read one dotted part the way a browser does, or return None.

    Three bases, and the prefix decides: `0x1f` is hexadecimal, `017`
    is octal, `17` is decimal. Python's `ipaddress` module knows only
    the third, which is the whole problem this function exists to fix.
    """
    if not part:
        return None
    try:
        if part[:2] in ("0x", "0X"):
            return int(part[2:], 16) if len(part) > 2 else 0
        if len(part) > 1 and part[0] == "0":
            return int(part[1:], 8)
        return int(part, 10)
    except ValueError:
        return None


def parse_browser_ipv4(host: str):
    """Return the IPv4Address a browser would reach, or None.

    EXTERNAL AUDIT 2026-08-22, finding C-02. `block_private_targets`
    was checked with `ipaddress.ip_address()`, which accepts exactly
    one spelling of an address. A browser accepts four, and the URL
    Standard requires it to:

        http://127.0.0.1/     refused   (the only one we caught)
        http://2130706433/    ACCEPTED  -- same machine
        http://127.1/         ACCEPTED  -- same machine
        http://0x7f000001/    ACCEPTED  -- same machine
        http://0177.0.0.1/    ACCEPTED  -- same machine

    So the promise `block_private_targets = true` was not kept: a short
    link could hide `127.0.0.1` from the visitor who follows it. This
    is not server-side SSRF -- the service never fetches the target --
    but on an internal network it is a way to dress up an internal
    address as a public link.

    Rules from the URL Standard section 3.3: at most four parts, a
    trailing empty part dropped, every part but the last at most 255,
    the last part absorbing the remaining space.
    """
    parts = host.split(".")
    if len(parts) > 1 and parts[-1] == "":
        parts = parts[:-1]
    if not parts or len(parts) > 4:
        return None
    numbers = [_parse_ipv4_part(part) for part in parts]
    if any(number is None for number in numbers):
        return None
    if any(number > 255 for number in numbers[:-1]):
        return None
    if numbers[-1] >= 256 ** (4 - (len(numbers) - 1)):
        return None
    value = numbers[-1]
    for index, number in enumerate(numbers[:-1]):
        value += number * 256 ** (3 - index)
    try:
        return ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return None


def _looks_numeric(host: str) -> bool:
    """True when a browser would read the LAST label as a number.

    `example.0x1` is not a domain to a browser: it tries the IPv4
    reading, fails, and rejects the URL. We refuse it too rather than
    store something no client can reach.
    """
    labels = host.rstrip(".").split(".")
    return bool(labels) and bool(_NUMERIC_LABEL.match(labels[-1]))


def _to_idna(candidate: str) -> str:
    """Encode a host the way a BROWSER encodes it, not the way Python does.

    EXTERNAL AUDIT, second pass, finding D-01. `str.encode("idna")` is
    the built-in codec, and it implements RFC 3490 -- IDNA2003. A
    browser follows the URL Standard, which is UTS #46 with
    NON-TRANSITIONAL processing. The two disagree on names that exist:

        faß.de       codec -> fass.de            browser -> xn--fa-hia.de
        βόλος.com    codec -> xn--nxasmq6b.com   browser -> xn--nxasmm1c.com

    Those are different domains, and they can have different owners. A
    shortener whose whole promise is "you arrive where you asked to
    arrive" cannot resolve a host differently from the browser that
    will follow the link -- this is the same class of defect as the
    non-ASCII `Location:` fixed in 2.0.1, and it was introduced by the
    canonicalisation train that was meant to close that class.

    `transitional=False` is the browser behaviour and the one that
    keeps ß as ß. `std3_rules=False` matches what browsers accept;
    the label shape is checked separately by `_LABEL` afterwards.
    """
    try:
        return idna.encode(
            candidate, uts46=True, transitional=False, std3_rules=False
        ).decode("ascii").lower()
    except (idna.IDNAError, UnicodeError, UnicodeDecodeError) as error:
        raise InvalidURL("error_url_host", str(error)) from None


def canonical_host(host: str, strict=True):
    """Return `(canonical_ascii_host, ip_or_None)`.

    ONE canonicalisation, used by every check that follows. The bug
    class this closes (external audit C-08) is having several spellings
    of one name and testing a different spelling from the one that is
    stored:

        blocked_hosts = xn--bcher-kva.example
        https://xn--bcher-kva.example/   refused
        https://bücher.example/          ACCEPTED   -- same DNS name

    With `strict=False` nothing is raised: that mode is for
    `to_wire_url`, which also runs against rows imported verbatim from
    2016 and must never turn an odd old row into an exception.
    """
    if not host:
        if strict:
            raise InvalidURL("error_url_host")
        return host, None

    # IPv6 literal -- `parts.hostname` has already dropped the brackets.
    if ":" in host:
        try:
            address = ipaddress.IPv6Address(host.strip("[]"))
        except ValueError:
            if strict:
                raise InvalidURL("error_url_host", host) from None
            return host, None
        return "[%s]" % address.compressed, address

    address = parse_browser_ipv4(host)
    if address is not None:
        return address.compressed, address
    if _looks_numeric(host):
        # A numeric-looking host that is NOT a valid address: a browser
        # rejects it outright, so storing it would mint a dead link.
        if strict:
            raise InvalidURL("error_url_host", host)
        return host, None

    candidate = host.rstrip(".")
    if not candidate or len(candidate) > 253:
        if strict:
            raise InvalidURL("error_url_host", host)
        return host, None
    try:
        ascii_host = _to_idna(candidate)
    except InvalidURL:
        if strict:
            raise
        return host, None
    if not all(_LABEL.match(label) for label in ascii_host.split(".")):
        if strict:
            raise InvalidURL("error_url_host", host)
        return host, None
    return ascii_host, None


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


def _host_is_private(host: str, address=None) -> bool:
    """True for a LITERAL address outside the public internet.

    `address` is the one `canonical_host` already parsed, so the four
    browser spellings of 127.0.0.1 are all judged here, not just the
    dotted-quad one (external audit C-02).

    A name is never resolved (see the module docstring), so
    `internal.example.com` passes; only literal addresses, and the
    well-known local names, are caught.
    """
    if host.strip("[]").lower() in LOCAL_HOSTNAMES:
        return True
    if address is None:
        return False
    # `is_global` is the complement we actually want: it covers the
    # documentation ranges, 6to4, benchmarking and the rest, instead of
    # a hand-kept list of properties that is short by construction.
    if not address.is_global:
        return True
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def to_wire_url(url: str) -> str:
    """Return `url` in a form that can legally be put in a header.

    AUDIT 2026-08-22, finding S-01. An HTTP field value is ASCII. WebOb
    hands the header to waitress, which does `res.encode("latin-1")`,
    so a target carrying non-ASCII characters produced one of two
    outcomes, both bad:

    * inside latin-1 (`münchen.example/café`): the UTF-8 was re-encoded
      as latin-1 and the visitor was sent to a MANGLED address;
    * outside latin-1 (Japanese, Cyrillic, an emoji): a hard
      `UnicodeEncodeError`, i.e. a 500 with a traceback on EVERY visit
      to that link, for ever, and an unauthenticated way for anyone to
      flood the log.

    The fix is to store, and to serve, the wire form: IDNA for the
    host, percent-encoding for the rest. `%` is kept safe so an
    already-encoded URL is not double-encoded -- `%20` stays `%20`
    instead of becoming `%2520`.

    Applied at creation (so new rows are stored wire-safe) AND at
    redirect time (so the rows imported verbatim from 2016, which this
    function never saw, cannot 500 either).
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return url

    ascii_host, _address = canonical_host(host, strict=False)

    netloc = ascii_host
    try:
        port = parts.port
    except ValueError:
        # REGRESSION of my own 2.0.1 fix, caught by external audit C-16:
        # `parts.port` is lazy and raises on `:99999` or `:abc`, so
        # to_wire_url -- called from normalise_url -- turned a bad port
        # into a 500 instead of a refusal. Creation now rejects those
        # ports before reaching here; this branch is for the legacy rows
        # that never went through creation.
        port = None
    if port:
        netloc = "%s:%d" % (netloc, port)

    return urlunsplit((
        parts.scheme,
        netloc,
        quote(parts.path, safe="/%:@!$&'()*+,;=~-._"),
        quote(parts.query, safe="/%:@!$&'()*+,;=?~-._"),
        quote(parts.fragment, safe="/%:@!$&'()*+,;=?~-._"),
    ))


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


def _host_is_blocked(host: str, blocked) -> bool:
    """True when `host` is, or is a subdomain of, a blocked name.

    Both sides are canonicalised, so the operator can write the list in
    whichever spelling they think in -- `bücher.example` and
    `xn--bcher-kva.example` block the same name (external audit C-08).
    """
    host = canonical_host(host, strict=False)[0]
    for blocked_host in blocked:
        blocked_host = canonical_host(str(blocked_host), strict=False)[0]
        if not blocked_host:
            continue
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

    # The port BEFORE anything else touches the authority: `parts.port`
    # is a lazy property that raises on `:99999` or `:abc`, and one of
    # the callers below reads it (external audit C-16).
    try:
        port = parts.port
    except ValueError:
        raise InvalidURL("error_url_port") from None

    # ONE canonical spelling of the host, computed once. Every check
    # below uses it, and it is what gets stored -- so no check can ever
    # again be run against a different spelling from the stored one.
    host, address = canonical_host(parts.hostname or "")

    if settings.blocked_hosts and _host_is_blocked(host, settings.blocked_hosts):
        raise InvalidURL("error_url_blocked", host)

    if settings.block_private_targets and _host_is_private(host, address):
        raise InvalidURL("error_url_private", host)

    # Rebuild from the canonical pieces: what is stored is exactly what
    # was checked.
    netloc = host if port is None else "%s:%d" % (host, port)
    normalised = to_wire_url(
        urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))
    )
    if len(normalised) > settings.max_url_length:
        raise InvalidURL("error_url_too_long")
    return normalised
