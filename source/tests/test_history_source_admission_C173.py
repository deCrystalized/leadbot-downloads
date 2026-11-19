"""Regression tests for canonical matches and source-bound reviewed memory."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import test_research_history212 as history_fixture
from experience_memory import CHECKS, OWNER_CHECKS, digest
from research_history import HistoryCorpus
from research_index import DailyIndex, Header, Page
from research_pipeline import ResearchError
from test_full_history_learning300 import lesson_record, rows
from test_history_revisions304 import seed

LESSON_SOURCE = '40bdd08a-ebc8-4b3b-acde-96683a3daf21'


@pytest.fixture
def archive() -> Iterator[history_fixture.HistoryTests]:
    case = history_fixture.HistoryTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def test_find_an_additional_case_before_showing_a_second_version(
    archive: history_fixture.HistoryTests,
) -> None:
    seed(archive)
    seed(archive, cid='zz-authored-third', messages=rows(archive))
    history = HistoryCorpus(archive.approved, archive.index, archive.identities,
                            raw_history_selection='all_observed')
    result = archive.search(history)
    canonical = [hit.get('native_source_cid', hit['case_id']) for hit in result['hits']]
    assert canonical == ['old-a', 'old-b', 'zz-authored-third']
    original = history.call('read_history', {'case_id': 'zz-authored-third'}, archive.current)
    assert original['full_case_read'] is True
    assert original['manual_review_verified'] is False


def _lesson_corpus(
    archive: history_fixture.HistoryTests, mode: str = 'all_observed',
) -> tuple[HistoryCorpus, list[dict[str, Any]], dict[str, Any]]:
    archive.approved.allowed.add(LESSON_SOURCE)
    owner = lesson_record()
    staff = dict(owner, id='staff-wall', case_id=LESSON_SOURCE)
    archive.approved.__dict__['reviewed_lesson_metadata'] = {
        record['id']: {
            'record': record,
            'review': {
                'source_kind': source_kind, 'content_sha256': digest(record),
                'policy': 'current', **dict.fromkeys(checks, True),
            },
        }
        for record, source_kind, checks in [
            (owner, 'owner_correction', OWNER_CHECKS),
            (staff, 'reviewed_staff_case', CHECKS),
        ]
    }
    history = HistoryCorpus(archive.approved, archive.index, archive.identities,
                            raw_history_selection=mode)
    return history, [owner, staff], dict(archive.current, policy_version='current')


def _delete_source(archive: history_fixture.HistoryTests) -> None:
    state = archive.index.state()
    header = Header(LESSON_SOURCE, 3, 'native-' + LESSON_SOURCE, (), (), '', op='delete')
    archive.index.apply(Page('native', 'authored-source-deletion', state['cursor'],
                             'after-authored-deletion', (header,)),
                        lambda _: pytest.fail('Deletion must not read a body'),
                        expected_version=state['version'])


def test_tombstone_revokes_a_reviewed_lesson_without_revoking_owner_instruction(
    archive: history_fixture.HistoryTests,
) -> None:
    seed(archive, cid=LESSON_SOURCE, messages=rows(archive))
    earlier, records, current = _lesson_corpus(archive)
    assert [r['record']['id'] for r in earlier.admit_lessons(records, current)] == [
        'owner-wall', 'staff-wall',
    ]
    _delete_source(archive)
    with pytest.raises(ResearchError, match='Authoritative sources changed'):
        earlier.admit_lessons(records, current)
    archive.index = DailyIndex(archive.index.directory, source_instance='native',
                               guard=lambda _: True, guard_version=lambda: 'a' * 64)
    fresh, records, current = _lesson_corpus(archive)
    assert fresh.filter_lessons(records, current) == records[:1]
    assert [r['record']['id'] for r in fresh.admit_lessons(records, current)] == ['owner-wall']


@pytest.mark.parametrize('identity', ['group', 'phone', 'media'])
def test_newer_source_identity_can_exclude_an_old_lesson(
    archive: history_fixture.HistoryTests, identity: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_kwargs = {
        'group': {'group': archive.current['client_group']},
        'phone': {'phones': ['c' * 64]},
        'media': {'media': ['d' * 64]},
    }
    archive.current.update(phone_hashes=['c' * 64], media_hashes=['d' * 64])
    seed(archive, cid=LESSON_SOURCE, messages=rows(archive), **identity_kwargs[identity])
    fresh, records, current = _lesson_corpus(archive)

    def forbid_body(*args: object, **kwargs: object) -> None:
        pytest.fail('Lesson admission must use metadata alone')

    monkeypatch.setattr(archive.index, 'read', forbid_body)
    assert fresh.filter_lessons(records, current) == records[:1]
    assert [r['record']['id'] for r in fresh.admit_lessons(records, current)] == ['owner-wall']


def test_unavailable_index_withholds_source_derived_lesson(
    archive: history_fixture.HistoryTests,
) -> None:
    archive.index.source_unavailable()
    fresh, records, current = _lesson_corpus(archive)
    assert fresh.filter_lessons(records, current) == records[:1]


def test_source_lesson_remains_when_no_observed_revision_has_superseded_identity(
    archive: history_fixture.HistoryTests,
) -> None:
    fresh, records, current = _lesson_corpus(archive)
    assert fresh.filter_lessons(records, current) == records
