"""Protected full-pool retrieval, explicit provenance and checked lesson growth."""
import copy
import hashlib
import json
import os
from unittest.mock import patch

import pytest
import test_research_history212 as history_source
from research_history import HistoryCorpus
from research_index import Header, IndexFailure, Page, source_hash
from research_pipeline import ResearchError


@pytest.fixture
def fixture():
    case = history_source.HistoryTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def corpus(case, mode='all_observed'):
    return HistoryCorpus(case.approved, case.index, case.identities,
                         raw_history_selection=mode)


def seed_many(case, records):
    headers = []
    sources = {}
    for index, record in enumerate(records):
        cid = record.get('cid', 'raw-' + str(index).zfill(3))
        source = {'cid': cid, 'source_revision': 1, 'client_group': record.get('client_group', 'group-' + cid),
                  'phone_hashes': record.get('phone_hashes', []), 'media_hashes': record.get('media_hashes', []),
                  'messages': record['messages'], 'metadata': {'names': ['Анна']}}
        sources[cid] = source
        headers.append(Header(cid, 1, source['client_group'], tuple(source['phone_hashes']),
            tuple(source['media_hashes']), source_hash(source), identity_keys=('b' * 64,)))
    for start in range(0, len(headers), 100):
        state = case.index.state()
        case.index.apply(Page('native', 'authored-full-search-' + str(start), state['cursor'],
            'next-' + str(start), tuple(headers[start:start + 100])),
            lambda header: sources[header.cid], expected_version=state['version'])


def rows(case, *, bot=False, delivery='delivered', author='Другой сотрудник'):
    result = copy.deepcopy(case.rows)
    result[1]['author'] = author
    for index, message in enumerate(result):
        if message.get('direction') == 'out':
            message['delivery'] = delivery
            if bot:
                message['client_message_id'] = 'lcp:authored-prior-bot-' + str(index)
    return result


def search(case, history, query='шкаф крепёж купить'):
    return history.call('search_history', {'query': query, 'direction': 'mnc'}, case.current)


def test_other_staff_is_retrievable_without_becoming_an_expert_or_a_lesson(fixture):
    seed_many(fixture, [{'messages': rows(fixture)}])
    old = search(fixture, corpus(fixture, 'experienced_humans'))
    assert 'raw-000' not in [h['case_id'] for h in old['hits']]
    history = corpus(fixture)
    out = search(fixture, history)
    hit = next(h for h in out['hits'] if h['case_id'] == 'raw-000')
    assert hit['source_provenance']['delivered_human_staff'] is True
    assert hit['source_provenance']['experienced_human_observed'] is False
    actual = history.call('read_history', {'case_id': 'raw-000'}, fixture.current)
    assert len(actual['messages']) == len(fixture.rows)
    assert actual['manual_review_verified'] is False
    assert actual['automatic_lesson_promotion'] is False
    assert actual['proves_current_customer_facts'] is False
    assert '89995550000' not in str(actual)
    assert history.filter_lessons([{'id': 'invented', 'case_id': 'raw-000'}], fixture.current) == []


def test_prior_bot_reply_is_labelled_as_bot_and_never_as_an_experienced_human(fixture):
    seed_many(fixture, [{'messages': rows(fixture, bot=True, author='Мамонтов Георгий')}])
    history = corpus(fixture)
    hit = next(h for h in search(fixture, history)['hits'] if h['case_id'] == 'raw-000')
    proof = hit['source_provenance']
    assert proof['delivered_bot'] is True
    assert proof['delivered_human_staff'] is False
    assert proof['experienced_human_observed'] is False
    actual = history.call('read_history', {'case_id': 'raw-000'}, fixture.current)
    assert actual['messages'][1]['source_role'] == 'bot'
    assert actual['historical_errors_possible'] is True


def test_pagination_finds_a_delivered_case_after_the_first_twenty_pending_ones(fixture):
    records = [{'messages': rows(fixture, delivery='pending')} for _ in range(25)]
    records += [{'messages': rows(fixture)}]
    seed_many(fixture, records)
    out = search(fixture, corpus(fixture))
    assert 'raw-025' in [h['case_id'] for h in out['hits']]
    assert out['candidate_headers_examined'] == out['candidate_bodies_examined'] == 1
    assert out['search_exhausted'] is True and out['search_truncated'] is False


