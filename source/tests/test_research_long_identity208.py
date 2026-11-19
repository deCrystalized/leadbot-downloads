import copy
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

import operator_identity
from research_workflow import ResearchService
import test_operator_identity203 as ids
import test_research_bridge203 as bridge_fixture
import test_research_jobs203 as jobs_fixture
from research_jobs import JobError


class LongIdentity208Tests(unittest.TestCase):
    def setUp(self):
        real_verify=operator_identity.verify
        self.f=bridge_fixture.ResearchBridgeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.now=int(time.time());self.initial=self.now
        self.env=patch.dict(os.environ,LEADBOT_ACTOR_PROOF_KEY=ids.KEY,LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        self.env.start();self.addCleanup(self.env.stop)
        self.clock=patch('extension_assistant.time.time',side_effect=lambda:self.now)
        self.clock.start();self.addCleanup(self.clock.stop)
        verifier=patch.object(operator_identity,'verify',side_effect=real_verify)
        verifier.start();self.addCleanup(verifier.stop)
        self.f.service.identity=None;self.f.service.jobs.clock=lambda:self.now
        self.f.body.update(operator_id=ids.ACTOR,browser_session='long:208:session')
        self.proofs=[];self.issue()
        self.started=threading.Event();self.release=threading.Event()
        self.thread=None;self.errors=[];original=self.f.provider
        def provider(packet,timeout):
            if not self.started.is_set():
                self.started.set()
                if not self.release.wait(8):raise AssertionError('Test observer did not release response')
            return original(packet,timeout)
        self.f.service.request=provider
        self.addCleanup(self.cleanup_worker)

    def issue(self,**change):
        self.f.body.update(change)
        challenge=operator_identity.challenge(self.f.app.store,'owner',self.f.body,self.now)
        payload=dict(v=1,aud='leadbot-browser-operator',principal_id=ids.ADMIN,
            operator_id=self.f.body['operator_id'],principal_name='Admin',operator_name='Operator',role='admin',
            nonce=challenge['nonce'],sid=self.f.body['browser_session'],iat=self.now,exp=self.now+45)
        helper=ids.OperatorIdentityTests();helper.payload=payload
        proof=helper.proof();self.proofs.append(proof);self.f.body['identity_proof']=proof

    def cleanup_worker(self):
        self.release.set()
        if self.thread:
            # An expired proof may wait35s for the next30s signed heartbeat.
            # Keep the worker inside this fixture's identity/clock patches.
            self.thread.join(40)
            if self.thread.is_alive():raise AssertionError('Local test worker was not terminal')

    def start(self):
        self.f.service.admit(self.f.app,self.f.body,max_calls=4,seconds=300)
        out,code=self.f.call('research_start');self.assertEqual(code,200)
        self.job=out['research_job_id'];run=self.f.work.pop(0)
        def worker():
            try:run()
            except BaseException as exc:self.errors.append(type(exc).__name__)
        self.thread=threading.Thread(target=worker)
        self.thread.start();self.assertTrue(self.started.wait(5))
        return self.job

    def renew(self,**change):
        self.now+=30;self.issue(**change)
        return self.f.call('research_status',research_job_id=self.job)

    def complete(self):
        self.release.set();self.thread.join(40);self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.errors,[])
        return self.f.service.jobs.status('owner',self.job)

    def test_long_original_generation_survives_verified_poll_renewal_and_keeps_root_gate(self):
        self.start()
        for _ in range(5):
            status,code=self.renew();self.assertEqual(code,200)
            self.assertEqual(status['research_job_id'],self.job)
        status=self.complete()
        self.assertEqual(status['state'],'awaiting_root')
        self.assertEqual(status['deadline'],self.initial+300)
        self.assertEqual(status['calls_spent'],2)
        self.assertEqual(len(self.f.requests),2)
        self.f.service.jobs.decide(self.job,status['result_sha256'],accepted=True,reviewer='root')
        final,code=self.f.call('research_finalize',research_job_id=self.job)
        self.assertEqual(code,200);self.assertEqual(final['validation'],[])
        self.assertFalse(final['auto_enabled'])

    def test_no_renewal_keeps_raw_but_stops_before_another_generation(self):
        self.start();self.now+=60;status=self.complete()
        self.assertIn(status['state'],('stopped','rejected'))
        self.assertEqual(len(self.f.requests),1)
        self.assertTrue(self.f.service.jobs._file(self.job,'0.raw').exists())

    def test_expired_or_invalid_observer_cannot_renew_a_worker(self):
        self.start();self.now+=60
        self.f.body['identity_proof']='invalid'
        _,code=self.f.call('research_status',research_job_id=self.job)
        self.assertEqual(code,403)
        self.complete();self.assertEqual(len(self.f.requests),1)

    def test_session_change_cannot_rebind_existing_grant(self):
        self.start();_,code=self.renew(browser_session='other:208:session')
        self.assertEqual(code,403)
        status=self.complete();self.assertIn(status['state'],('stopped','rejected'))
        self.assertEqual(len(self.f.requests),1)

    def test_actor_change_stops_old_task_even_with_valid_new_signature(self):
        self.start();_,code=self.renew(operator_id='33333333-3333-4333-8333-333333333333')
        self.assertEqual(code,403);self.complete()
        self.assertEqual(len(self.f.requests),1)

    def test_new_client_message_fences_old_generation_despite_fresh_proof(self):
        self.start()
        self.f.ctx['messages'].append(dict(id='new',direction='in',sender_type='client',body='Секунду, подождите.'))
        _,code=self.renew();self.assertEqual(code,403)
        self.complete();self.assertEqual(len(self.f.requests),1)

    def test_renewal_does_not_extend_original_job_deadline(self):
        self.start();self.now=self.initial+290;self.issue()
        status,code=self.f.call('research_status',research_job_id=self.job)
        self.assertEqual(code,200);self.assertEqual(status['deadline'],self.initial+300)
        self.now=self.initial+301;self.issue()
        self.f.call('research_status',research_job_id=self.job)
        state=self.complete();self.assertIn(state['state'],('stopped','rejected'))
        self.assertEqual(len(self.f.requests),1)

    def test_proofs_and_test_signing_key_never_enter_model_or_durable_job_files(self):
        self.start();self.renew();self.renew();self.complete()
        packets=json.dumps(self.f.requests).encode()
        durable=b''.join(p.read_bytes()for p in self.f.service.jobs.directory.rglob('*')if p.is_file())
        for secret in self.proofs+[ids.KEY]:
            self.assertNotIn(secret.encode(),packets)
            self.assertNotIn(secret.encode(),durable)

    def test_replaced_challenge_revokes_cached_proof_before_expiry(self):
        self.start();self.renew()
        # Native challenge replacement revokes the currently cached proof.
        operator_identity.challenge(self.f.app.store,'owner',self.f.body,self.now)
        self.complete();self.assertEqual(len(self.f.requests),1)

    def test_response_arriving_during_nonce_rotation_waits_for_verified_same_session_observer(self):
        self.start();old=self.f.body['identity_proof']
        self.now+=30;self.issue()
        rejected=threading.Event();verifier=operator_identity.verify.side_effect
        def observe(store,owner,body,now):
            value=verifier(store,owner,body,now)
            if value is None and body.get('identity_proof')==old:rejected.set()
            return value
        with patch.object(operator_identity,'verify',side_effect=observe):
            self.release.set();self.assertTrue(rejected.wait(5))
            _,code=self.f.call('research_status',research_job_id=self.job)
            self.assertEqual(code,200)
            state=self.complete()
        self.assertEqual(state['state'],'awaiting_root')
        self.assertEqual(len(self.f.requests),2)

    def test_expired_observer_after_restart_cannot_generate_from_saved_task(self):
        self.release.set()
        self.f.service.admit(self.f.app,self.f.body,max_calls=4,seconds=300)
        out,code=self.f.call('research_start');self.assertEqual(code,200);self.job=out['research_job_id']
        with patch.object(self.f.service.jobs,'propose',side_effect=SystemExit('raw saved')):
            with self.assertRaises(SystemExit):self.f.work.pop(0)()
        old=self.f.service
        def forbidden(*args):raise AssertionError('Expired identity cannot generate')
        fresh=ResearchService(old.jobs.directory,shared_lock=old.jobs.lock,corpus_factory=old.corpus_factory,
            request=forbidden,schedule=lambda fn:self.f.work.append(fn))
        fresh.jobs.clock=lambda:self.now;self.now+=60
        fresh.run(self.f.app,copy.deepcopy(self.f.body),self.job)
        self.assertEqual(fresh.jobs.status('owner',self.job)['state'],'stopped')
        self.assertEqual(len(self.f.requests),2)

    def test_restart_with_fresh_proof_recovers_both_original_raw_responses_without_new_call(self):
        self.release.set()
        self.f.service.admit(self.f.app,self.f.body,max_calls=4,seconds=300)
        out,code=self.f.call('research_start');self.assertEqual(code,200);self.job=out['research_job_id']
        with patch.object(self.f.service.jobs,'propose',side_effect=SystemExit('observer lost after raw')):
            with self.assertRaises(SystemExit):self.f.work.pop(0)()
        self.assertEqual(len(self.f.requests),2)
        old=self.f.service
        def forbidden(*args):raise AssertionError('Same saved raw must be recovered without provider')
        fresh=ResearchService(old.jobs.directory,shared_lock=old.jobs.lock,corpus_factory=old.corpus_factory,
            request=forbidden,schedule=lambda fn:self.f.work.append(fn))
        fresh.jobs.clock=lambda:self.now
        self.f.service=self.f.app.research=fresh
        self.now+=60;self.issue()
        status,code=self.f.call('research_status',research_job_id=self.job)
        self.assertEqual(code,200);self.assertEqual(status['research_job_id'],self.job)
        self.f.work.pop(0)()
        state=fresh.jobs.status('owner',self.job)
        self.assertEqual(state['state'],'awaiting_root')
        self.assertEqual(state['calls_spent'],2)
        self.assertEqual(fresh.ledger.summary()['calls'],2)


class FreshGateRace208Tests(unittest.TestCase):
    def setUp(self):
        self.f=jobs_fixture.DurableResearchTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_deadline_is_checked_again_after_waiting_for_fresh_identity(self):
        def fresh():self.f.now+=301;return self.f.current
        with self.assertRaises(JobError):self.f.jobs._check(self.f.job,self.f.binding,fresh)

    def test_cancel_during_fresh_check_cannot_use_precheck_job_state(self):
        def fresh():self.f.jobs.cancel('owner',self.f.job);return self.f.current
        with self.assertRaises(JobError):self.f.jobs._check(self.f.job,self.f.binding,fresh)


if __name__=='__main__':unittest.main()
