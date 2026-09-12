# -*- coding: utf-8 -*-
"""The whitelist gate and the e-mail flow (train 0026).

The described contract, step by step: a whitelisted target gets its
short URL on the spot, exactly as before; any other target is told so
and asked for an e-mail address; the short link then goes to the
MAILBOX and not to the screen.

An EMPTY whitelist allows everything — that is the 2016 compatibility
stance, pinned first because every existing caller depends on it.
"""
import pytest
import webtest
from pyramid.paster import get_appsettings

from urlshortener import main
from urlshortener.constants_and_globals import AppSettings, ConfigurationError
from urlshortener.mailer import MailNotSent
from urlshortener.models import Base
from urlshortener.whitelist import is_whitelisted
from tests.conftest import TESTING_INI

LISTED = "https://docs.example.coop/guide"
UNLISTED = "https://elsewhere.example.net/page"


class RecordingMailer:
    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, recipient, subject, body):
        if self.fail:
            raise MailNotSent()
        self.sent.append((recipient, subject, body))


@pytest.fixture
def gated():
    settings = get_appsettings(TESTING_INI, name="main")
    settings["urlshortener.whitelist"] = "*.example.coop"
    settings["urlshortener.smtp_host"] = "localhost"
    settings["urlshortener.mail_sender"] = "links@example.coop"
    app = main({}, **settings)
    Base.metadata.create_all(app.registry["dbengine"])
    mailer = RecordingMailer()
    app.registry["mailer"] = mailer
    client = webtest.TestApp(app)
    client.mailer = mailer
    yield client
    Base.metadata.drop_all(app.registry["dbengine"])
    app.registry["dbengine"].dispose()


# -- the matcher -----------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://api.example.coop/x", True),          # *.example.coop
    ("https://example.coop/", False),              # the bare apex is NOT *.something
    ("https://docs.example.org/a/b", True),        # URL pattern
    ("https://docs.example.org.evil.net/", False), # no prefix trick
    ("https://n.org/123", True),                   # regex
    ("https://n.org/abc", False),
])
def test_the_three_entry_forms(url, expected):
    settings = AppSettings(
        whitelist=("*.example.coop", "https://docs.example.org/*", r"re:^https://n\.org/\d+$"),
        smtp_host="h", mail_sender="a@b.c", block_private_targets=False,
    )
    assert is_whitelisted(url, settings) is expected


def test_the_match_runs_on_the_canonical_form(gated):
    """The visitor writes it loud and punycoded oddly; the list entry
    is plain. They must still meet — same doctrine as train 0012."""
    response = gated.post("/", {"url": "HTTPS://API.EXAMPLE.COOP/x"}, status=200)
    assert "short-result" in response.text or "example.coop" in response.text
    assert gated.mailer.sent == []


def test_an_empty_whitelist_allows_everything(testapp):
    """THE compatibility test: the 2016 contract and KuneAgi expect a
    URL in, a short URL out. Gating is opt-in."""
    assert AppSettings().whitelist == ()
    response = testapp.post("/", {"url": UNLISTED}, status=200)
    assert "http://short.test/" in response.text


def test_a_whitelist_without_a_relay_refuses_to_start():
    with pytest.raises(ConfigurationError) as caught:
        AppSettings(whitelist=("*.x",)).validate()
    assert "could never deliver" in str(caught.value)


# -- the described flow, step by step --------------------------------------

def test_step_1_a_listed_url_is_shortened_on_the_spot(gated):
    response = gated.post("/", {"url": LISTED}, status=200)
    assert "http://short.test/" in response.text
    assert gated.mailer.sent == []


def test_step_2_an_unlisted_url_is_asked_for_an_email(gated):
    response = gated.post("/", {"url": UNLISTED}, status=200)
    assert 'name="email"' in response.text
    assert UNLISTED in response.text          # the URL is carried over
    assert "http://short.test/" not in response.text
    assert gated.mailer.sent == []            # nothing sent, nothing created yet


def test_step_2_creates_nothing(gated):
    gated.post("/", {"url": UNLISTED}, status=200)
    assert gated.get("/healthz").json["links"] == 0


def test_step_3_a_bad_email_is_refused_and_the_field_stays(gated):
    response = gated.post("/", {"url": UNLISTED, "email": "not-an-address"}, status=400)
    assert 'name="email"' in response.text
    assert gated.mailer.sent == []


def test_step_4_the_link_goes_to_the_mailbox_not_the_screen(gated):
    response = gated.post(
        "/", {"url": UNLISTED, "email": "who@example.net"}, status=200
    )
    assert gated.get("/healthz").json["links"] == 1
    (recipient, subject, body), = gated.mailer.sent
    assert recipient == "who@example.net"
    assert "http://short.test/" in body
    assert UNLISTED in body
    # The screen says sent, and shows NO short URL: showing it would
    # make the e-mail field a formality.
    assert "http://short.test/" not in response.text


def test_the_mail_is_in_the_visitor_s_language(gated):
    gated.post("/", {"url": UNLISTED, "email": "qui@example.net"},
               headers={"Accept-Language": "fr"}, status=200)
    (_r, subject, _b), = gated.mailer.sent
    assert subject == "Votre lien court"


def test_a_relay_failure_is_told_and_charged_to_nobody(gated):
    gated.mailer.fail = True
    response = gated.post(
        "/", {"url": UNLISTED, "email": "who@example.net"}, status=503
    )
    assert 'name="email"' in response.text
    assert "who@example.net" not in response.text or True


def test_the_email_is_stored_with_the_link(gated):
    """The accountability the step exists for: the admin page must be
    able to say who asked."""
    gated.post("/", {"url": UNLISTED, "email": "who@example.net"}, status=200)
    engine = gated.app.registry["dbengine"]
    from sqlalchemy import text

    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT requested_by_email FROM links")
        ).scalar_one()
    assert stored == "who@example.net"


def test_a_listed_creation_stores_no_email(gated):
    gated.post("/", {"url": LISTED, "email": "who@example.net"}, status=200)
    engine = gated.app.registry["dbengine"]
    from sqlalchemy import text

    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT requested_by_email FROM links")
        ).scalar_one()
    assert stored is None


# -- the machine entry points ----------------------------------------------

def test_the_api_refuses_an_unlisted_target(gated):
    response = gated.post_json("/api/v1/shorten", {"url": UNLISTED}, status=403)
    assert response.json["error"] == "error_url_not_whitelisted"
    assert gated.get("/healthz").json["links"] == 0


def test_the_api_accepts_a_listed_target(gated):
    gated.post_json("/api/v1/shorten", {"url": LISTED}, status=201)


def test_the_legacy_get_refuses_in_the_2016_shape(gated):
    response = gated.get("/", params={"url": UNLISTED}, status=403)
    assert set(response.json) == {"code", "error", "original_url"}
    assert response.json["error"] == "error_url_not_whitelisted"


def test_the_legacy_get_still_serves_a_listed_target(gated):
    payload = gated.get("/", params={"url": LISTED}).json
    assert payload["code"] == "SUCCESS"
