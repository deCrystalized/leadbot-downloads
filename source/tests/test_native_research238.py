"""Actual research jobs/proposal/review/finalize with simulated native Run/model."""
import hashlib
import json
import os
import unittest
import uuid
from unittest.mock import patch

import auto_simulator231 as fixture
import assistant_policy as policy
from native_authority import NativeAuthority
from source_protocol import SourceError
from research_workflow import ResearchService
from test_research_media204 import PNG


class NativeResearch238Tests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{},clear=False);env.start();self.addCleanup(env.stop)
        self.sim=fixture.Simulation();self.addCleanup(self.sim.tmp.cleanup)
        self.run_id=str(uuid.uuid4());self.generation=1;self.mode='auto';self.live=True
        self.permission=True;self.version_override=None;self.reads=0
        case=self
        class Reader:
            def run_authority(self, run_id, generation, actor):
                case.reads+=1
                if (not case.live or not case.permission or run_id!=case.run_id or generation!=case.generation
                        or actor!=dict(principal_id=fixture.PRINCIPAL,operator_id=fixture.ACTOR)):
                    raise SourceError('Run or role changed')
                return dict(actor,run_id=run_id,generation=generation,mode=case.mode,
                    versions=case.version_override or list(case.versions()))
        self.authority=NativeAuthority(Reader(),owner=fixture.OWNER,principal_id=fixture.PRINCIPAL,
                                       current_versions=self.versions)
        old=self.sim.service
        self.sim.service=ResearchService(self.sim.root/'research',shared_lock=self.sim.root/'provider.lock',
            corpus_factory=old.corpus_factory,request=self.sim.provider,schedule=self.sim.work.append,
            native_context=old.native_context,proposal_enabled=True,owner_auto_enabled=True,
            auto_session_call_limit=12,native_authority=self.authority)
        self.sim.app.research=self.sim.service
        self.ctx=self.sim.add('native-research238','Нужно повесить полку.')
        self.body=dict(owner=fixture.OWNER,ctx=self.ctx,native_run=dict(
            run_id=self.run_id,generation=1,operator_id=fixture.ACTOR))

    def versions(self):
        s=self.sim.service
        return policy.VERSION,s.code_version,s._map_version(),s.corpus_factory().initial

    def call(self,action,**extra):
        return self.sim.app.handle(dict(self.body,action=action,**extra))

    def preview(self,mode='neural_auto'):
        out,code=self.call('preview',wording_mode=mode,_trusted_research_profile='sol_only')
        self.assertEqual(code,200,out);self.assertTrue(out.get('pending_model'),out)
        self.body.update(request_id=out['request_id'],revision=out['revision'])
        return out

    def start(self):
        self.preview();out,code=self.call('research_start')
        self.assertEqual(code,200,out);self.assertTrue(out.get('research_job_id'),out)
        self.body['research_job_id']=out['research_job_id']
        return out['research_job_id']

    def workers(self):
        while self.sim.work:self.sim.work.pop(0)()

    def test_complete_shared_pipeline_without_browser_session_or_observer(self):
        with patch('personal_assistant.operator_identity.verify',side_effect=AssertionError('No fake browser proof')):
            job=self.start();self.workers()
            self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,job)['state'],'accepted')
            final,code=self.call('research_finalize')
            self.assertEqual(code,200,final);self.assertTrue(final.get('draft_id'),final)
            self.assertEqual(final['validation'],[]);self.assertFalse(final['needs_operator'])
            recovered,code=self.call('research_status')
            self.assertEqual(code,200,recovered);self.assertEqual(recovered['draft_id'],final['draft_id'])
        self.assertEqual(len(self.sim.requests),2)
        self.assertGreater(self.reads,4)
        self.assertEqual(self.sim.service.observers._entries,{})
        with self.sim.app.store.connect()as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='personal_sessions'").fetchone()
            self.assertFalse(exists and db.execute('SELECT count(*)FROM personal_sessions').fetchone()[0])

    def test_rehearsal_is_pending_until_manual_finite_root_admission(self):
        self.mode='rehearsal';self.preview('neural_review')
        out,code=self.call('research_start')
        self.assertEqual(code,200,out);self.assertTrue(out['pending_admission'])
        self.assertEqual(self.sim.requests,[])
        self.sim.service.admit(self.sim.app,self.body,max_calls=4,seconds=300)
        out,code=self.call('research_start');self.assertEqual(code,200,out)
        self.body['research_job_id']=out['research_job_id'];self.workers()
        status=self.sim.service.jobs.status(fixture.OWNER,out['research_job_id'])
        self.assertEqual(status['state'],'awaiting_root')
        self.sim.service.jobs.decide(out['research_job_id'],status['result_sha256'],accepted=True,reviewer='unit-root')
        final,code=self.call('research_finalize');self.assertEqual(code,200,final)
        self.assertTrue(final.get('draft_id'));self.assertEqual(len(self.sim.requests),2)

    def test_stopped_run_before_worker_has_no_model_request(self):
        job=self.start();self.live=False;self.workers()
        self.assertEqual(self.sim.requests,[])
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,job)['state'],'stopped')

    def test_permission_revoked_between_proposal_and_review_preserves_one_attempt(self):
        original=self.sim.provider
        def provider(payload,timeout):
            raw=original(payload,timeout)
            self.permission=False
            return raw
        self.sim.service.request=provider
        job=self.start();self.workers()
        self.assertEqual(len(self.sim.requests),1)
        status=self.sim.service.jobs.status(fixture.OWNER,job)
        self.assertEqual(status['state'],'stopped')
        self.assertEqual(status['calls_spent'],1)

    def test_stop_after_review_prevents_native_finalize_or_draft(self):
        self.start();self.workers();self.live=False
        out,code=self.call('research_finalize')
        self.assertEqual(code,403,out);self.assertFalse(out.get('draft_id'))
        self.assertEqual(len(self.sim.requests),2)

    def test_visual_task_diagnostic_reports_changed_media_without_source_values(self):
        cid = self.ctx['convId']
        self.ctx['messages'][0]['attachments'] = [dict(id='original-image', type='image')]
        self.sim.sync(cid)
        pixels = PNG

        def resolve(scope, descriptor):
            return dict(scope, message_id=descriptor['message_id'],
                        media_id=descriptor['media_id'], attachment_hash=descriptor['attachment_hash'],
                        data=pixels, mime='image/png', sha256=hashlib.sha256(pixels).hexdigest())

        service = self.sim.service
        service.media_resolver = resolve
        job = self.start()
        self.assertEqual(service.jobs.status(fixture.OWNER, job)['state'], 'queued')
        original = json.loads(service.jobs._file(job, 'input.json').read_bytes())
        self.assertIn('media', original['visual_task_fingerprints'])
        self.assertNotIn('_visual_task_fingerprints', original['payload'])
        pixels = PNG + b'changed-original'
        _, code = self.call('research_status')
        self.assertEqual(code, 403)
        events = service.jobs.audit_read(fixture.OWNER, job)['events']
        changes = [event['detail'] for event in events if event['event'] == 'visual_task_components_changed']
        self.assertEqual(changes, [dict(components=['media'])])
        self.assertNotIn('original-image', json.dumps(changes))
        self.assertEqual(self.sim.requests, [])

    def test_completed_draft_and_visual_purpose_do_not_cross_launch_generation(self):
        self.start();self.workers();final,code=self.call('research_finalize')
        self.assertEqual(code,200,final);self.assertTrue(final.get('draft_id'))
        original_tag=self.authority.launch_binding(self.body)
        self.generation=2;self.body['native_run']['generation']=2
        with self.assertRaises(ValueError):
            self.sim.service.check_native_launch(dict(native_launch_binding=original_tag,
                research_purpose='visual_observation_v1'),self.body)
        stale,code=self.call('research_status')
        self.assertEqual(code,403,stale);self.assertFalse(stale.get('draft_id'))
        self.assertEqual(len(self.sim.requests),2)

    def test_changed_native_generation_rejects_original_preview_without_spend(self):
        self.preview();self.generation=2;self.body['native_run']['generation']=2
        out,code=self.call('research_start')
        self.assertEqual(code,403,out);self.assertEqual(self.sim.requests,[])

    def test_transport_failure_and_new_launch_never_regenerate_old_source(self):
        self.sim.provider_mode='transport';job=self.start();self.workers()
        self.assertEqual(len(self.sim.requests),1)
        original=self.sim.service.jobs.status(fixture.OWNER,job)
        self.assertEqual(original['state'],'rejected')
        self.generation=2;self.run_id=str(uuid.uuid4())
        self.body=dict(owner=fixture.OWNER,ctx=self.ctx,native_run=dict(
            run_id=self.run_id,generation=2,operator_id=fixture.ACTOR))
        self.preview();out,code=self.call('research_start')
        self.assertEqual(code,403,out);self.assertEqual(out.get('code'),'research_prior_attempt')
        self.assertEqual(len(self.sim.requests),1)
        unchanged=self.sim.service.jobs.status(fixture.OWNER,job)
        self.assertEqual(unchanged['state'],original['state'])
        self.assertEqual(unchanged['result_sha256'],original['result_sha256'])
        self.assertEqual(unchanged['calls_spent'],original['calls_spent'])

    def test_recreated_service_resumes_exact_job_and_deadline_without_observer(self):
        job=self.start();original=self.sim.service.jobs.status(fixture.OWNER,job)
        self.sim.work.clear()
        old=self.sim.service
        self.sim.service=ResearchService(self.sim.root/'research',shared_lock=self.sim.root/'provider.lock',
            corpus_factory=old.corpus_factory,request=self.sim.provider,schedule=self.sim.work.append,
            native_context=old.native_context,proposal_enabled=True,owner_auto_enabled=True,
            auto_session_call_limit=12,native_authority=self.authority)
        self.sim.app.research=self.sim.service
        out,code=self.call('research_status');self.assertEqual(code,200,out)
        self.assertEqual(out['research_job_id'],job);self.assertEqual(out['deadline'],original['deadline'])
        self.assertEqual(self.sim.requests,[]);self.assertEqual(len(self.sim.work),1)
        self.workers();final,code=self.call('research_finalize');self.assertEqual(code,200,final)
        self.assertTrue(final.get('draft_id'));self.assertEqual(len(self.sim.requests),2)
        with self.sim.service.jobs.connect()as db:self.assertEqual(db.execute('SELECT count(*)FROM jobs').fetchone()[0],1)

    def test_expired_original_deadline_cannot_gain_time_from_native_authority(self):
        job=self.start();original=self.sim.service.jobs.status(fixture.OWNER,job)
        with patch.object(self.sim.service.jobs,'clock',return_value=original['deadline']+1):
            out,code=self.call('research_status')
        self.assertFalse(out.get('draft_id'));self.assertEqual(self.sim.requests,[])
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,job)['deadline'],original['deadline'])

    def test_existing_order_and_system_only_are_not_sent_to_a_model(self):
        self.ctx['crmRequestId']='1234567';self.sim.sync(self.ctx['convId'])
        out,code=self.call('preview',wording_mode='neural_auto')
        self.assertEqual(code,200,out);self.assertFalse(out.get('pending_model'),out)
        self.assertEqual(out['action'],'handoff');self.assertEqual(self.sim.requests,[])
        self.ctx=self.sim.add('native-system-only238','temporary')
        self.ctx['messages']=[dict(id='system',direction='system',sender_type='system',body='Диалог принят сотрудником')]
        self.sim.sync(self.ctx['convId']);self.body['ctx']=self.ctx
        out,code=self.call('preview',wording_mode='neural_auto')
        self.assertEqual(code,200,out);self.assertFalse(out.get('pending_model'),out)
        self.assertEqual(self.sim.requests,[])

    def test_new_client_wait_fences_old_source_without_a_provider_step(self):
        self.preview();self.ctx['messages'].append(dict(id='new-client',direction='in',sender_type='client',body='Секунду.'))
        self.sim.sync(self.ctx['convId'])
        out,code=self.call('research_start')
        self.assertEqual(code,200,out);self.assertTrue(out['refresh_preview'])
        self.assertEqual(self.sim.requests,[])

    def test_other_cid_waits_without_rotating_native_launch_or_reserving_calls(self):
        self.start()
        second=self.sim.add('native-second238','Нужно повесить полку.')
        self.body=dict(owner=fixture.OWNER,ctx=second,native_run=dict(
            run_id=self.run_id,generation=1,operator_id=fixture.ACTOR))
        self.preview();out,code=self.call('research_start')
        self.assertEqual(code,200,out);self.assertEqual(out['research_state'],'waiting_turn')
        self.assertEqual(self.sim.requests,[])

    def test_bad_native_binding_or_browser_fields_cannot_enter_native_preview(self):
        for extra in (dict(identity_proof='browser'),dict(browser_session='browser')):
            out,code=self.call('preview',wording_mode='neural_auto',**extra)
            self.assertEqual(code,403,out)
        self.version_override=['bad','bad','bad','bad']
        out,code=self.call('preview',wording_mode='neural_auto')
        self.assertEqual(code,403,out);self.assertEqual(self.sim.requests,[])

    def test_native_authority_requires_typed_dependency_and_current_source(self):
        for extra in (dict(native_authority=object(),native_context=self.sim.service.native_context),
                      dict(native_authority=self.authority),
                      dict(native_authority=self.authority,native_context=self.sim.service.native_context,identity=lambda body:{})):
            with self.assertRaises(ValueError):
                ResearchService(self.sim.root/'invalid',shared_lock=self.sim.root/'provider.lock',
                    corpus_factory=self.sim.service.corpus_factory,request=self.sim.provider,**extra)


if __name__=='__main__':unittest.main()
