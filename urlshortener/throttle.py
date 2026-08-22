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

import threading
import time
from collections import deque


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
    MAX_KEYS = 20000

    def __init__(self, max_events: int, window_seconds: int, clock=time.monotonic,
                 max_keys=None):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.max_keys = self.MAX_KEYS if max_keys is None else max_keys
        self._clock = clock
        # Insertion-ordered, so the first key is the oldest.
        self._events = {}
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
            if len(self._events) > self.max_keys:
                # Drop expired entries first; evict the oldest only if
                # that was not enough.
                threshold = now - self.window_seconds
                for stale in [
                    key for key, seen in self._events.items()
                    if not seen or seen[-1] <= threshold
                ]:
                    del self._events[stale]
                while len(self._events) > self.max_keys:
                    self._events.pop(next(iter(self._events)))
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
