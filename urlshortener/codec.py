# -*- coding: utf-8 -*-
# Copyright (c) 2016 Ecreall — Copyright (c) 2026 Logikascium
# Licensed under the GNU Affero General Public License v3 or later.
"""Short-code alphabet and generation.

The alphabet is byte-for-byte the one the 2016 service used (digits,
then lowercase, then uppercase), so every code minted by the old
instance is still a legal code here and keeps resolving after import.

What changed is how a NEW code is chosen. The old service handed out a
strictly sequential counter: seeing `4f2` told you `4f3` existed, and
the whole corpus could be walked in a few thousand requests. Codes are
now drawn from `secrets`, so knowing one tells you nothing about the
others.
"""
from __future__ import annotations

import secrets
import string
from typing import Final

#: Same order as the 2016 `BASE` list -- do not reorder, `decode_int`
#: of a legacy code depends on it.
ALPHABET: Final = string.digits + string.ascii_lowercase + string.ascii_uppercase
BASE: Final = len(ALPHABET)  # 62

_ALPHABET_SET: Final = frozenset(ALPHABET)

#: Codes never handed out, because a route already answers on them.
#: `tests/test_codec.py` checks this set against the registered routes,
#: so adding a route without reserving its name fails the suite.
RESERVED_CODES: Final = frozenset({"api", "healthz", "static", "locale", "favicon.ico", "robots.txt"})

#: Bounds accepted by `is_valid_code`. The lower bound is 1 because the
#: very first legacy code was the single character '0'.
MIN_CODE_LENGTH: Final = 1
MAX_CODE_LENGTH: Final = 32


def encode_int(number: int) -> str:
    """Render a non-negative integer in base 62 with `ALPHABET`."""
    if number < 0:
        raise ValueError("encode_int expects a non-negative integer")
    if number == 0:
        return ALPHABET[0]
    digits = []
    while number:
        number, remainder = divmod(number, BASE)
        digits.append(ALPHABET[remainder])
    return "".join(reversed(digits))


def decode_int(code: str) -> int:
    """Inverse of `encode_int`. Raises ValueError on a foreign character."""
    value = 0
    for char in code:
        index = ALPHABET.find(char)
        if index < 0:
            raise ValueError("character %r is not in the alphabet" % char)
        value = value * BASE + index
    return value


def is_valid_code(code) -> bool:
    """True when `code` could have been minted by this service.

    Used to reject junk before it reaches the database, and to decide
    whether an unknown path is a mistyped short link or plain noise.
    """
    if not isinstance(code, str):
        return False
    if not (MIN_CODE_LENGTH <= len(code) <= MAX_CODE_LENGTH):
        return False
    return _ALPHABET_SET.issuperset(code)


def generate_code(length: int = 7) -> str:
    """Draw one unpredictable code of `length` characters.

    Collisions are handled by the caller (it holds the database), which
    retries; at length 7 the space is 62**7, roughly 3.5e12.
    """
    if not (MIN_CODE_LENGTH <= length <= MAX_CODE_LENGTH):
        raise ValueError("code length must be between %d and %d" % (MIN_CODE_LENGTH, MAX_CODE_LENGTH))
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if code not in RESERVED_CODES:
            return code
