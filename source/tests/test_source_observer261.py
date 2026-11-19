"""Another CID may renew identity, never the original job's facts or rights."""
import base64
import hashlib
import hmac
import json
import threading
import unittest
from unittest.mock import patch

import test_owner_auto241 as fixture
from research_jobs import JobError


class SourceObserver261Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.OwnerAuto241Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.entered=threading.Event();self.release=threading.Event()
        self.native_entered=threading.Event();self.native_release=threading.Event()
        self.worker=None;self.reader=None;self.read_results=[]
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set();self.native_release.set()
        for thread in (self.worker,self.reader):
            if thread:
                thread.join(8)
                if thread.is_alive():raise AssertionError('Original simulation thread not terminal')

    def start(self,at_review=False):
        f=self.f;f.preview();out,code=f.research();self.assertEqual(code,200,out)
        self.job=out['research_job_id'];self.before=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        provider=f.sim.service.request
        def held(payload,timeout):
            raw=provider(payload,timeout)
            if len(f.sim.requests)==1 and not at_review:
                self.entered.set()
                if not self.release.wait(6):raise AssertionError('Synthetic provider not released')
            return raw
        f.sim.service.request=held
        if at_review:
            audit=f.sim.service.jobs.audit
            def gated(job,event,detail):
                result=audit(job,event,detail)
                if event=='model_step_planned' and detail['role']=='review':
                    self.entered.set()
                    if not self.release.wait(6):raise AssertionError('Review gate not released')
                return result
            f.sim.service.jobs.audit=gated
        wait=f.sim.service.observers.wait_for_observer
        f.sim.service.observers.wait_for_observer=lambda body,seconds:wait(body,min(seconds,.05))
        self.worker=threading.Thread(target=lambda:f.sim.command(dict(op='run_workers')))
        self.worker.start();self.assertTrue(self.entered.wait(4))

    def renewed_request(self,action='personal_plan',slow=False):
        f=self.f;other=f.sim.add('other-cid261','Нужно заменить смеситель.')
        f.sim.identity()
        body=dict(owner=fixture.fixture.OWNER,ctx=other,action=action,mine_count=0,**f.sim.last_identity)
        if slow:
            native=f.sim.service.native_context.prepare
            def held(*args,**kwargs):
                if threading.current_thread() is self.reader:
                    self.native_entered.set()
                    if not self.native_release.wait(6):raise AssertionError('Other source not released')
                return native(*args,**kwargs)
            change=patch.object(f.sim.service.native_context,'prepare',held);change.start();self.addCleanup(change.stop)
            self.reader=threading.Thread(target=lambda:self.read_results.append(f.sim.app.handle(body)))
            self.reader.start();self.assertTrue(self.native_entered.wait(4))
        else:
            result,code=f.sim.app.handle(body);self.assertEqual(code,200,result)
        return body

    def assert_continued(self):
        self.release.set();self.worker.join(5);self.assertFalse(self.worker.is_alive())
        f=self.f;state=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        self.assertEqual(state['state'],'accepted',state)
        self.assertEqual(state['deadline'],self.before['deadline'])
        self.assertEqual(state['calls_spent'],2);self.assertEqual(len(f.sim.requests),2)
        self.assertEqual(len(f.jobs()),1)
        self.assertTrue(all(s['acknowledged']for s in state['steps']))

    def assert_stopped(self):
        self.finish();f=self.f
        self.assertEqual(len(f.sim.requests),1)
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')

    def test_other_cid_plan_keeps_original_job_and_review_alive(self):
        self.start();self.renewed_request();self.assert_continued()

    def test_slow_other_cid_source_publishes_identity_before_context_finishes(self):
        self.start();self.renewed_request(slow=True);self.assert_continued()
        self.assertTrue(self.reader.is_alive(),'Other source deliberately still waiting')

    def test_status_only_signature_also_renews_exact_existing_job(self):
        self.start();self.renewed_request('personal_status');self.assert_continued()

    def test_other_prepared_cid_waiting_turn_renews_without_another_grant(self):
        self.start();f=self.f;f.next_context('waiting-cid261');f.preview()
        result,code=f.research();self.assertEqual(code,200,result)
        self.assertEqual(result['research_state'],'waiting_turn')
        self.assertFalse(result.get('research_job_id'));self.assert_continued()

    def test_other_cid_rotation_after_first_ack_reaches_separate_review(self):
        self.start(at_review=True)
        step=self.f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['steps'][0]
        self.assertTrue(step['acknowledged']);original=step['raw_hash']
        self.renewed_request(slow=True);self.assert_continued()
        self.assertEqual(self.f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['steps'][0]['raw_hash'],original)

    def test_original_relay_gap_reproduces_after_first_ack_without_new_request(self):
        self.start(at_review=True);f=self.f
        with patch.object(f.sim.service,'relay_request_identity',return_value=0):
            self.renewed_request()
        self.assert_stopped()
        state=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        self.assertTrue(state['steps'][0]['acknowledged'])
        events=f.sim.service.jobs.audit_read(fixture.fixture.OWNER,self.job)['events']
        failure=next(e for e in events if e['event']=='worker_control_stopped')
        self.assertEqual(failure['detail']['check'],'identity_unverified')

    def test_changed_original_source_still_blocks_review(self):
        self.start();f=self.f
        f.ctx['messages'].append(dict(id='new261',direction='in',sender_type='client',body='Отменяю, подождите.'))
        f.sim.sync(f.ctx['convId']);self.renewed_request();self.assert_stopped()

    def test_stopped_owner_mode_never_renews_original_auto_launch(self):
        self.start();f=self.f
        f.sim.app.handle(dict(f.body,action='personal_mode',execution_mode='review'))
        self.renewed_request();self.assert_stopped()

    def test_cancelled_job_never_starts_review_from_another_cid(self):
        self.start();self.f.sim.service.jobs.cancel(fixture.fixture.OWNER,self.job)
        self.renewed_request();self.assert_stopped()

    def test_terminal_stopped_job_is_not_revived_by_a_valid_other_cid(self):
        self.start();self.f.sim.service.jobs.stop(fixture.fixture.OWNER,self.job)
        self.renewed_request();self.assert_stopped()
        self.assertEqual(self.f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'stopped')

    def test_invalid_signature_cannot_renew_original_job(self):
        self.start();f=self.f;f.sim.identity()
        result,code=f.sim.app.handle(dict(owner=fixture.fixture.OWNER,action='personal_status',
            **dict(f.sim.last_identity,identity_proof='invalid')))
        self.assertEqual(code,403,result);self.assert_stopped()

    def test_new_request_without_any_job_cannot_create_admission(self):
        f=self.f;self.renewed_request()
        self.assertEqual(f.jobs(),[]);self.assertEqual(f.sim.requests,[])

    def test_no_job_anchor_never_adds_a_session_read_to_the_legacy_protocol(self):
        f=self.f
        with patch.object(f.sim.service,'_identity',return_value=dict(principal_id='old-principal',operator_id='old-actor')):
            with patch('personal_assistant.session',side_effect=AssertionError('No extra legacy session read')):
                self.assertEqual(f.sim.service.relay_request_identity(f.sim.app,f.body),0)

    def test_revocation_between_entry_verification_and_relay_is_not_a_server_error(self):
        f=self.f
        with patch.object(f.sim.service,'_identity',side_effect=JobError('Revoked',check='identity_unverified')):
            self.assertEqual(f.sim.service.relay_request_identity(f.sim.app,f.body),0)
        self.assertEqual(f.jobs(),[]);self.assertEqual(f.sim.requests,[])

    def test_other_signed_principal_cannot_relay_to_original_actor_anchor(self):
        self.start();f=self.f;f.sim.identity()
        encoded=f.sim.last_identity['identity_proof'].split('.')[0]
        data=json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        data['principal_id']='33333333-3333-4333-8333-333333333333'
        encoded=base64.urlsafe_b64encode(json.dumps(data,separators=(',',':')).encode()).rstrip(b'=')
        signature=base64.urlsafe_b64encode(hmac.new(fixture.fixture.SECRET.encode(),encoded,hashlib.sha256).digest()).rstrip(b'=')
        f.sim.last_identity['identity_proof']=(encoded+b'.'+signature).decode()
        result,code=f.sim.app.handle(dict(owner=fixture.fixture.OWNER,action='personal_status',**f.sim.last_identity))
        self.assertFalse(result.get('active'));self.assert_stopped()

    def test_relay_never_populates_another_browser_session_anchor(self):
        self.start();f=self.f;f.sim.identity()
        key=next(iter(f.sim.service.observers._anchors))
        anchor=f.sim.service.observers._anchors.pop(key)
        other=key[:3]+('different-browser-session',)+key[4:]
        f.sim.service.observers._anchors[other]=dict(anchor,key=other)
        result,code=f.sim.app.handle(dict(owner=fixture.fixture.OWNER,action='personal_status',**f.sim.last_identity))
        self.assertEqual(code,200,result);self.assert_stopped()
