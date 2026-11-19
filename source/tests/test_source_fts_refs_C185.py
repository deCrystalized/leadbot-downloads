"""Keep FTS row references consistent with legacy writers and failed updates."""

from contextlib import contextmanager

import pytest
import test_research_index206 as legacy
from research_index import DailyIndex, IndexFailure


@pytest.fixture
def case():
    fixture = legacy.IndexTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.doCleanups()


def deletions(case, monkeypatch):
    statements = []
    connect = case.index.connect

    @contextmanager
    def traced(readonly=False):
        with connect(readonly) as db:
            db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr(case.index, "connect", traced)
    return statements


def test_warm_replacement_deletes_by_rowid(case, monkeypatch):
    case.apply(case.record(text="Собрать шкаф."))
    trace = deletions(case, monkeypatch)
    case.apply(case.record(revision=2, text="Заменить сифон."))
    assert any(sql.startswith("DELETE FROM source_fts WHERE rowid=") for sql in trace)
    assert not any(sql.startswith("DELETE FROM source_fts WHERE cid=") for sql in trace)
    assert not case.search("шкаф")["hits"]
    assert [hit["cid"] for hit in case.search("сифон")["hits"]] == ["a"]


@pytest.mark.parametrize("drift", ["source_hash", "foreign_rowid"])
def test_stale_reference_falls_back_without_deleting_another_dialogue(
    case, monkeypatch, drift
):
    case.apply(
        case.record(text="Собрать шкаф."), case.record("b", text="Установить витрину.")
    )
    with case.index.connect() as db:
        if drift == "source_hash":
            db.execute(
                "UPDATE source_fts_refs SET source_hash=? WHERE cid='a'", ("f" * 64,)
            )
        else:
            db.execute(
                "UPDATE source_fts_refs SET fts_rowid="
                "(SELECT fts_rowid FROM source_fts_refs WHERE cid='b') WHERE cid='a'"
            )
    trace = deletions(case, monkeypatch)
    case.apply(case.record(revision=2, text="Заменить сифон."))
    assert any(sql.startswith("DELETE FROM source_fts WHERE cid=") for sql in trace)
    assert [hit["cid"] for hit in case.search("витрина")["hits"]] == ["b"]
    assert [hit["cid"] for hit in case.search("сифон")["hits"]] == ["a"]
    assert not case.search("шкаф")["hits"]


def test_legacy_migration_defers_ambiguous_entries_until_replacement(case, monkeypatch):
    case.apply(
        case.record(text="Собрать шкаф."), case.record("b", text="Установить витрину.")
    )
    with case.index.connect() as db:
        db.execute("DROP TABLE source_fts_refs")
        db.execute("INSERT INTO source_fts VALUES ('a','шкаф')")
    version = case.index.state()["version"]
    case.index = DailyIndex(
        case.index.directory,
        source_instance=case.index.source_instance,
        guard=case.guard,
        guard_version=lambda: case.epoch,
    )
    assert case.index.state()["version"] == version
    with case.index.connect(True) as db:
        assert [
            row["cid"] for row in db.execute("SELECT cid FROM source_fts_refs")
        ] == ["b"]
    trace = deletions(case, monkeypatch)
    case.apply(case.record(revision=2, text="Заменить сифон."))
    assert any(sql.startswith("DELETE FROM source_fts WHERE cid=") for sql in trace)
    with case.index.connect(True) as db:
        assert (
            db.execute("SELECT count(*) FROM source_fts WHERE cid='a'").fetchone()[0]
            == 1
        )
    assert not case.search("шкаф")["hits"]
    assert [hit["cid"] for hit in case.search("сифон")["hits"]] == ["a"]


def test_reference_and_fts_update_roll_back_together(case):
    case.apply(case.record(text="Собрать шкаф."))
    with case.index.connect(True) as db:
        before = tuple(db.execute("SELECT * FROM source_fts_refs").fetchone())

    def interrupt():
        raise RuntimeError("Interruption before publication")

    with pytest.raises(IndexFailure):
        case.apply(
            case.record(revision=2, text="Заменить сифон."), before_publish=interrupt
        )
    with case.index.connect(True) as db:
        assert tuple(db.execute("SELECT * FROM source_fts_refs").fetchone()) == before
        original = db.execute(
            "SELECT cid,text FROM source_fts WHERE rowid=?", (before[-1],)
        )
        assert tuple(original.fetchone()) == ("a", "собрать шкаф")