def test_scan_limit_is_explicit_and_empty_is_not_global_absence(fixture):
    seed_many(fixture, [{'messages': rows(fixture)} for _ in range(101)])
    out = search(fixture, corpus(fixture))
    assert out['candidate_headers_examined'] == out['candidate_scan_limit'] == 100
    assert out['candidate_bodies_examined'] == 100
    assert out['search_truncated'] is True and out['full_pool_verified'] is False


def test_shown_raw_candidates_alone_gain_read_authority(fixture):
    seed_many(fixture, [{'messages': rows(fixture)} for _ in range(4)])
    history = corpus(fixture)
    shown = {h['case_id'] for h in search(fixture, history)['hits']}
    assert len(shown) == 3
    hidden = next(cid for cid in ['raw-000', 'raw-001', 'raw-002', 'raw-003'] if cid not in shown)
    with pytest.raises(ResearchError):
        history.call('read_history', {'case_id': hidden}, fixture.current)


@pytest.mark.parametrize('same', ['cid', 'client_group', 'phone_hashes', 'media_hashes'])
def test_current_identity_is_filtered_before_any_raw_body_read(fixture, same):
    record = {'cid': 'raw-000', 'messages': rows(fixture)}
    if same == 'cid':
        fixture.current['dialogue_id'] = 'historical-root-raw-000'
    elif same == 'client_group':
        record[same] = fixture.current[same]
    else:
        record[same] = ['d' * 64]
        fixture.current[same] = ['d' * 64]
    seed_many(fixture, [record])
    with patch.object(fixture.index, 'read', side_effect=AssertionError('Private body opened')) as read:
        assert 'raw-000' not in [h['case_id'] for h in search(fixture, corpus(fixture))['hits']]
    read.assert_not_called()


def test_guarded_source_is_never_opened_even_when_its_fts_text_matches(fixture):
    seed_many(fixture, [{'messages': rows(fixture)}])
    fixture.index.guard = lambda header: header.cid != 'raw-000'
    with patch.object(fixture.index, 'read', side_effect=AssertionError('Guarded body opened')) as read:
        assert 'raw-000' not in [h['case_id'] for h in search(fixture, corpus(fixture))['hits']]
    read.assert_not_called()


def test_selection_is_trusted_and_bound_to_the_same_job_snapshot(fixture):
    seed_many(fixture, [{'messages': rows(fixture)}])
    old = corpus(fixture, 'experienced_humans')
    current = corpus(fixture)
    assert old.initial != current.initial
    old.raw_history_selection = 'all_observed'
    with (patch.object(fixture.index, 'search', side_effect=AssertionError('Changed scope queried')),
          pytest.raises(ResearchError)):
        search(fixture, old)
    with pytest.raises(ResearchError):
        HistoryCorpus(fixture.approved, fixture.index, fixture.identities,
                      raw_history_enabled=False, raw_history_selection='all_observed')


@pytest.mark.parametrize('excluded', [[], ['raw-000'], ('x', 'x'), (None,), tuple('id-' + str(i) for i in range(101))])
def test_pagination_exclusions_are_typed_bounded_and_do_not_read_payload(fixture, excluded):
    with pytest.raises(IndexFailure):
        fixture.index.search('шкаф', expected_version=fixture.index.state()['version'],
            current={'cid': 'current'}, exclude_cids=excluded)


def test_unavailable_or_revoked_protection_is_not_a_silent_empty_archive(fixture):
    seed_many(fixture, [{'messages': rows(fixture)}])
    fixture.index.source_unavailable()
    out = search(fixture, corpus(fixture))
    assert out['raw_archive_available'] is False
    assert out['raw_archive_reason'] == 'source_sync_unavailable'
    fixture.index.source_unavailable(protection=True)
    with pytest.raises(ResearchError):
        corpus(fixture)


def test_private_factory_needs_the_new_explicit_scope_and_still_creates_no_job():
    import test_approved_history_scope266 as approved_source

    case = approved_source.ApprovedHistoryFactory266Tests()
    case.setUp()
    try:
        case.s.config['native_history_scope'] = 'approved_and_all_observed'
        result = case.configure()
        service = case.service()
        history = service.corpus_factory()
        assert history.raw_history_selection == 'all_observed'
        assert result['source_authority'] == 'approved_and_guarded_observed_staff_and_bot_history'
        assert not service.request.key_file.exists()
        with service.jobs.connect() as db:
            assert db.execute('SELECT count(*) FROM grants').fetchone()[0] == 0
    finally:
        case.doCleanups()


