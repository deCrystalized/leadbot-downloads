"""Different clients, original-result recovery and shared-SQLite reply claims."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
import test_research_pipeline218 as sources
from experienced_dialogues import digest
from reply_diversity import fingerprint
from research_jobs import JobError, Jobs
from research_pipeline import Pipeline, ResearchError, pack_context
from research_startup import HTTPStartup
from research_workflow import ResearchService

REPLY = 'Здравствуйте! Точную стоимость скажу после осмотра.'


@pytest.mark.parametrize('other', [
    '  ЗДРАВСТВУЙТЕ. Точную стоимость скажу после осмотра!!! ',
    'Здравствуйте!\nТочную стоимость скажу после осмотра.',
    'Здравствуйте! Точную стои\u200bмость скажу после осмотра.',
    '😊 Здравствуйте! Точную стоимость скажу после осмотра.',
])
def test_cosmetic_changes_cannot_evade_full_reply_fingerprint(other):
    assert fingerprint(REPLY) == fingerprint(other)


def test_rewording_and_material_facts_are_not_rewritten_by_the_hash():
    assert fingerprint(REPLY) != fingerprint('После осмотра смогу назвать точную стоимость.')
    assert fingerprint('1000 рублей за штуку.') != fingerprint('1500 рублей за штуку.')
    assert fingerprint('1 000 рублей за штуку.') == fingerprint('1000 рублей за штуку.')
    assert fingerprint('') is None
    with pytest.raises(ValueError):
        fingerprint('😊 !!!')


def jobs(tmp_path, enabled=True):
    return Jobs(tmp_path / 'jobs', shared_lock=tmp_path / 'provider.lock',
                clock=lambda: 1000., unique_replies_enabled=enabled)


def proposed(store, serial, reply=REPLY, *, owner='bot-owner', purpose=None):
    binding = {'owner': owner, 'request': 'request-' + str(serial), 'chat': 'cid-' + str(serial),
               'revision': 'r1', 'principal': 'admin', 'operator': 'operator', 'policy': 'p1',
               'memory': 'm1', 'map': 'map1', 'task': 'task', 'profile': 'sol_only'}
    grant = store.admit(binding, max_calls=3, seconds=300)
    job = store.submit(binding, grant)['job_id']
    result = {'approved': True, 'reply': reply,
              'candidate': {'reply': reply, 'needs_operator': not bool(reply)}}
    if purpose:
        result['purpose'] = purpose
    receipt = store.propose(job, binding, result, fresh=lambda: binding)
    return job, receipt['result_sha256'], binding


def accept(store, item):
    store.decide(item[0], item[1], accepted=True, reviewer='authored-direct-control-review')


def test_same_owner_cannot_accept_the_same_reply_in_a_second_cid(tmp_path):
    store = jobs(tmp_path)
    first, second = proposed(store, 1), proposed(store, 2)
    accept(store, first)
    assert store.reply_available('bot-owner', REPLY) is False
    with pytest.raises(JobError, match='already accepted'):
        accept(store, second)
    assert store.status('bot-owner', second[0])['state'] == 'awaiting_root'
    third = proposed(store, 3, 'После осмотра смогу назвать точную стоимость.')
    accept(store, third)
    assert store.status('bot-owner', third[0])['state'] == 'accepted'


def test_restart_backfills_verified_legacy_replies_once_without_plaintext_audit(tmp_path):
    old = jobs(tmp_path, False)
    item = proposed(old, 1)
    accept(old, item)
    new = jobs(tmp_path)
    for _ in range(3):
        assert new.reply_available('bot-owner', REPLY) is False
    assert jobs(tmp_path).reply_available('bot-owner', REPLY) is False
    with new.connect() as db:
        rows = db.execute("SELECT detail FROM audit_events WHERE event='reply_indexed'").fetchall()
    assert len(rows) == 1 and REPLY not in rows[0]['detail']
    assert new.audit_read('bot-owner', item[0])['chain_valid'] is True


def test_corrupt_unindexed_accepted_original_fails_closed(tmp_path):
    old = jobs(tmp_path, False)
    item = proposed(old, 1)
    accept(old, item)
    old._file(item[0], 'result.json').write_text('{}')
    with pytest.raises(JobError, match='original reply changed'):
        jobs(tmp_path).reply_available('bot-owner', 'A different reply')


def test_changed_legacy_owner_binding_is_rejected_before_indexing_reply_text(tmp_path):
    old = jobs(tmp_path, False)
    item = proposed(old, 1)
    accept(old, item)
    with old.connect() as db:
        row = db.execute('SELECT id,binding FROM grants').fetchone()
        binding = json.loads(row['binding'])
        binding['principal'] = 'foreign-principal'
        db.execute('UPDATE grants SET binding=? WHERE id=?',(json.dumps(binding),row['id']))
    with pytest.raises(JobError, match='owner binding changed'):
        jobs(tmp_path).reply_available('bot-owner', 'A different reply')


def test_unknown_finalize_keeps_claim_and_reconciliation_does_not_send_again(tmp_path):
    store = jobs(tmp_path)
    item = proposed(store, 1)
    accept(store, item)
    calls = []

    def lost(value):
        calls.append(value)
        raise SystemExit('authored original acknowledgement lost')

    with pytest.raises(SystemExit):
        store.finalize(item[0], item[2], fresh=lambda: item[2], finish=lost)
    recovered = jobs(tmp_path)
    assert recovered.reply_available('bot-owner', REPLY) is False
    out = recovered.reconcile(item[0], item[2], fresh=lambda: item[2],
                              read=lambda: {'done': True, 'result': {'reply': REPLY}})
    assert out['reply'] == REPLY and len(calls) == 1


def test_other_owner_silent_veto_and_forms_do_not_claim_this_owners_reply(tmp_path):
    store = jobs(tmp_path)
    accept(store, proposed(store, 1, owner='other-bot'))
    assert store.reply_available('bot-owner', REPLY) is True
    accept(store, proposed(store, 2, ''))
    accept(store, proposed(store, 3, ''))
    accept(store, proposed(store, 4, REPLY, purpose='intake_form_v1'))
    assert store.reply_available('bot-owner', REPLY) is True


def test_denied_candidate_is_not_reply_history(tmp_path):
    store = jobs(tmp_path)
    item = proposed(store, 1)
    store.decide(item[0], item[1], accepted=False, reviewer='authored-rejection')
    assert store.reply_available('bot-owner', REPLY) is True


def test_two_competing_connections_can_accept_only_one_identical_reply(tmp_path):
    first = jobs(tmp_path)
    items = [proposed(first, i) for i in [1, 2]]
    second = jobs(tmp_path)
    gate = Barrier(2)

    def contender(store, item):
        assert store.reply_available('bot-owner', REPLY) is True
        gate.wait(timeout=5)
        try:
            accept(store, item)
            return 'accepted'
        except JobError:
            return 'duplicate-rejected'

    with ThreadPoolExecutor(max_workers=2) as workers:
        a = workers.submit(contender, first, items[0])
        b = workers.submit(contender, second, items[1])
        outcomes = [a.result(timeout=10), b.result(timeout=10)]
    assert sorted(outcomes) == ['accepted', 'duplicate-rejected']


def test_automatic_accept_and_manual_accept_share_the_same_atomic_claim(tmp_path):
    service = ResearchService(tmp_path / 'jobs', shared_lock=tmp_path / 'provider.lock',
        corpus_factory=lambda: None, request=lambda *args: pytest.fail('Unexpected provider call'),
        schedule=lambda worker: None, unique_replies_enabled=True)
    service.jobs.clock = lambda: 1000.
    service.jobs.holds.clock = service.jobs.clock
    # Trusted authored admission fixture; no browser/Run or real action is used.
    service.owner_auto_enabled = True
    items = [proposed(service.jobs, i) for i in [1, 2, 3]]
    with service.jobs.connect() as db:
        db.execute('INSERT INTO auto_sessions VALUES(?,?,?,?,?,?)', ('tag', 'bot-owner', 14, 9, 0, 0))
        for i, item in enumerate(items):
            grant = db.execute('SELECT grant_id FROM jobs WHERE id=?', (item[0],)).fetchone()[0]
            db.execute('INSERT INTO auto_admissions VALUES(?,?,?,?,?)',
                       ('prefix-' + str(i), digest(item[2]), 'tag', grant, 1000.))
    first = items[0]
    assert service._automatic_accept(first[0], first[2], fresh=lambda: first[2]) is True
    with pytest.raises(JobError, match='already accepted'):
        accept(service.jobs, items[1])
    with pytest.raises(JobError, match='already accepted'):
        service._automatic_accept(items[2][0], items[2][2], fresh=lambda: items[2][2])
    assert service.jobs.status('bot-owner', items[2][0])['state'] == 'awaiting_root'


def test_unknown_index_version_is_not_silently_treated_as_empty_history(tmp_path):
    store = jobs(tmp_path)
    accept(store, proposed(store, 1))
    with store.connect() as db:
        row = db.execute("SELECT sequence,detail FROM audit_events WHERE event='reply_indexed'").fetchone()
        detail = json.loads(row['detail'])
        detail['version'] = 2
        db.execute('UPDATE audit_events SET detail=? WHERE sequence=?', (json.dumps(detail), row['sequence']))
    with pytest.raises(JobError, match='index version'):
        store.reply_available('bot-owner', 'Different reply')


def fixture():
    f = sources.ResearchTests()
    f.setUp()
    return f


def test_one_duplicate_rewrite_uses_the_same_finite_budget_then_separate_review():
    f = fixture()
    try:
        original = f.draft()
        unique = copy.deepcopy(original)
        unique['reply'] = 'После осмотра уточню, что понадобится из крепежа.'
        sequence = [original, unique, f.review()]
        calls = []

        def model(role, packet, tools):
            calls.append((role, packet))
            return sequence.pop(0)

        out = Pipeline(f.corpus, model, profile='sol_only', max_calls=3,
                       initial_rule_ids=['R1'],
                       reply_available=lambda text: text != original['reply']).run(sources.context())
        assert out['approved'] is True and out['reply'] == unique['reply']
        assert [c[0] for c in calls] == ['research', 'research', 'review']
        assert calls[1][1]['input']['research']['reply_revision']['own_rejected_reply'] == original['reply']
        assert 'contextual_reply_contract' in json.loads(calls[0][1]['instructions'])
    finally:
        f.doCleanups()


@pytest.mark.parametrize('budget,repeat_again', [(2, False), (4, True)])
def test_insufficient_budget_or_a_second_duplicate_never_skips_review(budget, repeat_again):
    f = fixture()
    try:
        calls = []
        def model(role, packet, tools):
            calls.append(role)
            return f.draft()
        out = Pipeline(f.corpus, model, profile='sol_only', max_calls=budget,
                       initial_rule_ids=['R1'], reply_available=lambda text: not text).run(sources.context())
        assert not out['approved'] and not out['reply']
        assert len(calls) == (2 if repeat_again else 1)
        assert 'review' not in calls
    finally:
        f.doCleanups()


def test_review_rejection_never_triggers_a_lucky_rewrite():
    f = fixture()
    try:
        denied = f.review()
        denied.update(approved=False, violations=['Authored unsupported promise'])
        sequence = [f.draft(), denied]
        out = Pipeline(f.corpus, lambda *args: sequence.pop(0), profile='sol_only', max_calls=4,
                       initial_rule_ids=['R1'], reply_available=lambda text: True).run(sources.context())
        assert not out['approved'] and out['reason'] == 'review_rejected' and not sequence
        assert len(out['trace']) == 2
    finally:
        f.doCleanups()


def test_history_failure_prevents_any_model_callback():
    f = fixture()
    try:
        def unavailable(text):
            raise JobError('Authored original reply history missing')
        out = Pipeline(f.corpus, lambda *args: pytest.fail('Model accessed before index verification'),
                       reply_available=unavailable).run(sources.context())
        assert not out['approved'] and out['trace'] == []
    finally:
        f.doCleanups()


def test_startup_capability_is_explicit_typed_and_defaults_off():
    settings = HTTPStartup(Path('/private/jobs'), Path('/private/key'), Path('/private/lock'))
    assert settings.unique_replies_enabled is False
    assert replace(settings, unique_replies_enabled=True).unique_replies_enabled is True
    with pytest.raises(ValueError):
        replace(settings, unique_replies_enabled='true')
    with pytest.raises(ResearchError):
        pack_context('research', sources.context(), reply_diversity='false')


def test_configured_native_principal_inherits_the_same_trusted_uniqueness_capability():
    import native_execution
    import test_native_startup240 as startup
    from research_startup import configure_http
    from test_crm_only_native296 import TrustedCRMOnly296Tests

    case = TrustedCRMOnly296Tests()
    try:
        f = case.configured_fixture()
        settings = replace(f.settings, unique_replies_enabled=True)
        out = configure_http(settings, corpus_factory=f.base.corpus_factory, source_guard=lambda ids: None,
            native_context=f.base.native_context, schedule=f.sim.work.append,
            native_schedule=f.commands.append, connection_factory=f.forbidden_connection)
        gateway = native_execution._gateway
        assert out['configured'] is True
        assert gateway.app_factory.base.jobs.unique_replies_enabled is True
        assert gateway.app_factory(startup.simulation.PRINCIPAL).research.jobs.unique_replies_enabled is True
        assert f.network == [] and f.commands == [] and f.sim.requests == []
    finally:
        case.doCleanups()


def test_two_native_dialogues_rewrite_the_repeat_after_service_restart_with_no_budget_refill():
    from unittest.mock import patch

    import test_owner_auto241 as auto

    class UniqueService(ResearchService):
        def __init__(self, *args, **kwargs):
            kwargs['unique_replies_enabled'] = True
            super().__init__(*args, **kwargs)

    case = auto.OwnerAuto241Tests()
    with patch.object(auto, 'ResearchService', UniqueService):
        case.setUp()
    try:
        first = case.finish()
        original = json.loads(case.sim.service.jobs._file(first, 'result.json').read_text())['candidate']['reply']
        old = case.sim.service
        case.sim.service = UniqueService(case.sim.root / 'research', shared_lock=old.jobs.lock,
            corpus_factory=old.corpus_factory, request=case.sim.provider, schedule=case.sim.work.append,
            native_context=old.native_context, proposal_enabled=True, owner_auto_enabled=True,
            auto_session_call_limit=8)
        case.sim.app.research = case.sim.service
        case.next_context('unique-new-dialogue-after-restart')
        variant = 'Подскажите, из какого материала сделана стена под полку?'
        assert fingerprint(original) != fingerprint(variant)
        base = {'intent': 'Клиент хочет повесить полку.', 'meaning': 'Просит повесить полку.',
                'note': 'Материал стены ещё не указан.'}
        case.sim.scripted_candidates = [dict(base, reply=original), dict(base, reply=variant)]
        second = case.finish()
        result = json.loads(case.sim.service.jobs._file(second, 'result.json').read_text())
        assert result['candidate']['reply'] == variant and result['approved'] is True
        assert len(result['trace']) == 3 and [t['role'] for t in result['trace']] == ['research', 'research', 'review']
        assert len(case.sim.requests) == 5 and len(case.jobs()) == 2
        original_parts = [json.loads(item['content'][0]['text'])
                          for item in case.sim.requests[2]['input'][1:]]
        research_parts = [part['research'] for part in original_parts if 'research' in part]
        assert len(research_parts) == 1
        hint = research_parts[0]['reply_revision']
        assert hint['reason'] == 'current_trusted_example_already_used'
        assert hint['current_trusted_example'] == original
        status, code = case.sim.app.handle(dict(case.body, action='personal_status'))
        assert code == 200 and status['research_auto']['reserved_calls'] == 8
        assert status['research_auto']['remaining_calls'] == 0
    finally:
        case.doCleanups()


def test_used_current_example_is_reported_before_two_tool_calls_so_conclusion_still_fits_budget():
    import test_research_native203 as native

    f = fixture()
    try:
        current = native.native_context()
        old = native.native()['reply']
        current['candidate_contract']['task']['output_contract'] = {'example': {'reply': old}}
        unique = native.native()
        unique['reply'] = 'После осмотра уточню, что понадобится из крепежа.'
        packets = []

        def model(role, packet, tools):
            packets.append(packet)
            step = len(packets)
            if step == 1:
                hint = packet['input']['research']['reply_revision']
                assert hint['reason'] == 'current_trusted_example_already_used'
                assert hint['current_trusted_example'] == old
                assert 'own_rejected_reply' not in hint
                return f.tool('search_rules', query='крепёж покупка осмотр')
            if step == 2:
                return f.tool('read_rule', rule_id='R1')
            if step == 3:
                draft = f.draft()
                draft.update(reply=unique['reply'], candidate=unique)
                return draft
            return f.review()

        out = Pipeline(f.corpus, model, profile='sol_only', max_calls=4,
                       initial_rule_ids=['R1'], reply_available=lambda text: text != old).run(current)
        assert out['approved'] is True and out['reply'] == unique['reply']
        assert len(out['trace']) == 4 and out['trace'][-1]['role'] == 'review'
    finally:
        f.doCleanups()


def test_uniqueness_and_crm_only_coexist_with_actual_accepted_form_and_office_grant():
    from unittest.mock import patch

    from test_crm_only_native296 import NativeCRMOnly296Tests

    original = ResearchService.__init__

    def configured(self, *args, **kwargs):
        kwargs['unique_replies_enabled'] = True
        original(self, *args, **kwargs)

    case = NativeCRMOnly296Tests()
    try:
        with patch.object(ResearchService, '__init__', configured):
            b = case.make()
        assert b.f.app.research.jobs.unique_replies_enabled is True
        assert b.accepted['completion_mode'] == 'crm_only'
        assert b.gateway.notifications_enabled is False
        before = len(b.f.sim.requests)
        grant, status = b.execute(b.packet())
        assert status == 200 and grant['ok'] is True and grant['execution_allowed'] is False
        started, status = b.execute(b.packet('consume_office', grant_id=grant['grant_id']))
        assert status == 200 and started['execution_allowed'] is True
        assert started['customer_effect_confirmed'] is False
        assert len(b.f.sim.requests) == before and len(b.grants()) == 1
    finally:
        case.doCleanups()


@pytest.mark.parametrize('task', [None, {'output_contract': 'bad'},
    {'output_contract': {'example': []}}, {'output_contract': {'example': {'reply': 123}}}])
def test_malformed_trusted_example_stops_before_any_model_call(task):
    import test_research_native203 as native

    f = fixture()
    try:
        current = native.native_context()
        current['candidate_contract']['task'] = task
        out = Pipeline(f.corpus, lambda *args: pytest.fail('Malformed task reached the model'),
                       reply_available=lambda text: True).run(current)
        assert out['approved'] is False and out['trace'] == []
    finally:
        f.doCleanups()
