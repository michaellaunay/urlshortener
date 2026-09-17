# -*- coding: utf-8 -*-
"""Regression tests for the 2026-09-17 /hello.world and POST / tracebacks.

Use real Pyramid/WebOb requests: dict-only doubles cannot expose the
lazy decoding failure which caused the incident.
"""
import pytest
from pyramid.request import Request
from pyramid.response import Response

from urlshortener.constants_and_globals import DEFAULT_LOCALE
from urlshortener.locale_negotiation import negotiate
from urlshortener.request_validation import utf8_query_tween_factory


INVALID_QUERIES = (
    "%AD=test",              # The invalid name byte in the production trace.
    "x=%AD",                 # Invalid values must be rejected as well.
    "_LOCALE_=%FF",           # Invalid explicit language.
    "good=ok&%C3=x",          # Truncated multi-byte sequence in a name.
    "_LOCALE_=fr&x=%80",      # A valid locale does not sanitize other fields.
)


@pytest.mark.parametrize("query", INVALID_QUERIES)
def test_invalid_query_is_rejected_before_the_handler(query):
    request = Request.blank("/?" + query)

    # Prove the fixture actually exercises WebOb's strict decoder.
    with pytest.raises(UnicodeDecodeError):
        _ = request.GET

    def forbidden_handler(request):
        pytest.fail("A malformed query reached the application handler")

    response = utf8_query_tween_factory(forbidden_handler, None)(request)
    assert response.status_int == 400
    assert response.content_type == "text/plain"
    assert response.charset == "UTF-8"
    assert response.headers["Content-Type"] == "text/plain; charset=UTF-8"
    # Check before reading .text/.body: WebOb may repair a missing length
    # when the body is consumed, hiding the original response defect.
    assert response.content_length == len(b"Invalid UTF-8 in query string.\n")
    assert response.text == "Invalid UTF-8 in query string.\n"
    assert response.headers["Cache-Control"] == "no-store"


def test_valid_unicode_and_literal_percent_sequences_are_not_rewritten():
    query = "caf%C3%A9=th%C3%A9&literal=%25AD&_LOCALE_=fr"
    request = Request.blank("/?" + query)
    expected = Response(text="ok")

    def handler(received):
        assert received is request
        assert received.GET["café"] == "thé"
        assert received.GET["literal"] == "%AD"
        assert received.query_string == query
        return expected

    assert utf8_query_tween_factory(handler, None)(request) is expected


def test_handler_decoding_errors_are_not_misclassified_as_client_errors():
    def broken_handler(request):
        return b"\xad".decode("utf-8")

    with pytest.raises(UnicodeDecodeError):
        utf8_query_tween_factory(broken_handler, None)(Request.blank("/"))


class QueryOnlyRequest(Request):
    @property
    def POST(self):
        raise AssertionError("Locale selection/query validation must not parse POST")

    @property
    def params(self):
        raise AssertionError("Locale selection/query validation must not read params")


def test_query_validation_does_not_parse_a_form_body():
    request = QueryOnlyRequest.blank(
        "/?ok=yes", method="POST", body=b"bad=%AD",
        content_type="application/x-www-form-urlencoded",
    )
    expected = Response(text="ok")
    assert utf8_query_tween_factory(lambda request: expected, None)(request) is expected


def test_locale_ignores_form_fields_and_does_not_parse_a_form_body():
    request = QueryOnlyRequest.blank(
        "/", method="POST", body=b"_LOCALE_=de&bad=%AD",
        content_type="application/x-www-form-urlencoded",
        headers={"Accept-Language": "fr"},
    )
    assert negotiate(request) == "fr"


def test_query_locale_still_wins_on_post_without_reading_the_body():
    request = QueryOnlyRequest.blank(
        "/?_LOCALE_=de", method="POST", body=b"bad=%AD",
        content_type="application/x-www-form-urlencoded",
        headers={"Cookie": "_LOCALE_=es", "Accept-Language": "fr"},
    )
    assert negotiate(request) == "de"


@pytest.mark.parametrize("headers,expected", [
    ({"Cookie": "_LOCALE_=fr", "Accept-Language": "de"}, "fr"),
    ({"Accept-Language": "de"}, "de"),
    ({}, DEFAULT_LOCALE),
])
def test_locale_falls_back_when_called_directly_with_an_invalid_query(headers, expected):
    request = Request.blank("/?%AD=x", headers=headers)
    assert negotiate(request) == expected


@pytest.mark.parametrize("path", ["/", "/hello.world"])
@pytest.mark.parametrize("query", INVALID_QUERIES)
@pytest.mark.parametrize("method", ["get", "post"])
def test_real_application_rejects_invalid_queries(testapp, path, query, method):
    response = getattr(testapp, method)(path + "?" + query, status=400)
    assert response.content_type == "text/plain"
    assert response.charset == "UTF-8"
    assert response.headers["Content-Type"] == "text/plain; charset=UTF-8"
    # Check before reading .text/.body: WebOb may repair a missing length
    # when the body is consumed, hiding the original response defect.
    assert response.content_length == len(b"Invalid UTF-8 in query string.\n")
    assert response.text == "Invalid UTF-8 in query string.\n"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    # A rejected request must not poison subsequent requests.
    testapp.get("/", status=200)


def test_an_ordinary_unknown_path_remains_a_404(testapp):
    testapp.get("/hello.world", status=404)
    testapp.get("/hello.world?name=caf%C3%A9&_LOCALE_=fr", status=404)


def test_a_cross_site_refusal_does_not_parse_a_malformed_form_for_locale(testapp):
    # The view rejects this before reading POST. Rendering that refusal
    # must not read the rejected body indirectly via request.locale_name.
    testapp.post(
        "/", params="bad=%AD",
        content_type="application/x-www-form-urlencoded",
        headers={"Sec-Fetch-Site": "cross-site"}, status=403,
    )
