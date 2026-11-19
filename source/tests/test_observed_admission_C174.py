"""Observed archive search skips known ineligible cases before body reads."""

import pytest
import test_full_history_learning300 as authored
import test_native_exporter212 as native
from research_index import DailyIndex, Header, Page, source_hash

fixture = authored.fixture


def test_valid_cases_beyond_one_hundred_undelivered_matches(fixture, monkeypatch):
    pending = [{'messages': authored.rows(fixture, delivery='pending')} for _ in range(120)]
    valid = [{'messages': authored.rows(fixture)}, {'messages': authored.rows(fixture, bot=True)}]
    authored.seed_many(fixture, pending + valid)
    bodies = []
    original_read = fixture.index.read

    def tracked_read(cid, **kwargs):
        bodies.append(cid)
        return original_read(cid, **kwargs)

    monkeypatch.setattr(fixture.index, 'read', tracked_read)
    history = authored.corpus(fixture)
    # Isolate native slots from the separate reviewed archive.
    fixture.identities.blocked.update({'old-a', 'old-b'})
    result = authored.search(fixture, history)
    assert {hit['case_id'] for hit in result['hits']} == {'raw-120', 'raw-121'}
    assert sorted(bodies) == ['raw-120', 'raw-121']
    assert result['candidate_bodies_examined'] == 2
    assert result['search_exhausted'] is True
    assert result['full_pool_verified'] is False
    readback = history.call('read_history', {'case_id': 'raw-120'}, fixture.current)
    assert len(readback['messages']) == len(fixture.rows)
    assert readback['automatic_lesson_promotion'] is False


def test_confirmed_history_has_search_terms_for_contact_and_lead_roles(fixture):
    story = authored.rows(fixture)
    for index, message in enumerate(row for row in story if row['direction'] == 'in'):
        message['sender_type'] = ('contact', 'lead')[index % 2]
    authored.seed_many(fixture, [{'messages': story}])
    result = authored.search(fixture, authored.corpus(fixture))
    assert 'raw-000' in [hit['case_id'] for hit in result['hits']]


def _headers(index, *, observed_only=True):
    result = index.search('шкаф', expected_version=index.state()['version'],
                          current={'cid': 'authored-current'}, observed_only=observed_only)
    return {row['cid'] for row in result['hits']}


def test_latest_source_revision_controls_observed_admission(fixture):
    authored.seed_many(fixture, [{'messages': authored.rows(fixture, delivery='pending')}])
    index = fixture.index
    assert _headers(index) == set()
    assert _headers(index, observed_only=False) == {'raw-000'}
    current = {'cid': 'authored-current'}
    old_state = index.state()
    old = index.read('raw-000', expected_version=old_state['version'], current=current)['source']
    revised = dict(old, source_revision=2, messages=authored.rows(fixture, delivery='read'))
    header = Header('raw-000', 2, old['client_group'], (), (), source_hash(revised),
                    identity_keys=('b' * 64,))
    index.apply(Page('native', 'authored-delivery', old_state['cursor'],
                     'new-end', (header,)), lambda _: revised,
                expected_version=old_state['version'])
    assert _headers(index) == {'raw-000'}
    with index.connect() as db:
        # An older writer or restore may leave an admission row for an old hash.
        db.execute('UPDATE observed_history_admission SET source_hash=?,eligible=0 WHERE cid=?',
                   (source_hash(old), 'raw-000'))
    assert _headers(index) == {'raw-000'}


@pytest.fixture
def legacy_worker():
    case = native.ExporterTests()
    case.setUp()
    try:
        case.sources['b']['messages'] = [
            {'id': 'authored-customer', 'direction': 'in', 'sender_type': 'client',
             'body': 'Нужно собрать шкаф.'},
            {'id': 'authored-staff', 'direction': 'out', 'sender_type': 'operator',
             'delivery_status': 'delivered', 'body': 'Уточните, есть ли схема сборки.'},
        ]
        case.finish()
        with case.index.connect() as db:
            db.execute('DROP TABLE observed_history_admission')
        case.index = DailyIndex(case.index.directory, source_instance='native-fixture',
                                guard=lambda _: True, guard_version=lambda: 'b' * 64)
        case.exporter.index = case.index
        case.bodies.clear()
        yield case
    finally:
        case.doCleanups()


def test_old_cache_keeps_searchable_rows_and_refreshes_once(legacy_worker):
    case = legacy_worker
    assert _headers(case.index) == {'a', 'b'}
    case.now += 86401
    case.finish()
    assert case.bodies == ['a', 'b']
    assert _headers(case.index) == {'b'}
    assert _headers(case.index, observed_only=False) == {'a', 'b'}
    case.bodies.clear()
    case.now += 86401
    case.finish()
    assert case.bodies == []
    assert _headers(case.index) == {'b'}


def test_refresh_does_not_open_a_newly_excluded_legacy_case(legacy_worker):
    case = legacy_worker
    case.excluded.add('a')
    case.now += 86401
    case.finish()
    assert case.bodies == ['b']
    assert _headers(case.index) == {'b'}
    assert _headers(case.index, observed_only=False) == {'b'}
