"""Real signed identity, delayed fake provider; no status-poll reattestation."""
import threading
import time
import unittest
from unittest.mock import patch

import test_owner_auto241 as fixture


class HeartbeatObserver247Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.OwnerAuto241Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.entered=threading.Event();self.release=threading.Event();self.thread=None
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set()
        if self.thread:
            self.thread.join(8)
            if self.thread.is_alive():raise AssertionError('Original worker is still running')

    def start(self):
        f=self.f;f.preview();out,code=f.research();self.assertEqual(code,200,out)
        self.job=out['research_job_id'];self.before=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        provider=f.sim.service.request
        def held(payload,timeout):
            raw=provider(payload,timeout)
            if len(f.sim.requests)==1:
                self.entered.set()
                if not self.release.wait(5):raise AssertionError('Synthetic response not released')
            return raw
        f.sim.service.request=held
        wait=f.sim.service.observers.wait_for_observer
        self.original_wait=wait
        f.sim.service.observers.wait_for_observer=lambda body,seconds:wait(body,min(seconds,.03))
        self.thread=threading.Thread(target=lambda:f.sim.command(dict(op='run_workers')))
        self.thread.start();self.assertTrue(self.entered.wait(4))

    def heartbeat(self):
        f=self.f;f.sim.identity();f.body.update(f.sim.last_identity)
        return f.sim.app.handle(dict(owner=fixture.fixture.OWNER,action='personal_heartbeat',**f.sim.last_identity))

    def assert_same_attempt(self):
        self.finish();f=self.f;state=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        self.assertEqual(state['state'],'accepted',state);self.assertEqual(state['deadline'],self.before['deadline'])
        self.assertEqual(state['calls_spent'],2);self.assertEqual(len(f.sim.requests),2)
        self.assertTrue(all(s['acknowledged']for s in state['steps']))
        self.assertEqual(len(f.jobs()),1)

    def test_heartbeat_alone_renews_worker_proof_across_saved_provider_response(self):
        self.start();out,code=self.heartbeat();self.assertEqual(code,200);self.assertTrue(out['active']);self.assert_same_attempt()

    def test_expired_volatile_observer_does_not_erase_exact_live_job_anchor(self):
        self.start();f=self.f
        for value in f.sim.service.observers._entries.values():value['expires']=0
        f.sim.service.observers.body(f.body)
        self.heartbeat();self.assert_same_attempt()

    def test_new_client_source_is_rechecked_after_heartbeat_before_review(self):
        self.start();f=self.f
        f.ctx['messages'].append(dict(id='changed',direction='in',sender_type='client',body='Отменяю полку, пока подождите.'))
        f.sim.sync(f.ctx['convId']);self.heartbeat();self.finish()
        self.assertEqual(len(f.sim.requests),1)
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')

    def test_stopped_auto_cannot_be_renewed_by_a_review_heartbeat(self):
        self.start();f=self.f
        f.sim.app.handle(dict(f.body,action='personal_mode',execution_mode='review'))
        self.heartbeat();self.finish();self.assertEqual(len(f.sim.requests),1)
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')

    def test_new_owner_launch_does_not_renew_a_previous_launch_job(self):
        self.start();f=self.f;f.sim.app.handle(dict(f.body,action='personal_stop'));f.start()
        self.heartbeat();self.finish();self.assertEqual(len(f.sim.requests),1)
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')

    def test_invalid_proof_heartbeat_does_not_supply_any_authority(self):
        self.start();f=self.f;f.sim.identity()
        bad=dict(owner=fixture.fixture.OWNER,action='personal_heartbeat',**f.sim.last_identity);bad['identity_proof']='invalid'
        out,code=f.sim.app.handle(bad);self.assertEqual(code,403);self.finish();self.assertEqual(len(f.sim.requests),1)

    def test_finished_job_heartbeat_cannot_generate_another_step(self):
        self.start();self.heartbeat();self.assert_same_attempt();f=self.f
        self.heartbeat();self.assertEqual(len(f.sim.requests),2)
        self.assertEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['deadline'],self.before['deadline'])

    def test_exact_status_can_recover_an_expired_volatile_entry_without_new_generation(self):
        self.start();f=self.f
        for value in f.sim.service.observers._entries.values():value['expires']=0
        f.sim.service.observers.body(f.body)
        out,code=f.research('research_status',self.job);self.assertEqual(code,200,out);self.assert_same_attempt()

    def test_cancelled_job_is_not_resumed_by_heartbeat(self):
        self.start();f=self.f;f.sim.service.jobs.cancel(fixture.fixture.OWNER,self.job)
        self.heartbeat();self.finish();self.assertEqual(len(f.sim.requests),1)
        self.assertEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'cancelled')

    def test_expiry_gap_waits_for_next_heartbeat_without_discarding_saved_raw(self):
        self.start();f=self.f;waiting=threading.Event()
        for value in f.sim.service.observers._entries.values():value['expires']=0
        for value in f.sim.service.observers._anchors.values():value['proof_expiry']=time.time()-1
        f.sim.service.observers.body(f.body);f.sim.identity()
        def wait(body,seconds):waiting.set();return self.original_wait(body,seconds)
        f.sim.service.observers.wait_for_observer=wait;self.release.set();self.assertTrue(waiting.wait(3))
        self.assertFalse(threading.Event().wait(5.2));self.assertTrue(self.thread.is_alive())
        state=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        self.assertEqual(state['state'],'running');self.assertEqual(len(f.sim.requests),1);self.assertFalse(state['steps'][0]['acknowledged'])
        original_raw_hash=state['steps'][0]['raw_hash'];self.assertTrue(original_raw_hash)
        self.heartbeat();self.assert_same_attempt()
        self.assertEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['steps'][0]['raw_hash'],original_raw_hash)

    def test_blocked_API_launch_denies_a_new_claim_before_customer_transport(self):
        f=self.f;f.preview();out,code=f.research();self.assertEqual(code,200);job=out['research_job_id']
        f.sim.service._automatic_failure(job,hard=True)
        f.ctx=f.sim.add('new-after-block','Нужно заменить смеситель.');f.body['ctx']=f.ctx
        f.sim.identity();f.body.update(f.sim.last_identity)
        plan,code=f.sim.app.handle(dict(f.body,action='personal_plan',mine_count=0))
        self.assertEqual(code,200);self.assertFalse(plan['eligible']);self.assertFalse(plan['needs_operator']);self.assertEqual(plan['step'],'paused')
        result,code=f.sim.app.handle(dict(f.body,action='personal_authorize',mine_count=0,operation=dict(kind='claim',operation_id='no-claim',revision=plan['revision'])))
        self.assertFalse(result['ok']);self.assertFalse(result.get('execution_allowed'));self.assertEqual(result['code'],'research_stopped')
        self.assertEqual(f.sim.requests,[])

    def test_exhausted_API_launch_does_not_take_a_new_dialogue(self):
        f=self.f;f.preview();_,code=f.research();self.assertEqual(code,200)
        with f.sim.service.jobs.connect()as db:db.execute('UPDATE auto_sessions SET reserved=call_limit')
        f.ctx=f.sim.add('after-exhaustion','Нужно заменить смеситель.');f.body['ctx']=f.ctx;f.sim.identity();f.body.update(f.sim.last_identity)
        plan,code=f.sim.app.handle(dict(f.body,action='personal_plan',mine_count=0))
        self.assertEqual(code,200);self.assertFalse(plan['eligible']);self.assertFalse(plan['needs_operator']);self.assertEqual(plan['step'],'paused');self.assertEqual(f.sim.requests,[])

    def test_unknown_acceptance_condition_keeps_its_existing_separate_route(self):
        f=self.f;f.preview();out,_=f.research();f.sim.service._automatic_failure(out['research_job_id'],hard=True)
        f.next_context('missing-wall-condition');f.sim.identity();f.body.update(f.sim.last_identity)
        plan,code=f.sim.app.handle(dict(f.body,action='personal_plan',mine_count=0))
        self.assertEqual(code,200);self.assertFalse(plan['eligible']);self.assertEqual(plan['admission'],'needs_facts')

    def test_prior_failed_prefix_is_not_regenerated_and_new_CID_can_progress(self):
        f=self.f;f.preview();out,code=f.research();self.assertEqual(code,200)
        f.sim.provider_mode='transport';f.sim.command(dict(op='run_workers'))
        self.assertEqual(len(f.sim.requests),1)
        f.sim.app.handle(dict(f.body,action='personal_stop'));f.body.pop('request_id');f.body.pop('revision');f.start();f.preview()
        prior,code=f.research();self.assertEqual(code,403);self.assertEqual(prior['code'],'research_prior_attempt')
        self.assertTrue(prior['needs_operator']);self.assertEqual(len(f.sim.requests),1);self.assertEqual(len(f.jobs()),1)
        f.next_context('separate-unattempted');f.preview();new,code=f.research()
        self.assertEqual(code,200,new);self.assertTrue(new['research_job_id']);self.assertEqual(len(f.jobs()),2)
        self.assertEqual(len(f.sim.requests),1)
