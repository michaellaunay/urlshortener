# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Print the `admin_password_hash` value for a password.

    python -m urlshortener.tools.hash_password
    python -m urlshortener.tools.hash_password 'the password'

The output goes into `urlshortener.admin_password_hash` (or the
environment). The password itself is stored nowhere.
"""
from __future__ import annotations

import getpass
import hashlib
import secrets
import sys

#: OWASP's 2023 floor for PBKDF2-HMAC-SHA256.
ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2$%d$%s$%s" % (ITERATIONS, salt.hex(), digest.hex())


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    password = argv[1] if len(argv) > 1 else getpass.getpass("Admin password: ")
    if not password:
        print("empty password refused", file=sys.stderr)
        return 2
    print(hash_password(password))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
