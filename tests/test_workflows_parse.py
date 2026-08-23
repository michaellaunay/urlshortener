# -*- coding: utf-8 -*-
"""Every workflow file must be YAML a parser accepts (audit N-01).

The Smoke workflow shipped in the very first commit with a plain
scalar containing ``: `` -- ``grep -q '"status": "ok"'`` -- which YAML
reads as a mapping indicator. GitHub refused the file, so the one gate
written to validate the DEPLOYMENT never ran once, while its two
siblings went green beside it. Same shape as D-05: a gate that exists
and never closes fails nothing and protects nothing.

PyYAML is already in the test lock (brought in by D-05 for the compose
file), so this costs nothing new.
"""
import glob
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOWS = sorted(
    glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))
    + glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yaml"))
)


def test_there_are_workflows_to_check():
    """An empty glob would make the test below pass by silence."""
    assert WORKFLOWS, "no workflow files found under .github/workflows/"


@pytest.mark.parametrize(
    "path", WORKFLOWS, ids=[os.path.basename(p) for p in WORKFLOWS]
)
def test_workflow_is_valid_yaml_with_jobs(path):
    yaml = pytest.importorskip("yaml")
    with open(path, encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    assert isinstance(document, dict), "%s is not a YAML mapping" % path
    assert document.get("jobs"), "%s declares no jobs" % path
