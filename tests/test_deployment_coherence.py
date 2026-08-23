# -*- coding: utf-8 -*-
"""The deployment files must agree with each other (train 0019).

External audit, third pass. Three findings, one shape: a setting that
is documented, and a deployment file that does not carry it. Nothing
fails at build time; the operator simply gets a different service from
the one they configured, or none at all.
"""
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNIT = os.path.join(ROOT, "deploy", "systemd", "urlshortener.service")
UNIT_ENV = os.path.join(ROOT, "deploy", "systemd", "urlshortener.env.example")


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


def _directive(body, name):
    match = re.search(r"^%s=(.*)$" % re.escape(name), body, re.MULTILINE)
    return match.group(1).strip() if match else None


def _settings_variables():
    source = _read(ROOT, "urlshortener", "constants_and_globals.py")
    return sorted(set(re.findall(r'"(URLSHORTENER_[A-Z_]+)"', source)))


# -- E-01 -- the database must land where the unit can write -------------

def test_e01_the_database_path_is_absolute_in_the_unit_environment():
    """`production.ini` says `sqlite:///%(here)s/var/...`, and
    `%(here)s` is the directory of the .ini FILE — etc/ — so the
    database would land in etc/var/, which ProtectSystem=strict makes
    read-only. ExecStartPre dies there."""
    url = _directive(_read(UNIT_ENV), "SQLALCHEMY_URL")
    assert url, "the environment example sets no database URL"
    assert "%(here)s" not in url
    path = url.split("sqlite:///", 1)[-1]
    assert path.startswith("/"), "a relative path resolves against etc/, not var/"


def test_e01_the_database_sits_under_a_writable_path():
    writable = _directive(_read(UNIT), "ReadWritePaths")
    url = _directive(_read(UNIT_ENV), "SQLALCHEMY_URL")
    path = url.split("sqlite:///", 1)[-1]
    assert path.startswith(writable.rstrip("/") + "/"), (
        "%s is not under ReadWritePaths=%s — the unit cannot write there"
        % (path, writable)
    )


# -- E-02 -- the environment must actually be read -----------------------

def test_e02_the_unit_reads_an_environment_file():
    """`find_dotenv` walks UP from the working directory; it never
    descends into `etc/`, so the `.env` the documentation places there
    was never loaded at all."""
    assert _directive(_read(UNIT), "EnvironmentFile"), (
        "no EnvironmentFile: the configuration depends on the current "
        "directory, which is how the documented .env went unread"
    )


def test_e02_the_environment_file_that_is_read_is_the_one_shipped():
    referenced = os.path.basename(_directive(_read(UNIT), "EnvironmentFile"))
    assert os.path.basename(UNIT_ENV) == referenced + ".example"


def test_e02_the_working_directory_is_the_application_directory():
    assert _directive(_read(UNIT), "WorkingDirectory").endswith("/app")


def test_e02_the_unit_upgrades_the_schema_before_serving():
    body = _read(UNIT)
    assert body.index("ExecStartPre") < body.index("ExecStart=")
    assert "urlshortener.upgrades" in _directive(body, "ExecStartPre")


def test_e02_the_unit_and_its_example_use_the_same_ini():
    body = _read(UNIT)
    pre = _directive(body, "ExecStartPre").split()[-1]
    start = _directive(body, "ExecStart").split()[-1]
    assert pre == start, "the upgrade and the server read different files"


# -- E-04 -- Compose must carry every setting it claims to ---------------

@pytest.mark.parametrize("where", ["docker/docker-compose.yaml", ".env.example"])
def test_e04_every_documented_setting_is_forwarded(where):
    """A setting the documentation calls overridable and that no
    deployment file carries is a setting the operator believes in and
    that never arrives. `COUNT_HITS` is the one that mattered: the
    documented mitigation for the write-per-redirect load could not be
    turned off in a container."""
    body = _read(ROOT, *where.split("/"))
    missing = [name for name in _settings_variables() if name not in body]
    assert not missing, "documented but absent from %s: %s" % (where, missing)


def test_e04_the_compose_file_still_parses():
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(_read(ROOT, "docker", "docker-compose.yaml"))
    assert document["services"]["urlshortener"]["environment"]


# -- E-03 -- one version, one source -------------------------------------

def test_e03_the_version_has_a_single_source():
    """It was a hard-coded string beside pyproject.toml, and they
    drifted twice — the package said 2.0.17 while the log announced
    2.0.16."""
    source = _read(ROOT, "urlshortener", "__init__.py")
    assert not re.search(r'^__version__ = "\d', source, re.MULTILINE), (
        "__version__ is hard-coded again"
    )
    assert "importlib.metadata" in source


def test_e03_the_installed_version_matches_pyproject():
    """They agree in CI, which installs the package immediately before
    running this. Locally after a version bump, reinstall."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as distribution_version

    declared = re.search(
        r'^version = "([^"]+)"', _read(ROOT, "pyproject.toml"), re.MULTILINE
    ).group(1)
    try:
        installed = distribution_version("urlshortener")
    except PackageNotFoundError:
        pytest.skip("urlshortener is not installed in this environment")
    assert installed == declared, (
        "pyproject says %s, the installed distribution says %s — run "
        "`pip install --no-deps -e .`" % (declared, installed)
    )


# -- N-02 -- the unit's environment carries only what its path reads -----
#
# External audit (Claude, 2026-08-23), finding N-02 — train 0022.

def _bare_metal_read_variables():
    """Environment variables SOMETHING on the systemd path reads: the
    settings module, plus what the app factory itself consumes.
    `docker/apply_server_overrides.py` is deliberately absent from
    this computation — it runs in the container, never under systemd.
    """
    names = set(_settings_variables())
    source = _read(ROOT, "urlshortener", "__init__.py")
    names |= set(re.findall(r'"(SQLALCHEMY_URL|URLSHORTENER_[A-Z_]+)"', source))
    return names


def test_n02_the_unit_environment_only_carries_what_the_unit_reads():
    """`URLSHORTENER_LISTEN` and the two trusted-proxy variables map
    onto `[server:main]`, and the only code performing that mapping
    runs in the container: under systemd, `pserve` reads the section
    straight from `production.ini`. A variable declared here that
    nothing on this path reads is a setting the operator believes in
    and that never arrives — the C-07/E-04 shape, in its third home,
    invisible out of the box because the shipped values coincided with
    the .ini's own."""
    declared = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", _read(UNIT_ENV), re.MULTILINE))
    inert = sorted(declared - _bare_metal_read_variables())
    assert not inert, (
        "declared in %s but read by nothing on the systemd path: %s"
        % (os.path.basename(UNIT_ENV), inert)
    )
