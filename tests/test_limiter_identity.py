# -*- coding: utf-8 -*-
"""The limiter's identity and its cost (train 0014).

External audit, second pass, findings D-03 and D-04. Train 0004 bounded
the limiter's memory and left a CPU cost behind; and counting per full
IPv6 address counts nothing, because one subscriber owns an entire /64.
"""
import time

import pytest

from urlshortener.throttle import IPV6_PREFIX, RateLimiter, client_identity


# -- D-04 -- one subscriber, one identity ---------------------------------

def test_d04_addresses_in_one_ipv6_prefix_share_a_budget():
    """A machine handed a /64 can use a fresh source address per
    request. Per-address counting therefore limits nothing at all."""
    limiter = RateLimiter(3, 300)
    for suffix in range(3):
        assert limiter.allow(client_identity("2001:db8:abcd:1234::%x" % suffix)) is True
    assert limiter.allow(client_identity("2001:db8:abcd:1234:ffff::9")) is False


def test_d04_a_different_prefix_is_a_different_customer():
    limiter = RateLimiter(1, 300)
    assert limiter.allow(client_identity("2001:db8:abcd:1234::1")) is True
    assert limiter.allow(client_identity("2001:db8:abcd:9999::1")) is True


def test_d04_ipv4_keeps_its_full_address():
    """There is no equivalent allocation to collapse; two IPv4 hosts
    are two customers."""
    limiter = RateLimiter(1, 300)
    assert limiter.allow(client_identity("203.0.113.9")) is True
    assert limiter.allow(client_identity("203.0.113.10")) is True
    assert limiter.allow(client_identity("203.0.113.9")) is False


@pytest.mark.parametrize("address,expected", [
    ("203.0.113.9", "203.0.113.9"),
    ("2001:db8:abcd:1234:5678::1", "2001:db8:abcd:1234::/64"),
    ("[2001:db8::1]", "2001:db8::/64"),
    ("::1", "::/64"),
    (None, "unknown"),
    ("", "unknown"),
    ("not-an-address", "not-an-address"),
])
def test_d04_the_identity_is_stable_and_never_raises(address, expected):
    assert client_identity(address) == expected


def test_d04_the_prefix_is_the_documented_one():
    assert IPV6_PREFIX == 64


def test_d04_both_creation_paths_use_the_same_identity(testapp):
    """The form and the API must count against one budget, or the
    limit is halved by using both."""
    from urlshortener import api, views

    assert api._client_key is views._client_key


# -- D-03 -- the sweep is gone --------------------------------------------

def test_d03_a_new_key_at_the_ceiling_is_cheap():
    """Before: every new key swept all 20 000 entries with the lock
    held, measured at 0.83 ms each — an attacker rotating addresses
    bought about a thousand times their own cost."""
    limiter = RateLimiter(30, 300, max_keys=20000)
    for index in range(20000):
        limiter.allow("2001:db8::%x" % index)

    start = time.perf_counter()
    for index in range(500):
        limiter.allow("2001:db8:1::%x" % index)
    per_call = (time.perf_counter() - start) / 500

    assert per_call < 0.0001, "%.3f ms per new key at the ceiling" % (per_call * 1000)


def test_d03_the_ceiling_still_holds():
    limiter = RateLimiter(5, 300, max_keys=100)
    for index in range(5000):
        limiter.allow("198.51.100.%d" % index)
    assert len(limiter._events) <= 100


def test_d03_the_evicted_key_is_the_least_recently_seen():
    """Eviction must not throw away an active client while an idle one
    stays. `move_to_end` on every touch is what makes that true."""
    limiter = RateLimiter(5, 300, max_keys=3)
    limiter.allow("a")
    limiter.allow("b")
    limiter.allow("c")
    limiter.allow("a")          # 'a' becomes the youngest, 'b' the oldest
    limiter.allow("d")          # forces one eviction
    assert "b" not in limiter._events
    assert "a" in limiter._events


def test_d03_normal_accounting_is_unchanged():
    limiter = RateLimiter(2, 300, max_keys=100)
    assert limiter.allow("a") and limiter.allow("a")
    assert limiter.allow("a") is False


def test_d03_the_window_still_expires():
    clock = [1000.0]
    limiter = RateLimiter(2, 60, clock=lambda: clock[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert limiter.allow("a") is False
    clock[0] += 61
    assert limiter.allow("a") is True
