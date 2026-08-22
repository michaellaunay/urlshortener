# -*- coding: utf-8 -*-
"""The rendered pages, including in the four languages."""
import pytest


def test_the_page_is_english_by_default(testapp):
    body = testapp.get("/").text
    assert "Turn a long address into a short one." in body


@pytest.mark.parametrize("language,marker", [
    ("fr", "Transformez une adresse longue"),
    ("de", "Aus einer langen Adresse"),
    ("es", "Convierta una dirección larga"),
])
def test_accept_language_renders_the_translated_page(testapp, language, marker):
    body = testapp.get("/", headers={"Accept-Language": language}).text
    assert marker in body


def test_the_language_switcher_sets_a_cookie_and_comes_back(testapp):
    response = testapp.get("/locale/fr", params={"came_from": "/"}, status=303)
    assert response.headers["Location"].endswith("/")
    assert "_LOCALE_=fr" in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "Transformez une adresse longue" in testapp.get("/").text


def test_the_language_switcher_ignores_an_unoffered_language(testapp):
    response = testapp.get("/locale/it", status=303)
    assert "Set-Cookie" not in response.headers


def test_the_language_switcher_is_not_an_open_redirect(testapp):
    response = testapp.get("/locale/fr", params={"came_from": "https://evil.test/"}, status=303)
    assert "evil.test" not in response.headers["Location"]
    response = testapp.get("/locale/fr", params={"came_from": "//evil.test/"}, status=303)
    assert "evil.test" not in response.headers["Location"]


def test_the_page_shows_the_short_code_after_a_post(testapp):
    response = testapp.post("/", {"url": "https://example.org/shown"})
    assert "result-code" in response.text
    assert "http://short.test/" in response.text


def test_posting_a_known_url_says_so(testapp):
    testapp.post("/", {"url": "https://example.org/twice"})
    response = testapp.post("/", {"url": "https://example.org/twice"})
    assert "already had a short link" in response.text


def test_a_refused_url_shows_a_message_and_keeps_what_was_typed(testapp):
    response = testapp.post("/", {"url": "javascript:alert(1)"}, status=400)
    assert "Only http:// and https://" in response.text
    assert "javascript:alert(1)" in response.text


def test_a_refused_url_is_shown_translated(testapp):
    response = testapp.post(
        "/", {"url": "javascript:alert(1)"},
        headers={"Accept-Language": "fr"}, status=400,
    )
    assert "peuvent être raccourcies" in response.text


def test_the_error_message_is_escaped_not_executed(testapp):
    response = testapp.post("/", {"url": "<script>alert(1)</script>"}, status=400)
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_the_footer_counts_the_stored_links(testapp):
    testapp.post("/", {"url": "https://example.org/one"})
    testapp.post("/", {"url": "https://example.org/two"})
    assert "links stored" in testapp.get("/").text


def test_the_404_page_is_rendered_and_translated(testapp):
    body = testapp.get("/nosuch1", headers={"Accept-Language": "fr"}, status=404).text
    assert "Ce lien court n'existe pas." in body


def test_head_on_a_short_link_works(testapp):
    code = testapp.get("/", params={"url": "https://example.org/head"}).json["short_url"]
    testapp.head("/" + code.rsplit("/", 1)[-1], status=302)


def test_no_external_asset_is_referenced(testapp):
    """2016 pulled Bootstrap and Font Awesome from maxcdn on every view,
    which told a third party who was reading which page."""
    body = testapp.get("/").text
    for marker in ("maxcdn", "cdn.", "//fonts.", "googleapis"):
        assert marker not in body
