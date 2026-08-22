# -*- coding: utf-8 -*-
"""Route order and the reserved-code list.

`/{code}` matches almost anything, so it must stay last, and every
top-level path must also be reserved in the codec -- otherwise the day
a draw produces the code `api`, that link is unreachable forever.
"""
from pyramid.config import Configurator

from urlshortener.codec import RESERVED_CODES


def _registered_routes():
    config = Configurator()
    config.include("urlshortener.routes")
    config.commit()
    mapper = config.get_routes_mapper()
    return [(route.name, route.pattern) for route in mapper.get_routes()]


def test_the_catch_all_redirect_is_registered_last():
    routes = _registered_routes()
    names = [name for name, _pattern in routes]
    assert names[-1] == "redirect"
    assert routes[-1][1] == "/{code}"


def test_every_top_level_path_is_a_reserved_code():
    for name, pattern in _registered_routes():
        if name == "redirect":
            continue
        first_segment = pattern.strip("/").split("/", 1)[0]
        if not first_segment or first_segment.startswith("{"):
            continue
        assert first_segment in RESERVED_CODES, (
            "route %r starts with %r, which is not in RESERVED_CODES -- a "
            "drawn code equal to it would be unreachable" % (name, first_segment)
        )


def test_the_static_view_is_reserved_too():
    assert "static" in RESERVED_CODES
