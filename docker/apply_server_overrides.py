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

import os
import sys
from configparser import RawConfigParser

#: Environment variable -> (section, option).
OVERRIDES = {
    "URLSHORTENER_LISTEN": ("server:main", "listen"),
    "URLSHORTENER_TRUSTED_PROXY": ("server:main", "trusted_proxy"),
    "SQLALCHEMY_URL": ("app:main", "sqlalchemy.url"),
}


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

    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    with open(destination, "w", encoding="utf-8") as handle:
        parser.write(handle)

    for variable, section, option, value in applied:
        # Never print a database URL: it can carry a password.
        shown = "<hidden>" if "URL" in variable and "://" in value and "@" in value else value
        print("[override] %s -> [%s] %s = %s" % (variable, section, option, shown))
    print("[override] wrote %s" % destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
