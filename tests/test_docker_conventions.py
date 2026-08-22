# -*- coding: utf-8 -*-
"""Structural locks on the deployment files.

Every assertion here corresponds to a failure that has actually
happened on a sibling project. They are cheap; the incidents were not.
"""
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCKER = os.path.join(ROOT, "docker")

DOCKERFILE = os.path.join(DOCKER, "DockerfileUrlshortener")
COMPOSE = os.path.join(DOCKER, "docker-compose.yaml")
ENTRYPOINT = os.path.join(DOCKER, "start_urlshortener.sh")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_dockerignore_does_not_exclude_the_docker_directory():
    """The exact latent crash AlirPunkto shipped: `.dockerignore` hid
    `docker/`, so the helper the entrypoint calls was never copied and
    the container died on its FIRST start -- long after the build had
    been declared green."""
    ignored = [
        line.strip()
        for line in _read(os.path.join(ROOT, ".dockerignore")).splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert "docker" not in ignored
    assert "docker/" not in ignored


def test_the_helper_the_entrypoint_calls_is_copied_into_the_image():
    called = re.findall(r"docker/(\w+\.py)", _read(ENTRYPOINT))
    assert called, "the entrypoint calls no helper — did it move?"
    dockerfile = _read(DOCKERFILE)
    for helper in set(called):
        assert "docker/%s" % helper in dockerfile, (
            "%s is called at start-up but never COPYed into the image" % helper
        )
        assert os.path.exists(os.path.join(DOCKER, helper))


def test_the_base_image_is_pinned_by_digest():
    for line in _read(DOCKERFILE).splitlines():
        if line.startswith("FROM "):
            assert "@sha256:" in line, "FROM without a digest: %s" % line


def test_the_runtime_lock_is_installed_with_hash_checking():
    dockerfile = _read(DOCKERFILE)
    assert "--require-hashes" in dockerfile
    assert "-r requirements.lock" in dockerfile
    # The test and quality locks must NEVER reach the image.
    assert "requirements-test.lock" not in dockerfile
    assert "requirements-quality.lock" not in dockerfile


def test_the_image_runs_as_a_non_root_user():
    dockerfile = _read(DOCKERFILE)
    assert re.search(r"^USER urlshortener$", dockerfile, re.MULTILINE)
    # ... and USER comes after the last chown, not before it.
    assert dockerfile.index("USER urlshortener") > dockerfile.rindex("chown -R")


def test_the_state_volume_is_declared():
    assert 'VOLUME ["/home/urlshortener/app/var"]' in _read(DOCKERFILE)


def test_the_compose_file_has_no_duplicate_keys():
    """`yaml.safe_load` silently keeps the LAST of two identical keys,
    so "the YAML parses" proves nothing. This walks the raw text."""
    stack = []
    seen = {}
    for number, raw in enumerate(_read(COMPOSE).splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if stripped.startswith("- "):
            # A list item opens a fresh mapping scope.
            seen.pop(indent + 2, None)
            continue
        if ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        for known in list(seen):
            if known > indent:
                del seen[known]
        keys = seen.setdefault(indent, set())
        assert key not in keys, (
            "duplicate key %r at line %d — compose keeps the last one and "
            "the first is silently lost" % (key, number)
        )
        keys.add(key)
        stack.append(key)


def test_the_compose_file_parses_and_declares_the_service():
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(_read(COMPOSE))
    service = document["services"]["urlshortener"]
    assert service["build"]["dockerfile"] == "docker/DockerfileUrlshortener"
    # Context is the repository root: the build installs the package.
    assert service["build"]["context"] == ".."
    assert "urlshortener-var:/home/urlshortener/app/var" in service["volumes"]


def test_the_service_is_published_on_loopback_only():
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(_read(COMPOSE))
    for published in document["services"]["urlshortener"]["ports"]:
        assert str(published).startswith("127.0.0.1:"), (
            "%s exposes the service to the network; the reverse proxy is "
            "what should face it" % published
        )


def test_the_entrypoint_upgrades_the_schema_before_serving():
    body = _read(ENTRYPOINT)
    assert body.index("urlshortener.upgrades") < body.index("pserve"), (
        "the schema must be ready before the first request, not after it"
    )
    assert body.strip().splitlines()[-1].startswith("exec "), (
        "the server must be exec'd so it is PID 1 and receives signals"
    )


def test_the_entrypoint_is_strict():
    assert "set -euo pipefail" in _read(ENTRYPOINT)
