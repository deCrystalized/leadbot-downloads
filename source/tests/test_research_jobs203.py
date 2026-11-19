import json
import tempfile
import unittest
from pathlib import Path

from research_jobs import Jobs, JobError


class DurableResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1000.;self.binding=dict(owner='owner',request='request',chat='chat',revision='r1',
            principal='admin',operator='operator',policy='p1',memory='m1',map='map1',task='sha',profile='sol_only')
        self.current=dict(self.binding);self.calls=[]
        self.jobs=Jobs(Path(self.tmp.name)/'jobs',shared_lock=Path(self.tmp.name)/'provider.lock',clock=lambda:self.now)
        self.grant=self.jobs.admit(self.binding,max_calls=3,seconds=300)
        self.job=self.jobs.submit(self.binding,self.grant)['job_id']

    def payload(self,role='research'):
        return dict(model='gpt-6.1-sol',instructions=json.dumps(dict(role=role,profile='sol_only')),input=[dict(text='source')])

    def request(self,payload,timeout):
        self.calls.append((payload,timeout));return b'{"id":"response","model":"gpt-6.1-sol","status":"completed"}'

    def reader(self,**kwargs):
        return self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=self.request,**kwargs)

    def test_finite_server_grant_and_exact_scope_are_required(self):
        for key in self.binding:
            wrong=dict(self.binding);wrong[key]+='changed'
            with self.subTest(key=key),self.assertRaises(JobError):self.jobs.submit(wrong,self.grant)
        with self.assertRaises(JobError):self.jobs.admit(self.binding,max_calls=True,seconds=300)
        with self.assertRaises(JobError):self.jobs.admit(self.binding,max_calls=3,seconds=301)

    def test_submit_is_idempotent_and_other_owner_cannot_read_or_cancel(self):
        self.assertEqual(self.jobs.submit(self.binding,self.grant)['job_id'],self.job)
        with self.assertRaises(JobError):self.jobs.status('other',self.job)
        with self.assertRaises(JobError):self.jobs.cancel('other',self.job)

    def test_raw_is_fsynced_before_ack_and_parsing(self):
        observed=[]
        def after_raw(path):
            observed.append(path.read_bytes());s=self.jobs.status('owner',self.job)
            self.assertEqual(s['steps'][0]['state'],'raw');self.assertFalse(s['steps'][0]['acknowledged'])
        r=self.reader(after_raw=after_raw);out=r(self.payload(),120)
        self.assertEqual(out['id'],'response');self.assertEqual(len(observed),1)
        self.assertEqual(self.jobs.status('owner',self.job)['steps'][0]['state'],'acknowledged')

    def test_restart_reuses_exact_completed_raw_without_new_network(self):
        def crash(path):raise SystemExit('simulated process death after raw fsync')
        with self.assertRaises(SystemExit):self.reader(after_raw=crash)(self.payload(),120)
        recovered=Jobs(Path(self.tmp.name)/'jobs',shared_lock=Path(self.tmp.name)/'provider.lock',clock=lambda:self.now)
        out=recovered.requester(self.job,self.binding,fresh=lambda:self.current,request=self.request)(self.payload(),120)
        self.assertEqual(out['id'],'response');self.assertEqual(len(self.calls),1)
        self.assertEqual(recovered.status('owner',self.job)['calls_spent'],1)

    def test_changed_request_cannot_reuse_saved_raw(self):
        self.reader()(self.payload(),120);wrong=self.payload();wrong['input']=[dict(text='different')]
        with self.assertRaises(JobError):self.reader()(wrong,120)
        self.assertEqual(len(self.calls),1)

    def test_unknown_inflight_response_is_never_regenerated(self):
        def lost(payload,timeout):self.calls.append(payload);raise SystemExit('connection lost without raw')
        r=self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=lost)
        with self.assertRaises(SystemExit):r(self.payload(),120)
        with self.assertRaises(JobError):self.reader()(self.payload(),120)
        self.assertEqual(len(self.calls),1)

    def test_partial_or_malformed_raw_is_preserved_and_not_repaired(self):
        def malformed(payload,timeout):self.calls.append(payload);return b'{"broken": True}'
        r=self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=malformed)
        with self.assertRaises(JobError):r(self.payload(),120)
        self.assertEqual(self.jobs.raw(self.job,0),b'{"broken": True}')
        with self.assertRaises(JobError):self.reader()(self.payload(),120)
        self.assertEqual(len(self.calls),1)

    def test_call_budget_deadline_and_profile_cannot_be_reset(self):
        r=self.reader()
        for i in range(3):
            payload=self.payload();payload['input']=[dict(step=i)];r(payload,120)
        payload=self.payload();payload['input']=[dict(step=3)]
        with self.assertRaises(JobError):r(payload,120)
        self.assertEqual(len(self.calls),3)
        self.now=1301
        with self.assertRaises(JobError):self.reader()(self.payload(),120)

    def test_explicit_cancellation_and_each_version_change_prevent_network(self):
        for key in self.binding:
            self.current=dict(self.binding);self.current[key]+='changed'
            with self.subTest(key=key),self.assertRaises(JobError):self.reader()(self.payload(),120)
        self.current=dict(self.binding);self.jobs.cancel('owner',self.job)
        with self.assertRaises(JobError):self.reader()(self.payload(),120)
        self.assertEqual(self.calls,[])

    def test_version_change_during_request_saves_raw_then_stops(self):
        def changed(payload,timeout):self.calls.append(payload);self.current['revision']='r2';return b'{"id":"response"}'
        r=self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=changed)
        with self.assertRaises(JobError):r(self.payload(),120)
        self.assertEqual(self.jobs.raw(self.job,0),b'{"id":"response"}')
        self.assertEqual(len(self.calls),1)

    def test_root_acceptance_exact_result_and_legacy_validation_required(self):
        self.reader()(self.payload(),120)
        result=dict(approved=True,reply='По крепежу после осмотра.',candidate=dict(reply='По крепежу после осмотра.',needs_operator=False),can_send_or_create=False)
        receipt=self.jobs.propose(self.job,self.binding,result,fresh=lambda:self.current)
        calls=[]
        with self.assertRaises(JobError):self.jobs.finalize(self.job,self.binding,fresh=lambda:self.current,finish=lambda value:calls.append(value))
        with self.assertRaises(JobError):self.jobs.decide(self.job,'wrong',accepted=True,reviewer='root')
        self.jobs.decide(self.job,receipt['result_sha256'],accepted=True,reviewer='root')
        out=self.jobs.finalize(self.job,self.binding,fresh=lambda:self.current,finish=lambda value:dict(reply='',validation=['item_fitment_not_observed'],needs_operator=True))
        self.assertEqual(out['validation'],['item_fitment_not_observed']);self.assertEqual(calls,[])

    def test_root_denial_is_terminal_and_does_not_call_finalize(self):
        receipt=self.jobs.propose(self.job,self.binding,dict(approved=True,candidate={}),fresh=lambda:self.current)
        self.jobs.decide(self.job,receipt['result_sha256'],accepted=False,reviewer='root')
        with self.assertRaises(JobError):self.jobs.finalize(self.job,self.binding,fresh=lambda:self.current,finish=lambda value:self.fail('called'))

    def test_unknown_finalize_result_requires_explicit_same_request_reconciliation(self):
        receipt=self.jobs.propose(self.job,self.binding,dict(approved=True,candidate={}),fresh=lambda:self.current)
        self.jobs.decide(self.job,receipt['result_sha256'],accepted=True,reviewer='root')
        calls=[]
        def died(value):calls.append(value);raise SystemExit('saved draft but lost observer')
        with self.assertRaises(SystemExit):self.jobs.finalize(self.job,self.binding,fresh=lambda:self.current,finish=died)
        with self.assertRaises(JobError):self.jobs.finalize(self.job,self.binding,fresh=lambda:self.current,finish=died)
        out=self.jobs.reconcile(self.job,self.binding,fresh=lambda:self.current,read=lambda:dict(done=True,result=dict(draft_id='same-existing-draft')))
        self.assertEqual(out['draft_id'],'same-existing-draft');self.assertEqual(len(calls),1)

    def test_global_shared_lock_prevents_second_worker(self):
        with self.jobs.worker(self.job):
            with self.assertRaises(JobError):
                with self.jobs.worker(self.job):pass
            with self.assertRaises(JobError):self.reader()(self.payload(),120)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.jobs.status('owner',self.job)['calls_spent'],0)

    def test_job_and_raw_files_are_private_and_no_secret_exception_is_exposed(self):
        self.reader()(self.payload(),120)
        self.assertEqual(self.jobs.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.jobs.directory.stat().st_mode & 0o777,0o700)
        def error(payload,timeout):raise ValueError('secret credential')
        r=self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=error)
        self.assertEqual(r(self.payload(),120)['id'],'response')  # Existing raw is recovered, not requested again.
        payload=self.payload();payload['input']=[dict(text='new distinct step')]
        with self.assertRaises(JobError)as caught:r(payload,120)
        self.assertNotIn('secret',str(caught.exception))

    def test_duplicate_payload_is_not_a_new_paid_step_and_preflight_not_billed(self):
        from research_openai import ResponsesTransport, TransportError
        from api_costs import UsageLedger
        from research_pipeline import pack_context
        from test_research_pipeline218 import context
        r=self.reader();r(self.payload(),120)
        with self.assertRaises(JobError):r(self.payload(),120)
        self.assertEqual(len(self.calls),1)
        ledger=UsageLedger();self.jobs.cancel('owner',self.job)
        with self.assertRaises(TransportError):ResponsesTransport(self.reader(),ledger)('research',pack_context('research',context()),())
        self.assertEqual(ledger.summary()['calls'],0)

    def test_cancellation_during_finalize_does_not_return_a_live_draft(self):
        receipt=self.jobs.propose(self.job,self.binding,dict(approved=True,candidate={}),fresh=lambda:self.current)
        self.jobs.decide(self.job,receipt['result_sha256'],accepted=True,reviewer='root')
        def finish(value):self.jobs.cancel('owner',self.job);return dict(reply='stale',draft_id='stale')
        with self.assertRaises(JobError):self.jobs.finalize(self.job,self.binding,fresh=lambda:self.current,finish=finish)
        self.assertEqual(self.jobs.status('owner',self.job)['state'],'cancelled')

    def test_crash_after_complete_candidate_fsync_recovers_same_result(self):
        result=dict(approved=True,candidate=dict(reply='original'))
        original=self.jobs._save
        def crash(path,raw):original(path,raw);raise SystemExit('died after result fsync')
        self.jobs._save=crash
        with self.assertRaises(SystemExit):self.jobs.propose(self.job,self.binding,result,fresh=lambda:self.current)
        self.jobs._save=original
        receipt=self.jobs.propose(self.job,self.binding,result,fresh=lambda:self.current)
        self.assertTrue(receipt['requires_root']);self.assertEqual(self.jobs.status('owner',self.job)['state'],'awaiting_root')

    def test_private_audit_has_source_packet_hash_chain_and_no_foreign_owner_read(self):
        self.jobs.audit(self.job,'observed',dict(message_ids=['one'],unknown=['materials']))
        self.reader()(self.payload(),120)
        self.jobs.audit(self.job,'decision_basis',dict(summary='Наличие деталей не подтверждено.',basis=['current:one'],source='model_assertion_unverified'))
        entries=self.jobs.audit_read('owner',self.job)['events']
        self.assertIn('decision_basis',[e['event']for e in entries])
        self.assertIn('provider_request_saved',[e['event']for e in entries])
        self.assertTrue(self.jobs.audit_read('owner',self.job)['chain_valid'])
        with self.assertRaises(JobError):self.jobs.audit_read('another',self.job)
        path=self.jobs._file(self.job,'0.request.json')
        self.assertEqual(json.loads(path.read_bytes()),self.payload())
        self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_audit_tampering_or_secret_fields_are_rejected(self):
        with self.assertRaises(JobError):self.jobs.audit(self.job,'bad',dict(Authorization='Bearer secret'))
        self.jobs.audit(self.job,'observed',dict(message_ids=['one']))
        with self.jobs.connect()as db:db.execute("UPDATE audit_events SET detail='{}' WHERE job=?",(self.job,))
        with self.assertRaises(JobError):self.jobs.audit_read('owner',self.job)

    def test_nested_busy_request_cannot_erase_first_attempt_billing(self):
        from research_openai import ResponsesTransport,TransportError
        from research_pipeline import pack_context
        from api_costs import UsageLedger
        from test_research_pipeline218 import context
        ref=[]
        def request(payload,timeout):
            with self.assertRaises(JobError):ref[0](payload,timeout)
            raise TimeoutError('actual first attempt uncertain')
        ref.append(self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=request))
        ledger=UsageLedger()
        with self.assertRaises(TransportError):ResponsesTransport(ref[0],ledger)('research',pack_context('research',context()),())
        self.assertEqual(ledger.summary()['unknown_calls'],1)

    def test_job_session_lock_survives_between_steps_and_blocks_another_observer(self):
        other=Jobs(Path(self.tmp.name)/'jobs',shared_lock=Path(self.tmp.name)/'provider.lock',clock=lambda:self.now)
        with self.jobs.session_worker(self.job):
            self.assertTrue(other.worker_present(self.job))
            self.reader()(self.payload(),120)
            with self.assertRaises(JobError):
                with other.session_worker(self.job):pass
        self.assertFalse(other.worker_present(self.job))

    def test_root_denial_revokes_old_sibling_admissions_but_allows_explicit_new_case_admission(self):
        other=dict(self.binding,request='second',chat='second')
        old_grant=self.jobs.admit(other,max_calls=3,seconds=300)
        receipt=self.jobs.propose(self.job,self.binding,dict(approved=True,candidate={}),fresh=lambda:self.current)
        self.jobs.decide(self.job,receipt['result_sha256'],accepted=False,reviewer='root')
        with self.assertRaises(JobError):self.jobs.submit(other,old_grant)
        new_grant=self.jobs.admit(other,max_calls=3,seconds=300)
        self.assertTrue(self.jobs.submit(other,new_grant)['job_id'])

    def test_stop_all_also_revokes_unbound_grants(self):
        other=dict(self.binding,request='unbound')
        grant=self.jobs.admit(other,max_calls=2,seconds=300)
        self.jobs.stop_series('owner')
        with self.assertRaises(JobError):self.jobs.submit(other,grant)

    def test_input_writer_recovers_only_before_any_model_call_and_preserves_partial(self):
        path=self.jobs._file(self.job,'input.json');partial=path.with_suffix('.json.part');partial.write_bytes(b'partial metadata')
        self.jobs.save_input(self.job,b'{"complete":true}')
        self.assertEqual(path.read_bytes(),b'{"complete":true}')
        self.assertTrue(list(self.jobs.directory.glob(self.job+'-input-abandoned-*.part')))


if __name__=='__main__':unittest.main()
