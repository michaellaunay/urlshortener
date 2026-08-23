# -*- coding: utf-8 -*-
# Copyright (c) 2016 Ecreall — Copyright (c) 2026 Logikascium
# Licensed under the GNU Affero General Public License v3 or later.
"""Constants, the supported-locale registry and settings parsing.

Everything that used to be a module-level literal in the 2016 `main.py`
(`host = 'http://6li.eu/'`, the base-62 alphabet, the sqlite path) is
configuration here: one instance can be deployed at any base URL, behind
any prefix, with any database.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

#: Bounds a code may take, mirrored from `codec` -- imported lazily
#: below to keep this module free of application imports.
MIN_CODE_LENGTH: Final = 1
MAX_CODE_LENGTH: Final = 32

#: Room a request needs around the URL itself: JSON braces, the field
#: name, form encoding, a few headers' worth of slack.
BODY_OVERHEAD: Final = 512

from pyramid.i18n import TranslationStringFactory

#: Translation domain. Catalogues live in `urlshortener/locale/<code>/
#: LC_MESSAGES/urlshortener.{po,mo}`.
DOMAIN: Final = "urlshortener"

_: Final = TranslationStringFactory(DOMAIN)

# -- Locale registry ------------------------------------------------------
#
# THE single source of truth for languages. Adding a language is two
# gestures and nothing else:
#   1. flip `selectable` to True here;
#   2. add `locale/<code>/LC_MESSAGES/urlshortener.po` and compile it.
#
# `tests/test_i18n.py` locks the bijection between this registry and what
# is actually on disk, so the two can never drift apart silently.
#
# Codes and native names are deliberately identical to AlirPunkto's
# registry: catalogues can be moved between the two projects verbatim.
#
# Note on scope: the European Union has 24 OFFICIAL languages for 27
# member states (Irish, Maltese and the rest included; German, French
# and Dutch are each shared by several states). The registry below
# carries those 24 plus Esperanto and a few neighbours already present
# in the AlirPunkto catalogues -- 33 codes in all.
SUPPORTED_LOCALES: Final = {
    # Delivered and reviewed -- the four languages of this iteration.
    "en": {"name": "English", "selectable": True, "tier": 1},
    "fr": {"name": "Français", "selectable": True, "tier": 1},
    "de": {"name": "Deutsch", "selectable": True, "tier": 2},
    "es": {"name": "Español", "selectable": True, "tier": 2},
    # Declared, not yet offered: no catalogue on disk yet. Flip
    # `selectable` the day the .po lands -- nothing else to change.
    "eo": {"name": "Esperanto", "selectable": False, "tier": 3},
    "bg": {"name": "български", "selectable": False, "tier": 3},
    "cs": {"name": "čeština", "selectable": False, "tier": 3},
    "da": {"name": "dansk", "selectable": False, "tier": 3},
    "et": {"name": "Eesti", "selectable": False, "tier": 3},
    "el": {"name": "ελληνικά", "selectable": False, "tier": 3},
    "ga": {"name": "Gaeilge", "selectable": False, "tier": 3},
    "hr": {"name": "Hrvatski", "selectable": False, "tier": 3},
    "it": {"name": "Italiano", "selectable": False, "tier": 2},
    "lv": {"name": "Latviešu", "selectable": False, "tier": 3},
    "lt": {"name": "Lietuvių", "selectable": False, "tier": 3},
    "hu": {"name": "Magyar", "selectable": False, "tier": 3},
    "mt": {"name": "Malti", "selectable": False, "tier": 3},
    "nl": {"name": "Nederlands", "selectable": False, "tier": 2},
    "pl": {"name": "Polski", "selectable": False, "tier": 2},
    "pt": {"name": "Português", "selectable": False, "tier": 3},
    "ro": {"name": "Română", "selectable": False, "tier": 3},
    "sk": {"name": "Slovenčina", "selectable": False, "tier": 3},
    "sl": {"name": "Slovenščina", "selectable": False, "tier": 3},
    "fi": {"name": "Suomi", "selectable": False, "tier": 3},
    "sv": {"name": "Svenska", "selectable": False, "tier": 3},
    "be": {"name": "беларуская", "selectable": False, "tier": 3},
    "bs": {"name": "bosanski", "selectable": False, "tier": 3},
    "is": {"name": "íslenska", "selectable": False, "tier": 3},
    "no": {"name": "norsk", "selectable": False, "tier": 3},
    "sq": {"name": "shqip", "selectable": False, "tier": 3},
    "sr": {"name": "српски", "selectable": False, "tier": 3},
    "tr": {"name": "Türkçe", "selectable": False, "tier": 3},
    "uk": {"name": "українська", "selectable": False, "tier": 3},
}

#: Language codes actually offered to visitors, registry order preserved.
AVAILABLE_LANGUAGES: Final = [
    code for code, spec in SUPPORTED_LOCALES.items() if spec["selectable"]
]

#: Native names of the offered languages, for the language switcher.
LANGUAGE_NAMES: Final = {
    code: SUPPORTED_LOCALES[code]["name"] for code in AVAILABLE_LANGUAGES
}

DEFAULT_LOCALE: Final = "en"

#: Name of the cookie remembering an explicit language choice.
LOCALE_COOKIE: Final = "_LOCALE_"

#: One year, in seconds -- lifetime of the language cookie.
LOCALE_COOKIE_MAX_AGE: Final = 31536000


# -- Settings -------------------------------------------------------------

def as_bool(value, default: bool = False) -> bool:
    """Parse the usual .ini / environment truthy spellings."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def as_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_list(value) -> list:
    """Split a whitespace/comma separated .ini value into a clean list."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).replace(",", " ").split() if item.strip()]


#: Schemes that must never be redirected to, whatever the operator
#: configures. A `Location:` carrying one of these turns the service
#: into the attack, under its own domain.
DANGEROUS_SCHEMES: Final = frozenset({"javascript", "data", "vbscript"})


class ConfigurationError(Exception):
    """The configuration cannot be served, and start-up must stop.

    EXTERNAL AUDIT 2026-08-22, finding C-17: `from_settings` accepted
    anything. `code_length = 0` started cleanly and failed later, on the
    first attempt to shorten something, with a ValueError from deep
    inside the codec -- an error message about an alphabet, produced by
    a typo in an .ini file, hours after the deployment was declared
    done. A configuration that cannot work should refuse to start, at
    the moment and in the place where the mistake is legible.
    """


@dataclass(frozen=True)
class AppSettings:
    """Effective configuration, resolved once at application start.

    Precedence is `environment > .ini > default`, so a container can be
    reconfigured without rebuilding the image and without editing the
    .ini shipped inside it.
    """

    #: Public prefix the short links are built on. MUST end with '/'.
    #: Behind nginx's `location /urlmetadata/` this is the full public
    #: URL including that prefix.
    base_url: str = "http://localhost:5123/"
    #: Length of a freshly generated code.
    #:
    #: Eleven characters, the same as a YouTube video identifier --
    #: `youtu.be/dQw4w9WgXcQ`. Their alphabet has 64 symbols and ours
    #: 62, so the two are within half a bit of each other: 66.0 against
    #: 65.5. Nobody has ever found a YouTube link too long to paste.
    #:
    #: Raised 7 -> 9 -> 11 on 2026-08-22. The number that justifies it
    #: is not the collision rate -- the retry loop absorbs those, and it
    #: was never the constraint -- but the hit rate of a blind probe,
    #: `stored_links / 62**length`. With a million links stored:
    #:
    #:     length  7: one hit per 3.5 million probes   (a scraper's afternoon)
    #:     length  9: one hit per 13 billion probes
    #:     length 11: one hit per 52 TRILLION probes
    #:
    #: Existing shorter codes keep working: length applies to codes
    #: being MINTED, and every legal code is resolvable whatever its
    #: length -- the 2016 corpus starts at one character.
    code_length: int = 11
    #: How many times a collision is retried before giving up.
    code_max_attempts: int = 8
    #: Longest accepted target URL.
    max_url_length: int = 2048
    #: Longest accepted REQUEST BODY, in bytes.
    #:
    #: EXTERNAL AUDIT 2026-08-22, finding C-04. `max_url_length` caps
    #: the URL at 2 KiB; nothing capped the envelope it arrives in.
    #: Waitress defaults `max_request_body_size` to 1 GiB, inside a
    #: container declared `mem_limit: 512m` -- on paper the application
    #: accepted a body twice the size of the memory it runs in.
    #:
    #: ONE number drives three places, so they cannot drift: this
    #: setting, `[server:main] max_request_body_size` (the same
    #: environment variable feeds both, see
    #: `docker/apply_server_overrides.py`), and `client_max_body_size`
    #: in the nginx recipe. `tests/test_body_limits.py` checks that the
    #: default here and the value in `production.ini` are equal.
    #:
    #: 0 disables the application-level check; the server's own limit
    #: still applies.
    max_body_bytes: int = 16384
    #: Scheme prepended when the submitted URL has none (2016 behaviour).
    default_scheme: str = "http"
    #: Accepted schemes. Anything else (javascript:, data:, file:...) is
    #: refused -- the 2016 code accepted them and happily redirected.
    allowed_schemes: tuple = ("http", "https")
    #: Refuse targets pointing at loopback / private / link-local
    #: addresses, so the shortener cannot be used to dress up an
    #: internal address as a public link.
    block_private_targets: bool = True
    #: Hostnames (and their subdomains) always refused.
    blocked_hosts: tuple = ()
    #: Count redirects. One UPDATE per hit; turn off for a read-only DB.
    count_hits: bool = True
    #: Serve `GET /?url=...`, the 2016 entry point that CREATES a link.
    #:
    #: EXTERNAL AUDIT 2026-08-22, finding C-09. Three things were wrong
    #: with it:
    #:
    #: 1. a GET that writes. Browser prefetch, crawlers, scanners and a
    #:    plain `<img src="...">` on any third-party page all create
    #:    links, at the visitor's address rather than the author's,
    #:    which also spreads the rate limit across strangers;
    #: 2. the target lands in a QUERY STRING, so it is written to the
    #:    nginx access log, the browser history, and whatever
    #:    monitoring reads either. `POST /api/v1/shorten` puts it in a
    #:    body, which none of those record;
    #: 3. no CORS preflight stands between a third-party page and it.
    #:
    #: Train 0024 (audit N-05) closed what can close while the endpoint
    #: lives: the D-02 guard now refuses a browser-borne cross-site
    #: call, so 3 -- and the third-party half of 1 -- are gone in every
    #: current browser, while a server-side caller sends no
    #: Sec-Fetch-Site and is untouched. What remains is structural: a
    #: GET with a side effect for non-browser clients, and 2 entirely.
    #:
    #: Default TRUE all the same: KuneAgi calls it, and this project's
    #: first promise is that nothing written against the 2016 service
    #: breaks. Turning it off is a decision with a date, taken once the
    #: callers have moved -- which is what the log line and the
    #: `Deprecation` header exist to make measurable.
    enable_legacy_get: bool = True
    #: Creations allowed per client address and per window.
    throttle_max_creations: int = 30
    throttle_window_seconds: int = 300
    #: Reads of `/api/v1/links/{code}` allowed per address and window.
    #: 0 = unlimited, which is the default: the endpoint is public and
    #: read-only. Raise it above 0 to slow bulk enumeration of the
    #: SHORT legacy codes (audit 2026-08-22, S-02). The redirect itself
    #: is never limited -- that is the service's whole function.
    throttle_max_reads: int = 0
    #: Send `Access-Control-Allow-Origin` on the JSON endpoints. The 2016
    #: service allowed '*' unconditionally; here it is an explicit list,
    #: '*' still being expressible.
    cors_origins: tuple = ()

    @classmethod
    def from_settings(cls, settings: dict) -> "AppSettings":
        def get(key, env, default=None):
            env_value = os.environ.get(env)
            if env_value is not None and env_value != "":
                return env_value
            return settings.get("urlshortener." + key, default)

        base_url = str(get("base_url", "URLSHORTENER_BASE_URL", cls.base_url))
        if not base_url.endswith("/"):
            base_url += "/"
        default_scheme = str(
            get("default_scheme", "URLSHORTENER_DEFAULT_SCHEME", cls.default_scheme)
        ).strip().lower().rstrip(":/")
        allowed = tuple(
            s.lower().rstrip(":/")
            for s in as_list(get("allowed_schemes", "URLSHORTENER_ALLOWED_SCHEMES"))
        ) or cls.allowed_schemes
        return cls(
            base_url=base_url,
            code_length=as_int(
                get("code_length", "URLSHORTENER_CODE_LENGTH"), cls.code_length
            ),
            code_max_attempts=as_int(
                get("code_max_attempts", "URLSHORTENER_CODE_MAX_ATTEMPTS"),
                cls.code_max_attempts,
            ),
            max_url_length=as_int(
                get("max_url_length", "URLSHORTENER_MAX_URL_LENGTH"), cls.max_url_length
            ),
            max_body_bytes=as_int(
                get("max_body_bytes", "URLSHORTENER_MAX_BODY_BYTES"), cls.max_body_bytes
            ),
            default_scheme=default_scheme or cls.default_scheme,
            allowed_schemes=allowed,
            block_private_targets=as_bool(
                get("block_private_targets", "URLSHORTENER_BLOCK_PRIVATE_TARGETS"),
                cls.block_private_targets,
            ),
            blocked_hosts=tuple(
                h.lower()
                for h in as_list(get("blocked_hosts", "URLSHORTENER_BLOCKED_HOSTS"))
            ),
            count_hits=as_bool(
                get("count_hits", "URLSHORTENER_COUNT_HITS"), cls.count_hits
            ),
            enable_legacy_get=as_bool(
                get("enable_legacy_get", "URLSHORTENER_ENABLE_LEGACY_GET"),
                cls.enable_legacy_get,
            ),
            throttle_max_creations=as_int(
                get("throttle_max_creations", "URLSHORTENER_THROTTLE_MAX"),
                cls.throttle_max_creations,
            ),
            throttle_window_seconds=as_int(
                get("throttle_window_seconds", "URLSHORTENER_THROTTLE_WINDOW"),
                cls.throttle_window_seconds,
            ),
            throttle_max_reads=as_int(
                get("throttle_max_reads", "URLSHORTENER_THROTTLE_MAX_READS"),
                cls.throttle_max_reads,
            ),
            cors_origins=tuple(
                as_list(get("cors_origins", "URLSHORTENER_CORS_ORIGINS"))
            ),
        )

    def validate(self):
        """Raise `ConfigurationError` when this configuration cannot work.

        Every problem is collected before raising: an operator fixing a
        deployment file should see the whole list, not discover the
        second mistake after restarting for the first.

        Called from `main()`, deliberately NOT from `__post_init__`: a
        test building an odd settings object on purpose must stay free
        to do so.
        """
        problems = []

        if not self.base_url.endswith("/"):
            problems.append("base_url must end with '/' (got %r)" % self.base_url)
        base = urlsplit(self.base_url)
        if base.scheme not in ("http", "https") or not base.netloc:
            problems.append(
                "base_url must be an absolute http(s) URL — it is printed into "
                "every link handed out (got %r)" % self.base_url
            )

        if not MIN_CODE_LENGTH <= self.code_length <= MAX_CODE_LENGTH:
            problems.append(
                "code_length must be between %d and %d (got %d)"
                % (MIN_CODE_LENGTH, MAX_CODE_LENGTH, self.code_length)
            )
        if self.code_max_attempts < 1:
            problems.append(
                "code_max_attempts must be at least 1 (got %d)" % self.code_max_attempts
            )

        if self.max_url_length < 32:
            problems.append(
                "max_url_length must be at least 32 (got %d)" % self.max_url_length
            )
        if self.max_body_bytes < 0:
            problems.append("max_body_bytes cannot be negative (got %d)" % self.max_body_bytes)
        elif 0 < self.max_body_bytes < self.max_url_length + BODY_OVERHEAD:
            # A cross-check, not a bound: with these two numbers a URL
            # of the maximum allowed length can never be submitted,
            # because its envelope is refused first. Two settings that
            # are each valid and jointly impossible.
            problems.append(
                "max_body_bytes (%d) is smaller than max_url_length (%d) plus the "
                "envelope: a URL of the allowed length could never be submitted"
                % (self.max_body_bytes, self.max_url_length)
            )

        if not self.allowed_schemes:
            problems.append("allowed_schemes cannot be empty")
        dangerous = sorted(set(self.allowed_schemes) & DANGEROUS_SCHEMES)
        if dangerous:
            problems.append(
                "allowed_schemes must not contain %s: a Location: header carrying "
                "one of those turns this service into the attack"
                % ", ".join(dangerous)
            )
        if self.default_scheme not in self.allowed_schemes:
            problems.append(
                "default_scheme %r is not in allowed_schemes %r — a URL submitted "
                "without a scheme could never be accepted"
                % (self.default_scheme, list(self.allowed_schemes))
            )

        if self.throttle_max_creations > 0 and self.throttle_window_seconds < 1:
            problems.append(
                "throttle_window_seconds must be at least 1 when throttling is on "
                "(got %d)" % self.throttle_window_seconds
            )
        if self.throttle_max_reads > 0 and self.throttle_window_seconds < 1:
            problems.append(
                "throttle_window_seconds must be at least 1 when read throttling is "
                "on (got %d)" % self.throttle_window_seconds
            )

        for origin in self.cors_origins:
            if origin == "*":
                continue
            parts = urlsplit(origin)
            if parts.scheme not in ("http", "https") or not parts.netloc or parts.path:
                problems.append(
                    "cors_origins entry %r is not an origin: a browser sends "
                    "scheme://host[:port], with no path and no trailing slash" % origin
                )

        if problems:
            raise ConfigurationError(
                "refusing to start, %d problem(s) in the configuration:\n  - %s"
                % (len(problems), "\n  - ".join(problems))
            )
        return self

    def short_url(self, code: str) -> str:
        """Public URL of a code -- the 2016 `host + encoded_string`."""
        return self.base_url + code
