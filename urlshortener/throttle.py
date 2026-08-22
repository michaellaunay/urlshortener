# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Creation rate limiting, in memory, per client address.

Scope, stated plainly: this is a courtesy limit, not a defence against a
determined flood. It lives in the process, so N workers allow N times
the configured rate, and a restart forgets everything. It exists to stop
a stuck script from filling the table, and it costs nothing. A real
limit belongs in the reverse proxy (`limit_req` in nginx), which is
documented in `docs/*/07_*`.

No address is ever written to the database (see `models/link.py`); the
window below holds them for at most `window_seconds` and then drops them.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict, deque

#: IPv6 prefix length used as the throttling identity.
#:
#: EXTERNAL AUDIT, second pass, finding D-04. A single subscriber is
#: handed a /64 -- eighteen billion billion addresses -- so limiting per
#: full IPv6 address limits nothing at all: one machine simply uses a
#: fresh source address per request. The /64 is the smallest unit that
#: corresponds to one customer, and it is what makes the counter mean
#: something. IPv4 keeps the full address; there is no equivalent
#: allocation to collapse.
IPV6_PREFIX = 64


def client_identity(address) -> str:
    """Return the key a limiter should count against, from an address.

    Anything unparseable is returned unchanged: the key only has to be
    stable and comparable, not meaningful. Nothing here is ever written
    to the database.
    """
    if not address:
        return "unknown"
    try:
        parsed = ipaddress.ip_address(address.strip("[]"))
    except ValueError:
        return address
    if parsed.version == 4:
        return parsed.compressed
    network = ipaddress.ip_network("%s/%d" % (parsed.compressed, IPV6_PREFIX), strict=False)
    return network.compressed


class RateLimiter:
    """Sliding window counter, `max_events` per `window_seconds` per key."""

    #: Hard ceiling on the number of tracked keys. AUDIT 2026-08-22,
    #: finding S-04: the key is the client address, which is
    #: attacker-influenced (and fully attacker-controlled if the
    #: trusted-proxy configuration is wrong). Without a ceiling, a scan
    #: from many addresses grows this dictionary until the process is
    #: killed -- a limiter that becomes the denial of service it was
    #: meant to blunt. At the ceiling the OLDEST key is evicted: the
    #: attacker can buy themselves a fresh budget, which is what the
    #: proxy-level limit is for, but they cannot exhaust memory.
    #:
    #: EXTERNAL AUDIT, second pass, finding D-03: bounding the memory
    #: left a CPU cost behind. Every new key at the ceiling swept all
    #: 20 000 entries looking for expired ones, with the lock held --
    #: measured at 0.83 ms per new key, so an attacker rotating source
    #: addresses bought roughly a thousand times their own cost. The
    #: store is now an OrderedDict kept in least-recently-seen order, so
    #: eviction pops the front and the sweep is gone: O(1) amortised.
    MAX_KEYS = 20000

    def __init__(self, max_events: int, window_seconds: int, clock=time.monotonic,
                 max_keys=None):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.max_keys = self.MAX_KEYS if max_keys is None else max_keys
        self._clock = clock
        # Least-recently-seen first; `move_to_end` on every touch keeps
        # it that way, and eviction pops the front.
        self._events = OrderedDict()
        self._lock = threading.Lock()

    def _prune(self, key, now):
        events = self._events.get(key)
        if events is None:
            return None
        threshold = now - self.window_seconds
        while events and events[0] <= threshold:
            events.popleft()
        if not events:
            del self._events[key]
            return None
        return events

    def allow(self, key) -> bool:
        """Record an attempt for `key`; False when over the limit.

        A limit of 0 or less disables the limiter entirely.
        """
        if self.max_events <= 0:
            return True
        now = self._clock()
        with self._lock:
            events = self._prune(key, now)
            if events is None:
                events = deque()
                self._events[key] = events
            if len(events) >= self.max_events:
                return False
            events.append(now)
            # Touched, so youngest: the front of the mapping is always
            # the least recently seen key.
            self._events.move_to_end(key)
            while len(self._events) > self.max_keys:
                self._events.popitem(last=False)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