def test_mixed_bot_and_human_history_keeps_both_roles(fixture):
    mixed = rows(fixture, bot=True)
    mixed[3].pop('client_message_id')
    seed_many(fixture, [{'messages': mixed}])
    history = corpus(fixture)
    hit = next(h for h in search(fixture, history)['hits'] if h['case_id'] == 'raw-000')
    assert hit['source_provenance']['delivered_human_staff'] is True
    assert hit['source_provenance']['delivered_bot'] is True


def test_precise_raw_match_can_rank_before_generic_approved_examples(fixture):
    exact = rows(fixture)
    exact[0]['body'] += ' Необычный шкаф.'
    seed_many(fixture, [{'messages': exact}])
    out = search(fixture, corpus(fixture), query='шкаф крепёж купить необычный')
    assert out['hits'][0]['case_id'] == 'raw-000'
    assert out['hits'][0]['manual_review_verified'] is False


def test_experienced_human_wins_a_raw_tie_without_becoming_a_rule(fixture):
    seed_many(fixture, [{'messages': rows(fixture, bot=True)},
                       {'messages': rows(fixture)},
                       {'messages': rows(fixture, author='Мамонтов Георгий')}])
    out = search(fixture, corpus(fixture))
    raw = [h for h in out['hits'] if h['case_id'].startswith('raw-')]
    assert raw[0]['case_id'] == 'raw-002'
    assert raw[0]['source_authority'] == 'guarded_unreviewed_observed_history'


def lesson_record():
    return {'id': 'owner-wall', 'case_id': 'owner-authored-correction', 'client_group': 'a' * 64,
            'direction': 'mnc', 'stage': 'intake',
            'situation': 'Нужно повесить полку. Материал стены не сообщён.',
            'action': 'Уточнить материал стены одним вопросом.',
            'boundary': 'Не обещать крепёж или визит; учитывать уже сообщённые сведения.',
            'source_sha256': hashlib.sha256(b'authored owner correction control').hexdigest()}


def publish_lessons(case, records, reviews):
    from research_sources import ApprovedSources

    case.write(case.root / 'lessons.json', {'schema': 1, 'records': records})
    case.write(case.root / 'reviews.json', {'schema': 1, 'reviews': reviews})
    pointer = json.loads(case.pointer.read_text())
    for key in ('lessons', 'reviews'):
        pointer[key + '_sha256'] = case.sha(case.root / pointer[key])
    case.write(case.pointer, pointer)
    case.permission['pointer_sha256'] = case.sha(case.pointer)
    case.write(case.manifest, case.permission)
    return ApprovedSources(case.manifest, case.sha(case.manifest))


def test_published_correction_reaches_actual_bridge_and_revocation_removes_it():
    import assistant_policy
    import test_research_bridge203 as bridge_source
    import test_research_server209 as server_source
    from experience_memory import OWNER_CHECKS, digest

    case = server_source.ServerSourceTests()
    case.setUp()
    bridge = bridge_source.ResearchBridgeTests()
    bridge.setUp()
    record = lesson_record()
    review = {'content_sha256': digest(record), 'policy': assistant_policy.VERSION,
              'source_kind': 'owner_correction', **dict.fromkeys(OWNER_CHECKS, True)}
    try:
        with patch.dict(os.environ, {'LEADBOT_EXPERIENCE_POINTER': str(case.pointer),
                                    'LEADBOT_EXPERIENCE_REQUIRED': '1'}):
            versions = []
            for index, reviews in enumerate(({}, {record['id']: review}, {})):
                published = publish_lessons(case, [record], reviews)
                bridge.service.corpus_factory = published.corpus
                ctx = dict(bridge.ctx, convId='authored-learning-stage-' + str(index))
                preview, code = bridge.app.handle({'owner': 'owner', 'action': 'preview', 'ctx': ctx,
                    'wording_mode': 'neural_review', 'identity_proof': 'verified-by-test-verifier'})
                assert code == 200 and preview.get('pending_model'), preview.get('reason')
                bridge.prepared = preview
                bridge.task = json.loads(preview['model_task']['task'])
                bridge.body = dict(bridge.body, ctx=ctx, request_id=preview['request_id'], revision=preview['revision'])
                previous_calls = len(bridge.requests)
                bridge.service.admit(bridge.app, bridge.body, max_calls=4, seconds=300)
                started, code = bridge.call('research_start')
                assert code == 200 and started['pending_research']
                job = started['research_job_id']
                assert len(bridge.work) == 1
                bridge.work.pop(0)()
                assert len(bridge.requests) == previous_calls + 2
                packets = [json.loads(item['content'][0]['text']) for item in bridge.requests[-2]['input']
                           if item.get('content')]
                current = next(value['current'] for value in packets if 'current' in value)
                expected = [{'record': record, 'review': review}] if index == 1 else []
                assert current['lessons'] == expected
                versions.append(current['memory_version'])
                status, code = bridge.call('research_status', research_job_id=job)
                assert code == 200 and status['research_state'] == 'awaiting_root'
                bridge.service.jobs.decide(job, status['result_sha256'], accepted=True, reviewer='authored-learning-control')
                final, code = bridge.call('research_finalize', research_job_id=job)
                assert code == 200 and not final['validation'] and final['reply']
                assert final['auto_enabled'] is False
            assert len(set(versions)) == 2  # Exact reviewed publication can return to its earlier version.
            assert len(bridge.requests) == 6
    finally:
        bridge.doCleanups()
        case.doCleanups()


