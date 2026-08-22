# -*- coding: utf-8 -*-
"""JSON API v1."""


def test_post_json_creates_and_answers_201(testapp):
    response = testapp.post_json("/api/v1/shorten", {"url": "https://example.org/a"})
    assert response.status_int == 201
    payload = response.json
    assert payload["created"] is True
    assert payload["url"] == "https://example.org/a"
    assert payload["short_url"].endswith(payload["code"])
    assert payload["hits"] == 0
    assert payload["created_at"]


def test_a_known_url_answers_200_and_created_false(testapp):
    testapp.post_json("/api/v1/shorten", {"url": "https://example.org/b"})
    response = testapp.post_json("/api/v1/shorten", {"url": "https://example.org/b"})
    assert response.status_int == 200
    assert response.json["created"] is False


def test_form_encoded_post_is_accepted_too(testapp):
    response = testapp.post("/api/v1/shorten", {"url": "https://example.org/c"})
    assert response.status_int == 201


def test_a_refused_url_answers_400_with_a_stable_identifier(testapp):
    response = testapp.post_json(
        "/api/v1/shorten", {"url": "file:///etc/passwd"}, status=400
    )
    assert response.json["error"] == "error_url_scheme"
    assert response.json["message"]


def test_a_missing_url_answers_400(testapp):
    response = testapp.post_json("/api/v1/shorten", {}, status=400)
    assert response.json["error"] == "error_url_required"


def test_malformed_json_answers_400_rather_than_500(testapp):
    response = testapp.post(
        "/api/v1/shorten", "{not json", content_type="application/json", status=400
    )
    assert response.json["error"] == "error_url_required"


def test_reading_a_link_does_not_count_as_a_visit(testapp):
    code = testapp.post_json("/api/v1/shorten", {"url": "https://example.org/d"}).json["code"]
    testapp.get("/api/v1/links/" + code)
    testapp.get("/api/v1/links/" + code)
    assert testapp.get("/api/v1/links/" + code).json["hits"] == 0
    testapp.get("/" + code, status=302)
    assert testapp.get("/api/v1/links/" + code).json["hits"] == 1


def test_unknown_code_answers_404(testapp):
    response = testapp.get("/api/v1/links/zzzzzz9", status=404)
    assert response.json["error"] == "error_unknown_code"


def test_healthz_reports_the_database(testapp):
    payload = testapp.get("/healthz").json
    assert payload["status"] == "ok"
    assert payload["links"] == 0
