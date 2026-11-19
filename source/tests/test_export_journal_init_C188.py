"""Keep the current export checkpoint when another process opens the journal."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import test_resume_protection_C187 as protection
from native_exporter import NativeExporter
from source_protocol import SourceError

case = protection.case


def reopen_during_write(case, before_write):
    """Schedule the existing worker immediately before initialization writes."""
    calls: list[str] = []

    class ReopeningExporter(NativeExporter):
        @contextmanager
        def db(self):
            with super().db() as connection:

                def execute(sql, parameters=()):
                    if not calls and sql.startswith("INSERT") and " INTO meta" in sql:
                        calls.append(sql)
                        before_write()
                    return connection.execute(sql, parameters)

                yield SimpleNamespace(
                    execute=execute, executescript=connection.executescript
                )

    reopened = ReopeningExporter(
        case.client,
        case.index,
        case.exporter.directory,
        shared_lock=case.lock,
        clock=lambda: case.now,
    )
    assert len(calls) == 1
    return reopened


def test_opening_journal_cannot_restore_obsolete_cursor(case):
    assert case.exporter.run(max_cases=1)["page"] == ["a", "b"]

    def advance():
        assert case.exporter.run(max_cases=1)["page"] == ["b"]

    reopened = reopen_during_write(case, advance)
    after_reopen = reopened.state()
    assert after_reopen["page"] == ["b"]
    assert after_reopen["processed"] == 1
    assert after_reopen["indexed"] == 1
    result = reopened.run()
    assert result["run"] is None
    assert result["indexed"] == 2
    assert case.header_reads == ["a", "b"]
    assert case.bodies == ["a", "b"]


def test_opening_journal_cannot_erase_protection_failure(case):
    case.exporter.run(max_cases=1)
    with case.exporter.db() as db:
        original = db.execute("SELECT value FROM prepared").fetchone()[0]

    def deny_protection(remaining):
        assert remaining > 0
        raise SourceError("current source protection could not be verified")

    def record_denial():
        case.exporter.preflight = deny_protection
        with pytest.raises(SourceError, match="could not be verified"):
            case.exporter.run(max_cases=1)

    reopened = reopen_during_write(case, record_denial)
    assert reopened.state()["error"] == "SourceError"
    assert reopened.state()["page"] == ["a", "b"]
    assert case.index.state()["protection_unavailable"] is True
    with reopened.db() as db:
        assert db.execute("SELECT value FROM prepared").fetchone()[0] == original
    with pytest.raises(SourceError, match="needs inspection"):
        reopened.run()
    assert case.header_reads == ["a"]
    assert case.bodies == ["a"]
