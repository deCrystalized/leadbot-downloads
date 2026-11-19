"""Nonce rotation after review preserves the result, never model authority."""
import threading
import time
import unittest

import test_owner_auto241 as fixture


class MachineAcceptHandoff243Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.OwnerAuto241Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.thread=None;self.release=threading.Event();self.ready=threading.Event()
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set()
        if self.thread:
            self.thread.join(8)
            if self.thread.is_alive():raise AssertionError('Original worker not terminal')

    def pause_after_propose(self):
        f=self.f;f.preview();started,code=f.research();self.assertEqual(code,200)
        self.job=started['research_job_id'];self.deadline=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['deadline']
        original=f.sim.service.jobs.propose
        def propose(*args,**kwargs):
            result=original(*args,**kwargs);self.ready.set()
            if not self.release.wait(5):raise AssertionError('Test did not release the original result')
            return result
        f.sim.service.jobs.propose=propose
        self.thread=threading.Thread(target=lambda:f.sim.command(dict(op='run_workers')))
        self.thread.start();self.assertTrue(self.ready.wait(5))
        pending,code=f.research('research_status',self.job);self.assertEqual(code,200,pending)
        self.assertEqual(pending['research_state'],'awaiting_root')
        self.assertFalse(pending['requires_root']);self.assertTrue(pending['awaiting_machine_acceptance'])
        f.sim.identity();f.body.update(f.sim.last_identity)
        self.release.set();time.sleep(.15)

    def test_rotated_proof_after_review_resumes_same_machine_acceptance_without_extra_calls(self):
        self.pause_after_propose();f=self.f
        result,code=f.research('research_status',self.job);self.assertEqual(code,200,result)
        self.assertFalse(result['requires_root']);self.finish()
        status=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        self.assertEqual(status['state'],'accepted');self.assertEqual(status['deadline'],self.deadline)
        self.assertEqual(status['calls_spent'],2);self.assertEqual(len(f.sim.requests),2)
        self.assertEqual(len(f.jobs()),1)
        final,code=f.research('research_finalize',self.job);self.assertEqual(code,200,final)
        self.assertTrue(final['draft_id']);self.assertEqual(final['validation'],[])

    def test_changed_source_after_review_cannot_resume_or_finalize_old_candidate(self):
        self.pause_after_propose();f=self.f
        f.ctx['messages'].append(dict(id='new-goal',direction='in',sender_type='client',body='Отменяю полку, пока не отвечайте.'))
        f.sim.sync(f.ctx['convId']);_,code=f.research('research_status',self.job)
        self.assertNotEqual(code,200);self.finish();self.assertEqual(len(f.sim.requests),2)
        self.assertNotEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'accepted')

    def test_explicit_stop_during_post_review_gap_never_accepts_or_generates(self):
        self.pause_after_propose();f=self.f
        f.sim.service.jobs.stop(fixture.fixture.OWNER,self.job)
        f.sim.service.observers.discard(fixture.fixture.OWNER,f.body['request_id'])
        self.finish();self.assertEqual(len(f.sim.requests),2)
        self.assertEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['state'],'stopped')

    def test_manual_grant_under_available_auto_still_requires_manual_root(self):
        f=self.f;f.start(auto=False);f.preview('neural_review')
        f.sim.service.admit(f.sim.app,f.body,max_calls=4,seconds=300)
        started,code=f.research();self.assertEqual(code,200)
        f.sim.command(dict(op='run_workers'))
        result,code=f.research('research_status',started['research_job_id']);self.assertEqual(code,200,result)
        self.assertTrue(result['requires_root']);self.assertFalse(result.get('awaiting_machine_acceptance',False))
        self.assertEqual(result['research_state'],'awaiting_root');self.assertEqual(len(f.sim.requests),2)

    def test_rotated_proof_before_native_finalize_recovers_same_draft_without_another_call(self):
        f=self.f;f.preview();started,code=f.research();self.assertEqual(code,200)
        self.job=started['research_job_id'];f.sim.command(dict(op='run_workers'))
        before=f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)
        self.assertEqual(before['state'],'accepted')
        original=f.sim.service.jobs.finalize;answers=[]
        def finalize(*args,**kwargs):
            self.ready.set()
            if not self.release.wait(5):raise AssertionError('Test did not release original finalize')
            return original(*args,**kwargs)
        f.sim.service.jobs.finalize=finalize
        self.thread=threading.Thread(target=lambda:answers.append(f.research('research_finalize',self.job)))
        self.thread.start();self.assertTrue(self.ready.wait(5))
        f.sim.identity();f.body.update(f.sim.last_identity);self.release.set();time.sleep(.15)
        observed,code=f.research('research_status',self.job);self.assertEqual(code,200,observed)
        self.finish();self.assertEqual(len(answers),1)
        final,code=answers[0];self.assertEqual(code,200,final);self.assertTrue(final['draft_id'])
        self.assertEqual(len(f.sim.requests),2)
        self.assertEqual(f.sim.service.jobs.status(fixture.fixture.OWNER,self.job)['deadline'],before['deadline'])
        again,code=f.research('research_finalize',self.job);self.assertEqual(code,200,again)
        self.assertEqual(again['draft_id'],final['draft_id']);self.assertEqual(len(f.sim.requests),2)

    def test_post_native_finish_gap_stays_pending_and_does_not_repeat_finish(self):
        f=self.f;f.preview();started,code=f.research();self.assertEqual(code,200)
        self.job=started['research_job_id'];f.sim.command(dict(op='run_workers'))
        original=f.sim.service.jobs.finalize;answers=[];finished=[]
        def finalize(*args,finish,**kwargs):
            def once(result):
                value=finish(result);finished.append(value);self.ready.set()
                if not self.release.wait(5):raise AssertionError('Test did not release native result')
                return value
            return original(*args,finish=once,**kwargs)
        f.sim.service.jobs.finalize=finalize
        self.thread=threading.Thread(target=lambda:answers.append(f.research('research_finalize',self.job)))
        self.thread.start();self.assertTrue(self.ready.wait(5))
        pending,code=f.research('research_status',self.job);self.assertEqual(code,200,pending)
        self.assertEqual(pending['research_state'],'finalizing');self.assertTrue(pending['pending_research'])
        self.assertFalse(pending['requires_root'])
        f.sim.identity();f.body.update(f.sim.last_identity);self.release.set();time.sleep(.15)
        observed,code=f.research('research_status',self.job);self.assertEqual(code,200,observed)
        self.finish();self.assertEqual(len(finished),1)
        final,code=answers[0];self.assertEqual(code,200,final)
        self.assertEqual(final['draft_id'],finished[0]['draft_id']);self.assertEqual(len(f.sim.requests),2)
        again,code=f.research('research_finalize',self.job);self.assertEqual(code,200,again)
        self.assertEqual(again['draft_id'],final['draft_id']);self.assertEqual(len(finished),1)
