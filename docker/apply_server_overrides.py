# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Write a runtime .ini with the container's server settings applied.

Why this exists: `pserve` reads `[server:main] listen` from the file,
and PasteDeploy's `global_conf` does NOT reach that section -- proven
the hard way on AlirPunkto. So rather than baking a container-specific
`listen` into the versioned `production.ini` (which would then be wrong
on bare metal), the entrypoint derives a runtime copy.

The source file is never modified. The copy goes to `var/`, which is
the volume, so an operator can read exactly what the server was given.

    python docker/apply_server_overrides.py production.ini var/runtime.ini
"""
from __future__ import annotations

import ipaddress
import os
import struct
import sys
from configparser import RawConfigParser

#: Environment variable -> (section, option).
#:
#: `tests/test_deployment_conventions.py` checks this mapping against
#: what `docker/docker-compose.yaml` actually passes into the container:
#: an override nobody forwards is a setting the operator believes in and
#: that never arrives (external audit C-07).
OVERRIDES = {
    "URLSHORTENER_LISTEN": ("server:main", "listen"),
    "URLSHORTENER_TRUSTED_PROXY": ("server:main", "trusted_proxy"),
    "URLSHORTENER_TRUSTED_PROXY_COUNT": ("server:main", "trusted_proxy_count"),
    # The SAME variable the application reads as `max_body_bytes`, so
    # the server limit and the application limit cannot drift apart.
    "URLSHORTENER_MAX_BODY_BYTES": ("server:main", "max_request_body_size"),
    "SQLALCHEMY_URL": ("app:main", "sqlalchemy.url"),
}

#: The value of `trusted_proxy` that only makes sense on bare metal.
BARE_METAL_TRUSTED_PROXY = "127.0.0.1"

#: Written in `URLSHORTENER_TRUSTED_PROXY` to trust nothing at all.
NO_PROXY = "none"


def default_gateway(route_table="/proc/net/route"):
    """Return the container's default gateway as a string, or None.

    EXTERNAL AUDIT 2026-08-22, finding C-07 (second half). Inside a
    container, `trusted_proxy = 127.0.0.1` is not merely useless, it is
    WRONG: nginx runs on the host and reaches the service through the
    Docker bridge, so waitress sees the gateway address, decides the
    peer is not the trusted proxy, and ignores `X-Forwarded-For`
    entirely. `request.client_addr` then becomes the SAME address for
    every visitor -- the bridge -- and the creation limiter, which is
    keyed on it, silently becomes one global budget that a single
    visitor can exhaust for everyone.

    The gateway address is not knowable when the compose file is
    written, so it is read at start-up from the kernel's own routing
    table: the default route is the one with destination 0.0.0.0, and
    the gateway field is a little-endian hexadecimal address.
    """
    try:
        with open(route_table, encoding="ascii") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 3 or fields[1] != "00000000":
            continue
        try:
            packed = struct.pack("<L", int(fields[2], 16))
            address = ipaddress.IPv4Address(packed)
        except (ValueError, struct.error, ipaddress.AddressValueError):
            continue
        # A default route with no gateway (`is_unspecified`) means the
        # destination is on-link: there is no proxy address to trust.
        #
        # Written as `is_unspecified` rather than as a comparison with
        # the literal address: bandit reads that literal as a bind to
        # every interface (B104) and fails the quality job. Train 0004
        # introduced exactly that, and the gate was not re-read closely
        # enough at the time -- `grep "No issues|Total lines"` matched
        # the second pattern and looked green.
        if address.is_unspecified:
            continue
        return str(address)
    return None


def resolve_trusted_proxy(parser, environ, route_table="/proc/net/route"):
    """Decide what `trusted_proxy` should be, and say why.

    Returns `(value_or_None, reason)`. An explicit environment value
    always wins, `none` disables the trust entirely, and the gateway is
    only substituted when the file still carries the bare-metal
    default -- an operator who wrote a value keeps it.
    """
    requested = (environ.get("URLSHORTENER_TRUSTED_PROXY") or "").strip()
    if requested.lower() == NO_PROXY:
        return "", "URLSHORTENER_TRUSTED_PROXY=none — no proxy is trusted"
    if requested:
        return requested, "URLSHORTENER_TRUSTED_PROXY set explicitly"

    current = ""
    if parser.has_option("server:main", "trusted_proxy"):
        current = parser.get("server:main", "trusted_proxy").strip()
    if current and current != BARE_METAL_TRUSTED_PROXY:
        return None, "trusted_proxy already set to %r in the file" % current

    gateway = default_gateway(route_table)
    if gateway is None or gateway == BARE_METAL_TRUSTED_PROXY:
        return None, "no container gateway found — leaving %r" % (current or "unset")
    return gateway, (
        "container gateway %s substituted for the bare-metal default %s "
        "(otherwise X-Forwarded-For is ignored and every visitor shares "
        "one rate-limit budget)" % (gateway, BARE_METAL_TRUSTED_PROXY)
    )


def apply_overrides(parser, environ):
    """Apply the overrides present in `environ`. Returns what changed."""
    applied = []
    for variable, (section, option) in OVERRIDES.items():
        value = environ.get(variable)
        if value is None or value == "":
            continue
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, option, value)
        applied.append((variable, section, option, value))
    return applied


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) < 3:
        print(
            "usage: apply_server_overrides.py <source.ini> <destination.ini>",
            file=sys.stderr,
        )
        return 2
    source, destination = argv[1], argv[2]

    # RawConfigParser: the .ini uses %(here)s, which ConfigParser would
    # try to interpolate and fail on. pserve does that substitution
    # itself, later, with the right value.
    parser = RawConfigParser()
    parser.optionxform = str
    if not parser.read(source, encoding="utf-8"):
        print("cannot read %s" % source, file=sys.stderr)
        return 1

    # %(here)s in the source refers to the SOURCE directory; the copy
    # lives elsewhere, so resolve it now rather than let pserve resolve
    # it against the wrong directory.
    here = os.path.dirname(os.path.abspath(source))
    for section in parser.sections():
        for option, value in parser.items(section):
            if "%(here)s" in value:
                parser.set(section, option, value.replace("%(here)s", here))

    applied = apply_overrides(parser, os.environ)

    proxy_value, proxy_reason = resolve_trusted_proxy(parser, os.environ)
    if proxy_value is not None:
        if not parser.has_section("server:main"):
            parser.add_section("server:main")
        parser.set("server:main", "trusted_proxy", proxy_value)
    print("[proxy] %s" % proxy_reason)

    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    # AUDIT 2026-08-22, finding S-07: this file lands on the DATA
    # VOLUME and may carry a database URL with a password in it. Create
    # it 0600 rather than inherit the umask -- and create it that way
    # from the start, not with a chmod after the write, which would
    # leave a window during which it is readable.
    file_descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
        parser.write(handle)

    for variable, section, option, value in applied:
        # Never print a database URL: it can carry a password.
        shown = "<hidden>" if "URL" in variable and "://" in value and "@" in value else value
        print("[override] %s -> [%s] %s = %s" % (variable, section, option, shown))
    print("[override] wrote %s" % destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
