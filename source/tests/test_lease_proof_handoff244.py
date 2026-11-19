"""A valid auto lease and a revoked observer proof are different facts."""
import threading
import unittest
from unittest.mock import patch

import personal_assistant
import test_owner_auto241 as fixture


class LeaseProofHandoff244Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.OwnerAuto241Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.ready=threading.Event();self.release=threading.Event();self.thread=None
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set()
        if self.thread:
            self.thread.join(8)
            if self.thread.is_alive():raise AssertionError('Original worker not terminal')

    def pause(self,occurrence=1):
        f=self.f;f.preview();started,code=f.research();self.assertEqual(code,200)
        self.job=started['research_job_id'];self.before=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        original=personal_assistant.session;self.lease_checks=0
        def session(*args,**kwargs):
            if threading.current_thread() is self.thread and args[2]=='personal_status':
                self.lease_checks+=1
                if self.lease_checks==occurrence:
                    self.ready.set()
                    if not self.release.wait(5):raise AssertionError('Test did not release original lease check')
            return original(*args,**kwargs)
        change=patch.object(personal_assistant,'session',session);change.start();self.addCleanup(change.stop)
        self.thread=threading.Thread(target=lambda:f.sim.command(dict(op='run_workers')))
        self.thread.start();self.assertTrue(self.ready.wait(5))

    def rotate(self):
        f=self.f;f.sim.identity();f.body.update(f.sim.last_identity)
        self.release.set()
        return f.research('research_status',self.job)

    def accepted_same_attempt(self):
        result,code=self.rotate();self.assertEqual(code,200,result);self.finish();f=self.f
        after=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        self.assertEqual(after['state'],'accepted');self.assertEqual(after['deadline'],self.before['deadline'])
        self.assertEqual(after['calls_spent'],2);self.assertEqual(len(f.sim.requests),2)
        self.assertEqual(len(f.jobs()),1)
        final,code=f.research('research_finalize',self.job);self.assertEqual(code,200,final)
        self.assertTrue(final['draft_id']);self.assertEqual(final['validation'],[])

    def test_rotation_during_personal_status_reobserves_full_context_and_same_job(self):
        self.pause();self.accepted_same_attempt()

    def test_rotation_during_launch_binding_recheck_reobserves_same_job(self):
        self.pause(2);self.accepted_same_attempt()

    def test_rotation_after_native_read_reobserves_before_using_that_snapshot(self):
        f=self.f;f.preview();started,code=f.research();self.assertEqual(code,200)
        self.job=started['research_job_id'];self.before=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        original=f.sim.service.native_context.prepare;reads=[]
        def prepare(*args,**kwargs):
            value=original(*args,**kwargs)
            if threading.current_thread() is self.thread:
                reads.append(value)
                if len(reads)==1:
                    self.ready.set()
                    if not self.release.wait(5):raise AssertionError('Test did not release native read')
            return value
        change=patch.object(f.sim.service.native_context,'prepare',prepare);change.start();self.addCleanup(change.stop)
        self.thread=threading.Thread(target=lambda:f.sim.command(dict(op='run_workers')))
        self.thread.start();self.assertTrue(self.ready.wait(5));self.accepted_same_attempt()
        self.assertGreaterEqual(len(reads),2,'The native source must be re-read after proof rotation')

    def test_new_source_during_lease_handoff_cannot_use_pre_rotation_native_snapshot(self):
        self.pause();f=self.f
        f.ctx['messages'].append(dict(id='new-order',direction='in',sender_type='client',body='Отменяю полку, пока подождите.'))
        f.sim.sync(f.ctx['convId']);self.rotate();self.finish()
        self.assertEqual(f.sim.requests,[])
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')

    def test_explicit_owner_stop_during_lease_handoff_never_renews_authority(self):
        self.pause();f=self.f
        f.sim.app.handle(dict(f.body,action='personal_stop'));self.release.set();self.finish()
        self.assertEqual(f.sim.requests,[])
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')

    def test_actually_expired_lease_is_not_a_proof_handoff(self):
        self.pause();f=self.f
        with f.sim.app.store.connect()as db:db.execute('UPDATE personal_sessions SET expires=0')
        self.release.set();self.finish();self.assertEqual(f.sim.requests,[])
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')