def test_missing_or_self_declared_lesson_review_fails_before_model_access(fixture):
    from experience_memory import OWNER_CHECKS, digest

    record = lesson_record()
    history = corpus(fixture)
    current = dict(fixture.current, policy_version='current')
    with pytest.raises(ResearchError):
        history.admit_lessons([record], current)
    review = {'content_sha256': digest(record), 'policy': 'current', 'source_kind': 'owner_correction',
              **dict.fromkeys(OWNER_CHECKS, True)}
    history.reviewed_lesson_metadata = {record['id']: {'record': record, 'review': review}}
    assert history.admit_lessons([record], current) == [{'record': record, 'review': review}]
    for key in OWNER_CHECKS:
        history.reviewed_lesson_metadata[record['id']]['review'] = dict(review, **{key: False})
        with pytest.raises(ResearchError):
            history.admit_lessons([record], current)


def test_revoked_publication_invalidates_older_corpus_admission():
    import assistant_policy
    import test_research_server209 as server_source
    from experience_memory import OWNER_CHECKS, digest

    case = server_source.ServerSourceTests()
    case.setUp()
    try:
        record = lesson_record()
        review = {'content_sha256': digest(record), 'policy': assistant_policy.VERSION,
                  'source_kind': 'owner_correction', **dict.fromkeys(OWNER_CHECKS, True)}
        before = publish_lessons(case, [record], {record['id']: review}).corpus()
        current = {'dialogue_id': 'other', 'policy_version': assistant_policy.VERSION, 'client_group': 'other'}
        assert before.admit_lessons([record], current)
        after = publish_lessons(case, [record], {}).corpus()
        with pytest.raises(ValueError):
            before.admit_lessons([record], current)
        with pytest.raises(ResearchError):
            after.admit_lessons([record], current)
    finally:
        case.doCleanups()


def test_completed_transcripts_are_searchable_without_claiming_audio_review(fixture):
    story = rows(fixture)
    for message in story:
        if message.get('direction') == 'in':
            message.update(voice_transcript=message['body'], voice_transcript_status='done', body='')
    seed_many(fixture, [{'messages': story}])
    history = corpus(fixture)
    hit = next(h for h in search(fixture, history)['hits'] if h['case_id'] == 'raw-000')
    assert hit['source_provenance']['existing_ASR_used_for_retrieval'] is True
    full = history.call('read_history', {'case_id': 'raw-000'}, fixture.current)
    assert full['original_media_reviewed'] is False
    assert full['messages'][0]['transcript_origin'] == 'existing_ASR_not_listened_audio'


def test_pending_transcripts_and_system_speech_do_not_establish_a_client_match(fixture):
    pending = rows(fixture)
    service = rows(fixture)
    for message in pending:
        if message.get('direction') == 'in':
            message.update(voice_transcript=message['body'], voice_transcript_status='pending', body='')
    for message in service:
        if message.get('direction') == 'in':
            message['speaker_role'] = 'system'
    seed_many(fixture, [{'messages': pending}, {'messages': service}])
    assert not any(h['case_id'].startswith('raw-') for h in search(fixture, corpus(fixture))['hits'])
