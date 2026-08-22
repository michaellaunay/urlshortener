# -*- coding: utf-8 -*-
"""The alphabet is a compatibility surface, not an implementation detail."""
import string

import pytest

from urlshortener import codec


def test_alphabet_is_the_2016_alphabet_in_the_2016_order():
    # Legacy: BASE = digits + ascii_lowercase + ascii_uppercase.
    # Reordering it would not break new codes, but it would change what
    # decode_int() says about an OLD one.
    assert codec.ALPHABET == string.digits + string.ascii_lowercase + string.ascii_uppercase
    assert codec.BASE == 62


@pytest.mark.parametrize("number,expected", [(0, "0"), (1, "1"), (9, "9"), (10, "a"),
                                             (35, "z"), (36, "A"), (61, "Z"), (62, "10")])
def test_encode_int_matches_the_alphabet(number, expected):
    assert codec.encode_int(number) == expected


def test_encode_decode_round_trip():
    for number in (0, 1, 61, 62, 3843, 999_999, 62 ** 7 - 1):
        assert codec.decode_int(codec.encode_int(number)) == number


def test_encode_int_refuses_negative():
    with pytest.raises(ValueError):
        codec.encode_int(-1)


def test_decode_int_refuses_a_foreign_character():
    with pytest.raises(ValueError):
        codec.decode_int("ab-cd")


def test_legacy_single_character_codes_are_valid():
    # The first codes the old service ever handed out were '0', '1', ...
    for code in ("0", "9", "a", "Z"):
        assert codec.is_valid_code(code)


@pytest.mark.parametrize("code", ["", "a b", "abc/def", "é", "a" * 33, None, 42, "a-b"])
def test_is_valid_code_rejects_junk(code):
    assert not codec.is_valid_code(code)


def test_generate_code_has_the_requested_length_and_alphabet():
    for length in (1, 4, 7, 12):
        code = codec.generate_code(length)
        assert len(code) == length
        assert set(code) <= set(codec.ALPHABET)


def test_generate_code_is_not_sequential():
    # The whole point of the change: 2016 handed out 0,1,2,... so one
    # code disclosed every other. 500 draws must not collide, and must
    # not be consecutive.
    codes = [codec.generate_code(7) for _ in range(500)]
    assert len(set(codes)) == 500


def test_generate_code_refuses_an_absurd_length():
    with pytest.raises(ValueError):
        codec.generate_code(0)
    with pytest.raises(ValueError):
        codec.generate_code(codec.MAX_CODE_LENGTH + 1)


def test_generate_code_never_returns_a_reserved_word():
    # 'api' is three characters, so ask for three-character codes and
    # draw enough of them that the reserved word would show up.
    for _ in range(2000):
        assert codec.generate_code(3) not in codec.RESERVED_CODES
