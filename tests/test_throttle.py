# -*- coding: utf-8 -*-
"""Creation rate limiting."""
from urlshortener.throttle import RateLimiter


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_allows_up_to_the_limit_then_refuses():
    limiter = RateLimiter(3, 60, clock=_Clock())
    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]


def test_each_key_has_its_own_budget():
    limiter = RateLimiter(1, 60, clock=_Clock())
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is False


def test_the_window_slides():
    clock = _Clock()
    limiter = RateLimiter(2, 60, clock=clock)
    assert limiter.allow("a") and limiter.allow("a")
    assert limiter.allow("a") is False
    clock.now += 61
    assert limiter.allow("a") is True


def test_a_limit_of_zero_disables_the_limiter():
    limiter = RateLimiter(0, 60, clock=_Clock())
    assert all(limiter.allow("a") for _ in range(1000))


def test_reset_clears_everything():
    limiter = RateLimiter(1, 60, clock=_Clock())
    limiter.allow("a")
    limiter.reset()
    assert limiter.allow("a") is True


def test_the_creation_endpoints_honour_the_limit():
    import webtest
    from pyramid.paster import get_appsettings

    from urlshortener import main
    from urlshortener.models import Base
    from tests.conftest import TESTING_INI

    settings = get_appsettings(TESTING_INI, name="main")
    settings["urlshortener.throttle_max_creations"] = "2"
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    client = webtest.TestApp(app)
    try:
        client.get("/", params={"url": "https://example.org/1"})
        client.get("/", params={"url": "https://example.org/2"})
        refused = client.get("/", params={"url": "https://example.org/3"}, status=429)
        assert refused.json["code"] == "ERROR"
        # Reading is never throttled: a short link must keep resolving
        # even while someone is hammering the creation endpoint.
        code = client.get("/api/v1/links/zzzzzz9", status=404)
        assert code.status_int == 404
    finally:
        Base.metadata.drop_all(app.registry["dbengine"])
        app.registry["dbengine"].dispose()
