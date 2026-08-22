# -*- coding: utf-8 -*-
"""The contract with clients written against the 2016 service.

These are the tests to read first when changing anything: every one of
them describes something an existing caller -- KuneAgi's `/urlmetadata/`
mount point included -- may already rely on.
"""


def test_get_with_url_returns_the_2016_json_shape(testapp):
    response = testapp.get("/", params={"url": "https://example.org/page"})
    assert response.status_int == 200
    assert response.content_type == "application/json"
    payload = response.json
    assert set(payload) == {"short_url", "code", "original_url"}
    assert payload["code"] == "SUCCESS"
    assert payload["original_url"] == "https://example.org/page"
    assert payload["short_url"].startswith("http://short.test/")


def test_get_with_url_is_idempotent(testapp):
    first = testapp.get("/", params={"url": "https://example.org/same"}).json
    second = testapp.get("/", params={"url": "https://example.org/same"}).json
    assert first["short_url"] == second["short_url"]


def test_get_without_scheme_is_completed(testapp):
    payload = testapp.get("/", params={"url": "example.org/x"}).json
    assert payload["original_url"] == "http://example.org/x"


def test_get_with_a_refused_url_returns_the_error_shape(testapp):
    response = testapp.get("/", params={"url": "javascript:alert(1)"}, status=400)
    payload = response.json
    assert payload["code"] == "ERROR"
    assert payload["original_url"] == "javascript:alert(1)"
    assert "error" in payload
    # Documented change: 2016 answered 200 with code=ERROR, which no
    # monitor could distinguish from a success.
    assert response.status_int == 400


def test_post_form_returns_the_html_page_with_the_short_link(testapp):
    response = testapp.post("/", {"url": "https://example.org/form"})
    assert response.status_int == 200
    assert response.content_type == "text/html"
    body = response.text
    assert "http://short.test/" in body


def test_redirect_sends_302_to_the_target(testapp):
    code = testapp.get("/", params={"url": "https://example.org/target"}).json["short_url"]
    code = code.rsplit("/", 1)[-1]
    response = testapp.get("/" + code, status=302)
    assert response.headers["Location"] == "https://example.org/target"


def test_unknown_code_answers_404(testapp):
    # Documented change from 2016, which answered 200 with an error page.
    testapp.get("/nosuch1", status=404)


def test_home_page_renders_without_a_url(testapp):
    response = testapp.get("/")
    assert response.status_int == 200
    assert response.content_type == "text/html"
