# -*- coding: utf-8 -*-
"""Creations arriving from another site (train 0013).

External audit, second pass, finding D-02. A `POST` in
`application/x-www-form-urlencoded` is a CORS-SIMPLE request: a browser
sends it with no preflight, and shows the answer to nobody. So any
third-party page could make its visitors create links — at THEIR
address, which also spreads the rate limit across strangers — and the
preflight added in train 0009 stood in front of none of it, because a
form never preflights.

There is no session, so there is no CSRF token. `Sec-Fetch-Site` is the
sessionless answer: the browser states where the request came from, and
a page can neither remove it nor choose its value.
"""
import pytest

from urlshortener.views import ALLOWED_FETCH_SITES, cross_site_creation


class _Request:
    def __init__(self, headers=None):
        self.headers = headers or {}


# -- the header itself ----------------------------------------------------

@pytest.mark.parametrize("site", sorted(ALLOWED_FETCH_SITES))
def test_d02_a_legitimate_origin_passes(site):
    assert cross_site_creation(_Request({"Sec-Fetch-Site": site})) is False


@pytest.mark.parametrize("site", ["cross-site", "CROSS-SITE", " cross-site ", "nonsense"])
def test_d02_anything_else_is_refused(site):
    assert cross_site_creation(_Request({"Sec-Fetch-Site": site})) is True


def test_d02_an_absent_header_fails_open():
    """curl, an old browser and every non-browser client send nothing.
    Refusing them would break far more than it protects, and the attack
    lives in current browsers — which always send it."""
    assert cross_site_creation(_Request()) is False
    assert cross_site_creation(_Request({"Sec-Fetch-Site": ""})) is False


def test_d02_same_site_is_allowed_on_purpose():
    """The service is mounted under a coop's domain; a sibling host of
    the same registrable domain is a legitimate caller."""
    assert "same-site" in ALLOWED_FETCH_SITES


# -- the form -------------------------------------------------------------

def test_d02_the_form_refuses_a_cross_site_post(testapp):
    response = testapp.post(
        "/", {"url": "https://example.org/a"},
        headers={"Sec-Fetch-Site": "cross-site"}, status=403,
    )
    assert "another website" in response.text


def test_d02_the_refusal_is_translated(testapp):
    response = testapp.post(
        "/", {"url": "https://example.org/b"},
        headers={"Sec-Fetch-Site": "cross-site", "Accept-Language": "fr"},
        status=403,
    )
    assert "depuis un autre site" in response.text


def test_d02_nothing_is_created_by_a_refused_post(testapp):
    testapp.post("/", {"url": "https://example.org/c"},
                 headers={"Sec-Fetch-Site": "cross-site"}, status=403)
    assert testapp.get("/healthz").json["links"] == 0


def test_d02_our_own_form_still_works(testapp):
    testapp.post("/", {"url": "https://example.org/d"},
                 headers={"Sec-Fetch-Site": "same-origin"}, status=200)
    assert testapp.get("/healthz").json["links"] == 1


def test_d02_the_refusal_costs_no_rate_limit_slot(testapp):
    """Refusing must come before the throttle, or a third-party page
    could still exhaust a visitor's budget without creating anything."""
    from urlshortener import views

    calls = []
    original = views._client_key
    views._client_key = lambda request: calls.append(1) or "x"
    try:
        testapp.post("/", {"url": "https://example.org/e"},
                     headers={"Sec-Fetch-Site": "cross-site"}, status=403)
    finally:
        views._client_key = original
    assert calls == []


# -- the API --------------------------------------------------------------

def test_d02_the_api_refuses_a_form_encoding(testapp):
    """The heart of the finding: this content type needs no preflight,
    so accepting it made the origin list decorative."""
    response = testapp.post(
        "/api/v1/shorten", {"url": "https://example.org/f"}, status=415
    )
    assert response.json["error"] == "error_content_type_required"


@pytest.mark.parametrize("content_type", [
    "application/x-www-form-urlencoded",
    "multipart/form-data; boundary=x",
    "text/plain",
    "",
])
def test_d02_every_cors_simple_content_type_is_refused(testapp, content_type):
    """Those three are exactly the types a browser sends without a
    preflight. All three must be refused, not just the obvious one."""
    testapp.post(
        "/api/v1/shorten", '{"url": "https://example.org/g"}',
        content_type=content_type, status=415,
    )


@pytest.mark.parametrize("content_type", [
    "application/json",
    "application/json; charset=utf-8",
    "APPLICATION/JSON",
    "application/merge-patch+json",
])
def test_d02_json_content_types_are_accepted(testapp, content_type):
    testapp.post(
        "/api/v1/shorten", '{"url": "https://example.org/%s"}' % content_type[-4:],
        content_type=content_type, status="*",
    )


def test_d02_the_api_refuses_a_cross_site_call_even_in_json(testapp):
    """A preflight would normally stop it, but a caller that is not a
    browser can send anything; the header check is the second lock."""
    response = testapp.post_json(
        "/api/v1/shorten", {"url": "https://example.org/h"},
        headers={"Sec-Fetch-Site": "cross-site"}, status=403,
    )
    assert response.json["error"] == "error_cross_site"


def test_d02_reads_are_not_affected(testapp):
    """Only creation is guarded. A redirect followed from a third-party
    page is the normal use of a short link."""
    code = testapp.post_json(
        "/api/v1/shorten", {"url": "https://example.org/i"}
    ).json["code"]
    testapp.get("/" + code, headers={"Sec-Fetch-Site": "cross-site"}, status=302)
    testapp.get("/api/v1/links/" + code, headers={"Sec-Fetch-Site": "cross-site"})
    testapp.get("/", headers={"Sec-Fetch-Site": "cross-site"}, status=200)


def test_d02_the_legacy_get_remains_the_wider_hole(testapp):
    """Told plainly rather than left implicit: `GET /?url=` is reachable
    from an `<img>` tag, which no header check can distinguish from a
    legitimate navigation. It is guarded by nothing here, and closing
    it is `enable_legacy_get = false` — a decision with a date, not a
    patch (train 0010)."""
    response = testapp.get(
        "/", params={"url": "https://example.org/j"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.json["code"] == "SUCCESS"
    assert response.headers["Deprecation"] == "true"
