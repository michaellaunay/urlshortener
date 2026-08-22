# -*- coding: utf-8 -*-
"""Shared fixtures.

Two levels are available on purpose:

* `dbsession` — the domain layer with no HTTP at all, so a rule like
  "the same URL always returns the same code" is tested where it lives;
* `testapp` — the real WSGI application built from `testing.ini`
  through the real `main()`, so route order, renderers, headers and the
  locale negotiator are exercised as deployed.
"""
from __future__ import annotations

import os

import pytest
import transaction
import webtest
from pyramid.paster import get_appsettings
from pyramid.testing import DummyRequest, setUp, tearDown

from urlshortener import main
from urlshortener.constants_and_globals import AppSettings
from urlshortener.models import Base, get_engine, get_session_factory, get_tm_session
from urlshortener.throttle import RateLimiter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
TESTING_INI = os.path.join(REPO_ROOT, "testing.ini")


@pytest.fixture(scope="session")
def ini_settings():
    return get_appsettings(TESTING_INI, name="main")


@pytest.fixture
def app_settings(ini_settings):
    return AppSettings.from_settings(dict(ini_settings))


@pytest.fixture
def engine():
    # A file-backed in-memory database would be recreated per connection;
    # a StaticPool-less `sqlite://` is fine here because the session
    # factory below holds one connection for the whole test.
    engine = get_engine({"sqlalchemy.url": "sqlite://"})
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def dbsession(engine):
    session_factory = get_session_factory(engine)
    manager = transaction.TransactionManager(explicit=True)
    manager.begin()
    session = get_tm_session(session_factory, manager)
    yield session
    manager.abort()
    session.close()


@pytest.fixture
def pyramid_request(dbsession, app_settings):
    """A minimal request carrying what the views actually read."""
    config = setUp(settings={"pyramid.default_locale_name": "en"})
    config.include("urlshortener.routes")
    request = DummyRequest()
    request.dbsession = dbsession
    request.app_settings = app_settings
    request.throttle = RateLimiter(0, 60)
    yield request
    tearDown()


@pytest.fixture
def testapp():
    """The real application, on a database that lives for one test."""
    settings = get_appsettings(TESTING_INI, name="main")
    app = main({}, **settings)
    engine = app.registry["dbengine"]
    Base.metadata.create_all(engine)
    yield webtest.TestApp(app)
    Base.metadata.drop_all(engine)
    engine.dispose()
