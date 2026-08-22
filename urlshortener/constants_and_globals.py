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
    code_length: int = 7
    #: How many times a collision is retried before giving up.
    code_max_attempts: int = 8
    #: Longest accepted target URL.
    max_url_length: int = 2048
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

    def short_url(self, code: str) -> str:
        """Public URL of a code -- the 2016 `host + encoded_string`."""
        return self.base_url + code
