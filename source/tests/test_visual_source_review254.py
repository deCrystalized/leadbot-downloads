"""A justified visual handoff is one source's result, never a technical pardon."""
import hashlib
import json
import unittest
import uuid

import source_protocol
import test_native_startup240 as fixture
import test_research_media204 as media
import test_research_vision214 as vision
from extension_assistant import _parse
from assistant_store import digest


class VisualSourceReview254Tests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.NativeStartup240Tests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.ctx['messages'][0]['attachments'] = [dict(id='unclear254', type='image')]
        self.case.sim.sync(self.case.ctx['convId'])
        self.case.base.native_context.client.image = lambda *args:dict(
            data=media.PNG,mime='image/png',sha256=hashlib.sha256(media.PNG).hexdigest())
        self.needs_human, self.review_approved = True, True
        self.error = None
        ordinary = self.case.sim.provider

        def provider(payload, timeout):
            current = json.loads(payload['input'][-1]['content'][0]['text'])['current']
            if current['candidate_contract']['task'].get('purpose') != 'visual_observation_v1':
                return ordinary(payload,timeout)
            self.case.sim.requests.append(payload)
            if self.error == 'transport':raise OSError('synthetic provider outage')
            if self.error == 'json':return b'{invalid-original'
            role = json.loads(payload['instructions'])['role']
            images = current['media']['images']
            if role == 'research':
                out = vision.observation(images)
                out['needs_operator'] = self.needs_human
                out['limitations'] = ['Предмет на этом синтетическом фото нельзя различить.']
            else:
                out = dict(kind='review',approved=self.review_approved,
                    violations=[] if self.review_approved else ['Описание не подтверждено пикселями'],
                    checked_claims=list(range(len(images))),basis=['current:'+i['message_id']for i in images])
            return source_protocol.encode(dict(id='visual254-'+str(len(self.case.sim.requests)),
                model='gpt-6.1-sol',status='completed',service_tier='default',usage=None,
                output=[dict(type='message',role='assistant',status='completed',
                    content=[dict(type='output_text',text=json.dumps(out,ensure_ascii=False))])]))

        self.case.app.research.request = provider
        self.service = self.case.app.research

    def start(self, manual=False):
        self.case.preview('neural_review' if manual else 'neural_auto')
        if manual:self.service.admit(self.case.app,self.case.body,max_calls=2,seconds=300)
        started,status = self.case.call('research_start')
        self.assertEqual(status,200,started)
        self.case.body['research_job_id'] = started['research_job_id']
        return started['research_job_id']

    def run_job(self):
        job = self.start()
        self.case.workers()
        return job

    def allowance(self):
        return self.service.automatic_allowance(self.case.app,self.case.body,{})

    def test_reviewed_unknown_parks_only_this_source_without_activating_facts_or_retry(self):
        job = self.run_job()
        original = self.service.jobs._file(job,'result.json').read_bytes()
        self.assertFalse(self.allowance()['blocked'])
        for action in ('research_status','research_finalize','research_status'):
            out,status = self.case.call(action)
            self.assertEqual(status,200,out)
            self.assertEqual(out['code'],'research_visual_review')
            self.assertTrue(out['needs_operator'])
            self.assertFalse(out['can_send_or_create'])
            self.assertFalse(out['retry_started'])
            self.assertFalse(out['human_media_review'])
            self.assertEqual(out['reply'],'')
            self.assertNotIn('draft_id',out)
        self.assertEqual(self.service.jobs._file(job,'result.json').read_bytes(),original)
        self.assertEqual(len(self.case.sim.requests),2)
        self.assertEqual(self.service.jobs.status(self.case.body['owner'],job)['state'],'rejected')
        scope='assistant:'+digest(self.case.body['owner'])
        _,messages,_,_ = _parse(self.case.ctx,self.case.app.store,scope)
        self.assertTrue(messages[0]['unread_media'])
        self.assertFalse(messages[0].get('media_model_reviewed',False))
        with self.case.app.store.connect()as db:
            self.assertEqual(db.execute('SELECT count(*)FROM research_visual_observations WHERE active=1').fetchone()[0],0)

    def test_another_prepared_case_runs_after_source_handoff_and_does_not_repeat_the_photo(self):
        oldjob=self.run_job()
        out,status=self.case.call('research_status')
        self.assertEqual(status,200,out)
        self.case.ctx=self.case.sim.add(str(uuid.uuid4()),'Нужно повесить полку на бетонную стену.')
        self.case.body=fixture.body(self.case,self.case.app,self.case.ctx)
        job=self.start();self.case.workers()
        final,status=self.case.call('research_finalize')
        self.assertEqual(status,200,final)
        self.assertTrue(final['reply']);self.assertEqual(final['validation'],[])
        self.assertNotEqual(job,oldjob)
        self.assertEqual(len(self.case.sim.requests),4)
        self.assertFalse(self.allowance()['blocked'])

    def test_existing_failure_counter_is_not_cleared_or_incremented_by_honest_unknown(self):
        job=self.start()
        with self.service.jobs.connect()as db:
            db.execute('UPDATE auto_sessions SET consecutive_failures=1')
        self.case.workers()
        for _ in range(2):
            out,status=self.case.call('research_status')
            self.assertEqual(status,200,out)
        with self.service.jobs.connect()as db:
            row=db.execute('SELECT blocked,consecutive_failures FROM auto_sessions').fetchone()
        self.assertEqual(tuple(row),(0,1))
        self.assertEqual(len(self.case.sim.requests),2)

    def test_negative_separate_review_is_not_a_source_review_pardon(self):
        self.review_approved=False
        self.run_job()
        self.assertTrue(self.allowance()['blocked'])
        out,status=self.case.call('research_status')
        self.assertNotEqual(status,200)
        self.assertNotEqual(out.get('code'),'research_visual_review')
        self.assertEqual(len(self.case.sim.requests),2)

    def test_format_or_transport_failure_still_stops_after_first_real_step(self):
        for kind in ('json','transport'):
            with self.subTest(kind=kind):
                other=type(self)();other.setUp()
                try:
                    other.error=kind;other.run_job()
                    self.assertTrue(other.allowance()['blocked'])
                    self.assertEqual(len(other.case.sim.requests),1)
                finally:other.doCleanups()

    def test_stop_after_review_prevents_old_scoped_result_from_becoming_current(self):
        self.run_job();self.case.live=False
        out,status=self.case.call('research_status')
        self.assertNotEqual(status,200)
        self.assertNotEqual(out.get('code'),'research_visual_review')
        self.assertEqual(len(self.case.sim.requests),2)

    def test_late_client_message_does_not_inherit_old_review_result(self):
        self.run_job()
        self.case.ctx['messages'].append(dict(id='later254',direction='in',sender_type='client',
                                            body='Подождите, я сейчас уточню.'))
        self.case.sim.sync(self.case.ctx['convId'])
        out,status=self.case.call('research_status')
        self.assertNotEqual(status,200)
        self.assertNotEqual(out.get('code'),'research_visual_review')
        self.assertEqual(len(self.case.sim.requests),2)

    def test_expired_review_does_not_obtain_a_new_deadline_or_call(self):
        job=self.run_job()
        with self.service.jobs.connect()as db:
            db.execute('UPDATE grants SET deadline=0 WHERE job=?',(job,))
        out,status=self.case.call('research_status')
        self.assertNotEqual(status,200)
        self.assertNotEqual(out.get('code'),'research_visual_review')
        self.assertEqual(self.service.jobs.status(self.case.body['owner'],job)['deadline'],0)
        self.assertEqual(len(self.case.sim.requests),2)

    def test_two_honest_unknowns_are_not_two_model_semantic_failures(self):
        self.run_job()
        self.case.ctx=self.case.sim.add(str(uuid.uuid4()),'Нужно повесить полку.')
        self.case.ctx['messages'][0]['attachments']=[dict(id='another254',type='image')]
        self.case.sim.sync(self.case.ctx['convId'])
        self.case.body=fixture.body(self.case,self.case.app,self.case.ctx)
        self.run_job()
        self.assertFalse(self.allowance()['blocked'])
        with self.service.jobs.connect()as db:
            row=db.execute('SELECT blocked,consecutive_failures FROM auto_sessions').fetchone()
        self.assertEqual(tuple(row),(0,0))
        self.assertEqual(len(self.case.sim.requests),4)

    def test_tampered_original_result_is_never_reclassified_as_readonly_review(self):
        job=self.run_job()
        self.service.jobs._file(job,'result.json').write_bytes(b'{}')
        out,status=self.case.call('research_status')
        self.assertNotEqual(status,200)
        self.assertNotEqual(out.get('code'),'research_visual_review')
        self.assertEqual(len(self.case.sim.requests),2)

    def test_manual_root_denial_retains_original_series_stop_contract(self):
        self.needs_human=False;self.case.mode='rehearsal'
        job=self.start(manual=True);self.case.workers()
        status=self.service.jobs.status(self.case.body['owner'],job)
        self.assertEqual(status['state'],'awaiting_root')
        self.service.jobs.decide(job,status['result_sha256'],accepted=False,reviewer='local-root-test')
        out,status=self.case.call('research_status')
        self.assertNotEqual(status,200)
        self.assertNotEqual(out.get('code'),'research_visual_review')
        self.assertEqual(self.service.jobs.status(self.case.body['owner'],job)['state'],'denied')
        self.assertEqual(len(self.case.sim.requests),2)


if __name__=='__main__':unittest.main()
