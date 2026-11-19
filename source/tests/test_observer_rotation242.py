"""A nonce renewal is not a new generation or permission to use old proofs."""
import os
import json
import threading
import time
import unittest
from unittest.mock import patch

import auto_simulator231 as fixture
from research_workflow import ResearchService
from research_jobs import JobError


class ObserverRotation242Tests(unittest.TestCase):
    def setUp(self):
        environment=patch.dict(os.environ,{},clear=False);environment.start();self.addCleanup(environment.stop)
        self.sim=fixture.Simulation();self.addCleanup(self.sim.tmp.cleanup)
        old=self.sim.service
        self.sim.service=ResearchService(self.sim.root/'research',shared_lock=self.sim.root/'lock',
            corpus_factory=old.corpus_factory,request=self.sim.provider,schedule=self.sim.work.append,
            native_context=old.native_context,proposal_enabled=True,owner_auto_enabled=True,auto_session_call_limit=8)
        self.sim.app.research=self.sim.service
        self.ctx=self.sim.add('observer-rotation242','Нужно повесить полку.')
        self.sim.identity();self.body=dict(owner=fixture.OWNER,ctx=self.ctx,**self.sim.last_identity)
        result,code=self.sim.app.handle(dict(self.body,action='personal_start'));self.assertEqual(code,200)
        result,code=self.sim.app.handle(dict(self.body,action='personal_mode',execution_mode='auto',confirmed=True,
            policy_ack=result['policy_version'],activation_nonce=result['activation_nonce'],client_version='2.8.32'))
        self.assertEqual(code,200)
        result,code=self.sim.app.handle(dict(self.body,action='preview',wording_mode='neural_auto',_trusted_research_profile='sol_only'))
        self.assertEqual(code,200);self.body.update(request_id=result['request_id'],revision=result['revision'])
        result,code=self.sim.app.handle(dict(self.body,action='research_start'));self.assertEqual(code,200)
        self.job=result['research_job_id'];self.deadline=self.sim.service.jobs.status(fixture.OWNER,self.job)['deadline']
        self.sim.identity();self.body.update(self.sim.last_identity)
        self.waiting=threading.Event();original=self.sim.service.observers.wait_for_observer
        def wait(*args,**kw):self.waiting.set();return original(*args,**kw)
        self.sim.service.observers.wait_for_observer=wait
        self.thread=threading.Thread(target=lambda:self.sim.command(dict(op='run_workers')))
        self.thread.start();self.addCleanup(self.finish)
        self.assertTrue(self.waiting.wait(3))

    def finish(self):
        self.thread.join(8)
        if self.thread.is_alive():raise AssertionError('Original worker not terminal')

    def observe(self):
        return self.sim.app.handle(dict(self.body,action='research_status',research_job_id=self.job))

    def test_verified_rotation_after_poll_interval_continues_same_job_and_original_deadline(self):
        time.sleep(1.25)
        self.assertEqual(self.sim.requests,[],'No call may use the revoked proof')
        result,code=self.observe();self.assertEqual(code,200,result)
        self.finish();status=self.sim.service.jobs.status(fixture.OWNER,self.job)
        self.assertEqual(status['state'],'accepted');self.assertEqual(status['deadline'],self.deadline)
        self.assertEqual(status['calls_spent'],2);self.assertEqual(len(self.sim.requests),2)
        with self.sim.service.jobs.connect()as db:self.assertEqual(db.execute('SELECT count(*)FROM grants').fetchone()[0],1)

    def test_changed_source_is_not_ordinary_proof_renewal(self):
        time.sleep(1.25)
        self.ctx['messages'].append(dict(id='changed',direction='in',sender_type='client',body='Пока отменяю, не отвечайте.'))
        self.sim.sync(self.ctx['convId']);_,code=self.observe();self.assertNotEqual(code,200)
        self.finish();self.assertEqual(self.sim.requests,[])
        self.assertNotEqual(self.sim.service.jobs.status(fixture.OWNER,self.job)['state'],'accepted')

    def test_explicit_stop_wakes_wait_without_accepting_a_proof_or_calling_model(self):
        self.sim.service.jobs.stop(fixture.OWNER,self.job)
        self.sim.service.observers.discard(fixture.OWNER,self.body['request_id'])
        self.finish();self.assertEqual(self.sim.requests,[])
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,self.job)['state'],'stopped')

    def test_owner_mode_change_during_gap_cannot_authorize_old_answer(self):
        self.sim.app.handle(dict(self.body,action='personal_mode',execution_mode='review'))
        _,code=self.observe();self.assertNotEqual(code,200)
        self.finish();self.assertEqual(self.sim.requests,[])
        self.assertNotEqual(self.sim.service.jobs.status(fixture.OWNER,self.job)['state'],'accepted')

    def test_worker_control_error_logs_safe_class_and_check_without_exception_text(self):
        marker='synthetic-credential-must-never-appear-in-audit'
        def fail(*args,**kwargs):raise JobError(marker,check='identity_unverified')
        self.sim.service._identity=fail
        self.sim.service.observers.discard(fixture.OWNER,self.body['request_id'])
        self.finish();self.assertEqual(self.sim.requests,[])
        audit=self.sim.service.jobs.audit_read(fixture.OWNER,self.job)
        self.assertNotIn(marker,json.dumps(audit))
        event=next(row for row in audit['events']if row['event']=='worker_control_stopped')
        self.assertEqual(event['detail']['stage'],'context')
        self.assertEqual(event['detail']['category'],'JobError')
        self.assertEqual(event['detail']['check'],'identity_unverified')
