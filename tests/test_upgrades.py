# -*- coding: utf-8 -*-
"""Schema stamp and upgrade steps."""
import pytest

from urlshortener import upgrades


def test_steps_are_contiguous_from_one():
    assert sorted(upgrades.UPGRADE_STEPS) == list(range(1, upgrades.SCHEMA_VERSION + 1))


def test_a_fresh_database_reports_version_zero(dbsession):
    assert upgrades.get_schema_version(dbsession) == 0


def test_running_the_steps_stamps_the_current_version(dbsession):
    assert upgrades.run_pending_upgrades(dbsession) == upgrades.SCHEMA_VERSION
    assert upgrades.get_schema_version(dbsession) == upgrades.SCHEMA_VERSION


def test_running_twice_is_a_no_op(dbsession):
    upgrades.run_pending_upgrades(dbsession)
    calls = []
    original = upgrades.UPGRADE_STEPS[1]
    upgrades.UPGRADE_STEPS[1] = lambda session: calls.append(1)
    try:
        assert upgrades.run_pending_upgrades(dbsession) == upgrades.SCHEMA_VERSION
    finally:
        upgrades.UPGRADE_STEPS[1] = original
    assert calls == []


def test_a_failing_step_does_not_advance_the_stamp(dbsession):
    def boom(session):
        raise RuntimeError("step failed")

    original = upgrades.UPGRADE_STEPS[1]
    upgrades.UPGRADE_STEPS[1] = boom
    try:
        with pytest.raises(RuntimeError):
            upgrades.run_pending_upgrades(dbsession)
    finally:
        upgrades.UPGRADE_STEPS[1] = original
    assert upgrades.get_schema_version(dbsession) == 0
