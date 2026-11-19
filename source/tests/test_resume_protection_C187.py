"""Refresh source protection before resuming a persisted export slice."""

from pathlib import Path
from typing import Any

import pytest
import test_native_exporter212 as legacy
from native_exporter import NativeExporter
from research_index import IndexFailure
from source_protocol import SourceError


@pytest.fixture
def case():
    fixture = legacy.ExporterTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.doCleanups()


def interrupt(case: Any, *, published: bool) -> None:
    if not published:
        case.exporter.run(max_cases=1)
        return

    def crash() -> None:
        raise legacy.SimulatedCrash()

    with pytest.raises(legacy.SimulatedCrash):
        case.exporter.run(after_publish=crash)


def prepared(case: Any) -> str:
    with case.exporter.db() as db:
        return str(db.execute("SELECT value FROM prepared").fetchone()[0])


def reopen(case: Any, preflight: Any) -> None:
    case.exporter = NativeExporter(
        case.client,
        case.index,
        Path(case.directory) / "scan",
        shared_lock=case.lock,
        clock=lambda: case.now,
        preflight=preflight,
    )


@pytest.mark.parametrize("published", [False, True])
def test_failed_resume_check_keeps_the_original_prepared_work(case, published):
    interrupt(case, published=published)
    original = prepared(case)
    old_scan = case.exporter.state()
    old_index = case.index.state()
    assert old_index["records"] == int(published)
    assert case.bodies == ["a"]

    def refuse(remaining: float) -> None:
        assert remaining > 0
        raise SourceError("Synthetic protection changed before resume")

    reopen(case, refuse)
    with pytest.raises(SourceError, match="Synthetic protection changed before resume"):
        case.exporter.run()
    assert case.bodies == ["a"]
    assert prepared(case) == original
    scan = case.exporter.state()
    assert scan["processed"] == old_scan["processed"] and scan["run"] == old_scan["run"]
    assert scan["error"] == "SourceError"
    fenced = case.index.state()
    assert fenced["generation"] == old_index["generation"]
    assert fenced["cursor"] == old_index["cursor"]
    assert fenced["data_version"] == old_index["data_version"]
    assert not fenced["healthy"] and fenced["protection_unavailable"]
    with pytest.raises(IndexFailure):
        case.index.search(
            "шкаф", expected_version=fenced["version"], current={"cid": "other"}
        )


@pytest.mark.parametrize("published", [False, True])
def test_resume_checks_protection_before_replaying_without_rereading(case, published):
    interrupt(case, published=published)
    events = []

    def verify(remaining: float) -> None:
        assert remaining > 0
        events.append("preflight")

    reopen(case, verify)
    state = case.exporter.run(after_publish=lambda: events.append("publish"))
    assert state["run"] is None and state["indexed"] == 2
    assert events == ["preflight", "publish", "publish"]
    assert case.bodies == ["a", "b"]
    assert case.index.state()["generation"] == 2


def test_idle_poll_does_not_revalidate_before_next_due_pass(case):
    case.finish()

    def unexpected(_: float) -> None:
        pytest.fail("Idle poll must not contact the protection reader")

    reopen(case, unexpected)
    assert case.exporter.run()["not_due"]
