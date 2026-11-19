"""Identity ingress may be fast; every worker still checks the full source."""
import base64
import hashlib
import hmac
import json
import threading
import time
import unittest
from unittest.mock import patch

import test_owner_auto241 as fixture


class ObserverIngress245Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.OwnerAuto241Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.worker=None;self.observer=None;self.waiting=threading.Event();self.entered=threading.Event()
        self.native_entered=threading.Event();self.native_release=threading.Event();self.answers=[]
        self.addCleanup(self.finish)

    def finish(self):
        self.native_release.set()
        for thread in (self.worker,self.observer):
            if thread:
                thread.join(8)
                if thread.is_alive():raise AssertionError('Original control thread not terminal')

    def start(self,gate_native=False):
        f=self.f;f.preview();out,code=f.research();self.assertEqual(code,200)
        self.job=out['research_job_id'];self.deadline=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['deadline']
        original_wait=f.sim.service.observers.wait_for_observer
        def wait(*args,**kwargs):self.waiting.set();return original_wait(*args,**kwargs)
        f.sim.service.observers.wait_for_observer=wait
        original_context=f.sim.service._context
        def context(*args,**kwargs):
            if threading.current_thread() is self.observer:
                self.entered.set();time.sleep(6)
            return original_context(*args,**kwargs)
        change=patch.object(f.sim.service,'_context',context);change.start();self.addCleanup(change.stop)
        if gate_native:
            original_native=f.sim.service.native_context.prepare
            def native(*args,**kwargs):
                if threading.current_thread() is self.worker and not self.native_entered.is_set():
                    self.native_entered.set()
                    if not self.native_release.wait(7):raise AssertionError('Native source gate not released')
                return original_native(*args,**kwargs)
            change=patch.object(f.sim.service.native_context,'prepare',native);change.start();self.addCleanup(change.stop)
        f.sim.identity();f.body.update(f.sim.last_identity)
        self.worker=threading.Thread(target=lambda:f.sim.command(dict(op='run_workers')))
        self.worker.start();self.assertTrue(self.waiting.wait(3))

    def observe(self):
        f=self.f;body=dict(f.body,action='research_status',research_job_id=self.job)
        self.observer=threading.Thread(target=lambda:self.answers.append(f.sim.app.handle(body)))
        self.observer.start()

    def audit(self):
        return self.f.sim.service.jobs.audit_read(fixture.fixture.OWNER,self.job)['events']

    def test_slow_context_observer_does_not_delay_exact_signed_identity_renewal(self):
        self.start();self.observe();self.assertTrue(self.entered.wait(3));self.finish();f=self.f
        self.assertEqual(self.answers[0][1],200,self.answers)
        status=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        self.assertEqual(status['state'],'accepted');self.assertEqual(status['deadline'],self.deadline)
        self.assertEqual(len(f.sim.requests),2);self.assertEqual(len(f.jobs()),1)
        event=next(e for e in self.audit()if e['event']=='identity_reattested_before_context')
        self.assertEqual(event['detail']['authority'],'identity_only_not_context_approval')
        final,code=f.research('research_finalize',self.job);self.assertEqual(code,200,final)
        self.assertTrue(final['draft_id']);self.assertEqual(final['validation'],[])

    def test_source_change_is_rejected_despite_early_valid_identity(self):
        self.start();f=self.f
        f.ctx['messages'].append(dict(id='new-client',direction='in',sender_type='client',body='Отменяю полку, подождите.'))
        f.sim.sync(f.ctx['convId']);self.observe();self.finish()
        self.assertEqual(f.sim.requests,[])
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')

    def test_owner_stop_after_identity_ingress_still_blocks_first_model_call(self):
        self.start(gate_native=True);self.observe();self.assertTrue(self.native_entered.wait(3));f=self.f
        f.sim.app.handle(dict(f.body,action='personal_stop'));self.native_release.set();self.finish()
        self.assertEqual(f.sim.requests,[])
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')

    def rejected_scope(self,field,value):
        self.start();f=self.f
        if field=='convId':f.body['ctx']=dict(f.body['ctx'],convId=value)
        else:f.body[field]=value
        self.observe();self.finish();self.assertEqual(f.sim.requests,[])
        self.assertNotIn('identity_reattested_before_context',[e['event']for e in self.audit()])

    def test_other_request_cannot_publish_a_proof_for_the_existing_job(self):
        self.rejected_scope('request_id','different-request')

    def test_other_chat_cannot_publish_a_proof_for_the_existing_job(self):
        self.rejected_scope('convId','different-chat')
        f=self.f
        for invalid in (None,'not-a-context',17):
            with self.subTest(invalid=invalid):
                value,code=f.sim.app.handle(dict(f.body,ctx=invalid,action='research_status',research_job_id=self.job))
                self.assertNotEqual(code,200);self.assertFalse(value.get('ok'))
        self.assertEqual(f.sim.requests,[])

    def test_another_signed_principal_cannot_renew_the_original_job(self):
        self.start();f=self.f
        encoded=f.body['identity_proof'].split('.')[0]
        data=json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        data['principal_id']='33333333-3333-4333-8333-333333333333'
        encoded=base64.urlsafe_b64encode(json.dumps(data,separators=(',',':')).encode()).rstrip(b'=')
        signature=base64.urlsafe_b64encode(hmac.new(fixture.fixture.SECRET.encode(),encoded,hashlib.sha256).digest()).rstrip(b'=')
        f.body['identity_proof']=(encoded+b'.'+signature).decode();self.observe();self.finish()
        self.assertEqual(f.sim.requests,[])
        self.assertNotIn('identity_reattested_before_context',[e['event']for e in self.audit()])
