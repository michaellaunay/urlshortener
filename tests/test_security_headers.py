# -*- coding: utf-8 -*-
"""Headers the 2016 service did not send at all."""


def test_html_pages_carry_a_content_security_policy(testapp):
    response = testapp.get("/")
    policy = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in policy
    assert "default-src 'self'" in policy
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_json_answers_are_not_given_an_html_policy(testapp):
    response = testapp.get("/api/v1/links/zzzzzz9", status=404)
    assert "Content-Security-Policy" not in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_redirect_does_not_leak_the_short_link_to_the_target(testapp):
    code = testapp.get("/", params={"url": "https://example.org/x"}).json["short_url"]
    response = testapp.get("/" + code.rsplit("/", 1)[-1], status=302)
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


def test_no_cross_origin_header_by_default(testapp):
    # 2016 sent Access-Control-Allow-Origin: * unconditionally.
    response = testapp.get(
        "/", params={"url": "https://example.org/y"}, headers={"Origin": "https://evil.test"}
    )
    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_is_sent_for_a_configured_origin():
    import webtest
    from pyramid.paster import get_appsettings

    from urlshortener import main
    from urlshortener.models import Base
    from tests.conftest import TESTING_INI

    settings = get_appsettings(TESTING_INI, name="main")
    settings["urlshortener.cors_origins"] = "https://friend.test"
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    client = webtest.TestApp(app)
    try:
        allowed = client.get(
            "/", params={"url": "https://example.org/z"},
            headers={"Origin": "https://friend.test"},
        )
        assert allowed.headers["Access-Control-Allow-Origin"] == "https://friend.test"
        assert allowed.headers["Vary"] == "Origin"

        refused = client.get(
            "/", params={"url": "https://example.org/z2"},
            headers={"Origin": "https://stranger.test"},
        )
        assert "Access-Control-Allow-Origin" not in refused.headers
    finally:
        Base.metadata.drop_all(app.registry["dbengine"])
        app.registry["dbengine"].dispose()
