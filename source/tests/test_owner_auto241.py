"""Owner-started API admission with synthetic identity, sources and transport."""
import os
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import auto_simulator231 as fixture
from assistant_store import digest
from research_workflow import ResearchService


class OwnerAuto241Tests(unittest.TestCase):
    def setUp(self):
        environment=patch.dict(os.environ,{},clear=False);environment.start();self.addCleanup(environment.stop)
        self.sim=fixture.Simulation();self.addCleanup(self.sim.tmp.cleanup)
        old=self.sim.service
        self.sim.service=ResearchService(self.sim.root/'research',shared_lock=self.sim.root/'provider.lock',
            corpus_factory=old.corpus_factory,request=self.sim.provider,schedule=self.sim.work.append,
            native_context=old.native_context,proposal_enabled=True,owner_auto_enabled=True,
            auto_session_call_limit=8)
        self.sim.app.research=self.sim.service
        self.ctx=self.sim.add('owner-auto241','Нужно повесить полку.')
        self.sim.identity();self.body=dict(owner=fixture.OWNER,ctx=self.ctx,**self.sim.last_identity)
        self.start()

    def start(self,auto=True):
        self.sim.identity();self.body.update(self.sim.last_identity)
        value,code=self.sim.app.handle(dict(self.body,action='personal_start'))
        self.assertEqual(code,200)
        if auto:
            value,code=self.sim.app.handle(dict(self.body,action='personal_mode',execution_mode='auto',
                confirmed=True,policy_ack=value['policy_version'],activation_nonce=value['activation_nonce'],client_version='2.8.31'))
            self.assertEqual(code,200);self.assertTrue(value['auto_enabled'])
        return value

    def preview(self,mode='neural_auto'):
        self.sim.identity();self.body.update(self.sim.last_identity)
        value,code=self.sim.app.handle(dict(self.body,action='preview',wording_mode=mode,
            _trusted_research_profile='sol_only'))
        self.assertEqual(code,200,value);self.assertTrue(value['pending_model'],value)
        self.body.update(request_id=value['request_id'],revision=value['revision'])
        return value

    def research(self,action='research_start',job=None):
        self.sim.identity();self.body.update(self.sim.last_identity)
        return self.sim.app.handle(dict(self.body,action=action,**({'research_job_id':job}if job else{})))

    def jobs(self):
        with self.sim.service.jobs.connect()as db:return list(db.execute('SELECT *FROM grants'))

    def next_context(self,cid):
        self.ctx=self.sim.add(cid,'Нужно повесить полку.');self.body['ctx']=self.ctx
        self.body.pop('request_id',None);self.body.pop('revision',None)

    def finish(self):
        self.preview();out,code=self.research();self.assertEqual(code,200,out)
        self.sim.command(dict(op='run_workers'))
        final,code=self.research('research_finalize',out['research_job_id']);self.assertEqual(code,200,final)
        self.assertTrue(final.get('draft_id'),final)
        return out['research_job_id']

    def test_owner_started_auto_admits_once_and_separate_review_reaches_native_finalize(self):
        self.preview();out,code=self.research();self.assertEqual(code,200,out)
        job=out['research_job_id'];self.assertTrue(job);self.assertEqual(len(self.jobs()),1)
        repeated,code=self.research('research_status',job);self.assertEqual(code,200);self.assertEqual(len(self.jobs()),1)
        self.sim.command(dict(op='run_workers'))
        status=self.sim.service.jobs.status(fixture.OWNER,job);self.assertEqual(status['state'],'accepted')
        final,code=self.research('research_finalize',job);self.assertEqual(code,200,final)
        self.assertTrue(final['draft_id']);self.assertFalse(final['needs_operator']);self.assertEqual(final['validation'],[])
        self.assertEqual(len(self.sim.requests),2)
        events=self.sim.service.jobs.audit_read(fixture.OWNER,job)['events']
        self.assertIn('machine_accepted',[r['event']for r in events]);self.assertNotIn('root_accepted',[r['event']for r in events])

    def test_rehearsal_still_waits_for_manual_root_admission(self):
        self.start(auto=False);self.preview('neural_review');out,code=self.research()
        self.assertEqual(code,200);self.assertTrue(out['pending_admission']);self.assertEqual(self.jobs(),[])
        self.assertEqual(self.sim.requests,[])

    def test_stop_then_restart_cannot_admit_the_old_preview(self):
        self.preview();self.sim.app.handle(dict(self.body,action='personal_stop'));self.start()
        out,code=self.research();self.assertEqual(code,403,out);self.assertEqual(self.jobs(),[])
        self.assertEqual(self.sim.requests,[])

    def test_session_stop_before_worker_prevents_any_model_call(self):
        self.preview();out,code=self.research();self.assertEqual(code,200)
        self.sim.app.handle(dict(self.body,action='personal_stop'));self.sim.command(dict(op='run_workers'))
        self.assertEqual(self.sim.requests,[])
        self.assertNotEqual(self.sim.service.jobs.status(fixture.OWNER,out['research_job_id'])['state'],'accepted')

    def test_new_client_message_before_admission_refreshes_without_spending_a_call(self):
        self.preview();self.ctx['messages'].append(dict(id='new',direction='in',sender_type='client',body='Секунду.'))
        self.sim.sync(self.ctx['convId']);out,code=self.research();self.assertEqual(code,200,out)
        self.assertTrue(out['refresh_preview']);self.assertEqual(self.jobs(),[]);self.assertEqual(self.sim.requests,[])

    def test_other_cids_wait_without_reserving_a_deadline_or_call_budget(self):
        self.preview();first,code=self.research();self.assertEqual(code,200)
        self.ctx=self.sim.add('second241','Нужно повесить полку.');self.body['ctx']=self.ctx
        self.body.pop('request_id');self.body.pop('revision');self.preview();out,code=self.research()
        self.assertEqual(code,200,out);self.assertEqual(out['research_state'],'waiting_turn')
        self.assertTrue(out['pending_research']);self.assertFalse(out.get('research_job_id'));self.assertEqual(len(self.jobs()),1)

    def test_same_unknown_prefix_never_regenerates_after_new_owner_session(self):
        self.preview();out,code=self.research();self.assertEqual(code,200)
        self.sim.provider_mode='transport';self.sim.command(dict(op='run_workers'))
        self.assertEqual(len(self.sim.requests),1)
        self.sim.app.handle(dict(self.body,action='personal_stop'));self.body.pop('request_id');self.body.pop('revision')
        self.start();self.preview();result,code=self.research();self.assertEqual(code,403,result)
        self.assertEqual(len(self.sim.requests),1);self.assertEqual(len(self.jobs()),1)

    def test_auto_configuration_rejects_missing_authenticated_native_dependency(self):
        with self.assertRaises(ValueError):
            ResearchService(self.sim.root/'bad',shared_lock=self.sim.root/'provider.lock',
                corpus_factory=self.sim.service.corpus_factory,request=self.sim.provider,schedule=self.sim.work.append,
                owner_auto_enabled=True)

    def test_finite_allowance_covers_nonconverting_chats_and_does_not_refill_on_poll(self):
        self.finish();self.next_context('budget-second241');self.finish()
        status,code=self.sim.app.handle(dict(self.body,action='personal_status'));self.assertEqual(code,200)
        self.assertEqual(status['research_auto']['reserved_calls'],8)
        self.assertEqual(status['research_auto']['remaining_calls'],0)
        self.next_context('budget-third241');self.preview();out,code=self.research()
        self.assertEqual(code,403,out);self.assertEqual(out['control_reason'],'auto_allowance_exhausted')
        self.assertIn('Допуск API',out['error']);self.assertEqual(len(self.jobs()),2)
        self.assertEqual(len(self.sim.requests),4)

    def test_restarting_service_recovers_the_same_grant_and_job(self):
        self.preview();out,code=self.research();self.assertEqual(code,200)
        old=self.sim.service;self.sim.work.clear()
        self.sim.service=ResearchService(self.sim.root/'research',shared_lock=self.sim.root/'provider.lock',
            corpus_factory=old.corpus_factory,request=self.sim.provider,schedule=self.sim.work.append,
            native_context=old.native_context,proposal_enabled=True,owner_auto_enabled=True,auto_session_call_limit=8)
        self.sim.app.research=self.sim.service
        recovered,code=self.research('research_status',out['research_job_id']);self.assertEqual(code,200,recovered)
        self.assertEqual(recovered['research_job_id'],out['research_job_id']);self.assertEqual(len(self.jobs()),1)
        status,code=self.sim.app.handle(dict(self.body,action='personal_status'))
        self.assertEqual(status['research_auto']['reserved_calls'],4)
        self.sim.command(dict(op='run_workers'));self.assertEqual(len(self.sim.requests),2)

    def test_other_staff_assignment_never_creates_an_automatic_grant(self):
        self.preview();self.ctx['assigneeId']='33333333-3333-4333-8333-333333333333';self.sim.sync(self.ctx['convId'])
        out,code=self.research();self.assertEqual(code,200,out);self.assertTrue(out['refresh_preview'])
        self.assertEqual(self.jobs(),[]);self.assertEqual(self.sim.requests,[])

    def test_existing_order_appearing_before_admission_retires_the_preview(self):
        self.preview();self.ctx['crmRequestId']='1234567';self.sim.sync(self.ctx['convId'])
        out,code=self.research();self.assertEqual(code,200,out);self.assertTrue(out['refresh_preview'])
        self.assertEqual(self.jobs(),[]);self.assertEqual(self.sim.requests,[])

    def test_held_conversation_does_not_mint_an_automatic_grant(self):
        self.preview();scope='assistant:'+digest(fixture.OWNER)
        self.sim.app.store.observe(scope,self.ctx['convId'],self.body['revision'],takeover=True)
        out,code=self.research();self.assertEqual(code,403,out);self.assertEqual(self.jobs(),[])

    def test_disabled_trusted_policy_cannot_be_enabled_by_browser_fields(self):
        self.sim.service.owner_auto_enabled=False
        self.preview();self.body['owner_auto_enabled']=True
        out,code=self.research();self.assertIn(code,(200,403));self.assertEqual(self.jobs(),[])
        self.assertEqual(self.sim.requests,[])

    def test_manual_admission_under_owner_auto_configuration_still_requires_root(self):
        self.preview();self.sim.service.admit(self.sim.app,self.body,max_calls=4,seconds=300)
        out,code=self.research();self.assertEqual(code,200,out)
        self.sim.command(dict(op='run_workers'))
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,out['research_job_id'])['state'],'awaiting_root')
        final,code=self.research('research_finalize',out['research_job_id']);self.assertEqual(code,403,final)

    def test_one_semantic_rejection_parks_the_case_but_two_stop_this_launch(self):
        self.sim.provider_mode='review_rejected';self.preview();out,code=self.research();self.assertEqual(code,200)
        self.sim.command(dict(op='run_workers'))
        self.next_context('semantic-second241');self.preview();second,code=self.research();self.assertEqual(code,200,second)
        self.sim.command(dict(op='run_workers'))
        self.next_context('semantic-third241');self.preview();third,code=self.research();self.assertEqual(code,403,third)
        self.assertEqual(third['control_reason'],'auto_session_blocked');self.assertEqual(len(self.jobs()),2)

    def test_hard_error_blocks_further_cases_in_this_launch(self):
        self.preview();out,code=self.research();self.assertEqual(code,200)
        self.sim.provider_mode='transport';self.sim.command(dict(op='run_workers'))
        self.next_context('hard-next241');self.preview();out,code=self.research();self.assertEqual(code,403,out)
        self.assertEqual(out['control_reason'],'auto_session_blocked');self.assertEqual(len(self.sim.requests),1)

    def test_stop_after_machine_approval_still_blocks_native_finalize(self):
        self.preview();out,code=self.research();self.assertEqual(code,200)
        self.sim.command(dict(op='run_workers'))
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,out['research_job_id'])['state'],'accepted')
        self.sim.app.handle(dict(self.body,action='personal_stop'))
        final,code=self.research('research_finalize',out['research_job_id']);self.assertEqual(code,403,final)
        self.assertFalse(final['reply']);self.assertNotIn('draft_id',final)

    def test_parallel_observers_cannot_mint_two_grants_or_workers(self):
        from concurrent.futures import ThreadPoolExecutor
        self.preview();body=dict(self.body,action='research_start')
        with ThreadPoolExecutor(max_workers=2)as pool:
            results=list(pool.map(lambda _:self.sim.app.handle(body),range(2)))
        self.assertTrue(all(code==200 for _,code in results),results)
        self.assertEqual(len(self.jobs()),1);self.assertEqual(len(self.sim.work),1)
        self.assertEqual(len({value['research_job_id']for value,_ in results}),1)

    def test_cancelled_unstarted_worker_is_a_noop_and_other_case_can_continue(self):
        self.preview();out,code=self.research();self.assertEqual(code,200)
        cancelled,code=self.research('research_cancel',out['research_job_id']);self.assertEqual(code,409,cancelled)
        self.assertEqual(cancelled['research_state'],'cancelled')
        self.sim.command(dict(op='run_workers'));self.assertEqual(self.sim.requests,[])
        self.next_context('after-cancel241');self.preview();out,code=self.research();self.assertEqual(code,200,out)
        self.assertTrue(out['research_job_id']);self.assertEqual(len(self.jobs()),2)

    def test_knowledge_or_runtime_change_is_not_a_new_customer_turn_after_unknown(self):
        self.preview();out,code=self.research();self.assertEqual(code,200)
        self.sim.provider_mode='transport';self.sim.command(dict(op='run_workers'))
        self.sim.app.handle(dict(self.body,action='personal_stop'));self.body.pop('request_id');self.body.pop('revision')
        self.start()
        replacement=digest(['new-code-and-memory-version',self.sim.service.code_version])
        with patch.object(self.sim.service,'code_version',replacement),patch.object(self.sim.service,'_runtime_version',return_value=replacement):
            self.preview();out,code=self.research();self.assertEqual(code,403,out)
            self.assertEqual(out['control_reason'],'auto_prefix_prior_attempt')
        self.assertEqual(len(self.sim.requests),1);self.assertEqual(len(self.jobs()),1)

    def test_expired_owner_lease_prevents_automatic_admission(self):
        self.preview()
        with self.sim.app.store.connect()as db:db.execute('UPDATE personal_sessions SET expires=0')
        out,code=self.research();self.assertEqual(code,403,out);self.assertEqual(self.jobs(),[])

    def test_source_change_after_machine_approval_prevents_native_finalize(self):
        self.preview();out,code=self.research();self.assertEqual(code,200)
        self.sim.command(dict(op='run_workers'))
        self.ctx['messages'].append(dict(id='changed-after-model',direction='in',sender_type='client',body='Секунду, пока не нужно.'))
        self.sim.sync(self.ctx['convId']);final,code=self.research('research_finalize',out['research_job_id'])
        self.assertEqual(code,403,final);self.assertFalse(final['reply']);self.assertNotIn('draft_id',final)

    def test_automatic_settings_are_typed_and_do_not_allow_a_provider_fallback(self):
        for changes in ({'owner_auto_enabled':'yes'},{'auto_session_call_limit':True},
                        {'auto_session_call_limit':3},{'auto_session_call_limit':4097},{'profile':'sol_astra'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                ResearchService(self.sim.root/'invalid-settings',shared_lock=self.sim.root/'provider.lock',
                    corpus_factory=self.sim.service.corpus_factory,request=self.sim.provider,schedule=self.sim.work.append,
                    native_context=self.sim.service.native_context,**dict({'owner_auto_enabled':True},**changes))

    def invalid_native_reply(self,cid=None):
        if cid:self.next_context(cid)
        self.preview()
        self.sim.scripted_candidates.append(dict(reply='Здравствуйте! Из какого материала стена в ванной?',
            intent='Клиент просит повесить полку.',meaning='Нужно повесить полку.',note='Материал стены ещё не указан.'))
        started,code=self.research();self.assertEqual(code,200,started);job=started['research_job_id']
        self.sim.command(dict(op='run_workers'))
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,job)['state'],'accepted')
        final,code=self.research('research_finalize',job);self.assertEqual(code,200,final)
        self.assertTrue(final['needs_operator']);self.assertTrue(final['validation']);self.assertFalse(final['reply'])
        return job,final

    def test_separate_review_does_not_override_native_guards_and_two_native_failures_stop(self):
        self.invalid_native_reply();self.invalid_native_reply('native-second241')
        self.next_context('native-third241');self.preview();out,code=self.research();self.assertEqual(code,403,out)
        self.assertEqual(out['control_reason'],'auto_session_blocked');self.assertEqual(len(self.sim.requests),4)

    def test_original_native_rejection_can_be_recovered_without_regeneration_or_double_count(self):
        job,final=self.invalid_native_reply()
        recovered,code=self.research('research_status',job);self.assertEqual(code,200,recovered)
        self.assertTrue(recovered['cached']);self.assertTrue(recovered['needs_operator']);self.assertFalse(recovered['reply'])
        self.sim.service._automatic_native_outcome(job,final)
        with self.sim.service.jobs.connect()as db:
            self.assertEqual(db.execute('SELECT consecutive_failures FROM auto_sessions').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*)FROM auto_native_outcomes').fetchone()[0],1)
        self.assertEqual(len(self.sim.requests),2)

    def test_automatic_form_keeps_the_existing_projection_and_crm_validation(self):
        cid='automatic-form241';self.sim.command(dict(op='ready',cid=cid))
        self.ctx=self.sim.contexts[cid];self.body['ctx']=self.ctx
        self.sim.service.intake_form_enabled=True
        out,code=self.sim.app.handle(dict(self.body,action='form_preview',wording_mode='neural_auto',_trusted_research_profile='sol_only'))
        self.assertEqual(code,200,out);self.assertEqual(out.get('research_purpose'),'intake_form_v1')
        self.body.update(request_id=out['request_id'],revision=out['revision'])
        started,code=self.research();self.assertEqual(code,200,started)
        self.sim.command(dict(op='run_workers'));job=started['research_job_id']
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,job)['state'],'accepted')
        final,code=self.research('research_finalize',job);self.assertEqual(code,200,final)
        self.assertTrue(final['intake_form_ready']);self.assertEqual(len(self.sim.requests),2)
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,job)['max_calls'],2)
        proposal=self.sim.command(dict(op='proposal',cid=cid));proposal['lead'].update(copy.deepcopy(final['form_extraction']['lead']))
        proposal['lead']['service_comment']='https://lead.test/chats/'+cid;proposal['form_reference']=final['form_reference']
        checked,code=self.sim.app.handle(dict(self.body,action='personal_crm_check',mine_count=0,proposal=proposal))
        self.assertEqual(code,200,checked);self.assertTrue(checked['ready'],checked)
        self.assertFalse(final['can_send_or_create'])

    def test_automatic_visual_research_reviews_the_same_original_pixels_and_caches_only_after_finalize(self):
        import test_research_media204 as media_fixture
        import test_research_vision214 as vision_fixture
        pixels=media_fixture.PNG
        self.sim.service.native_context.client.image=lambda *args:dict(data=pixels,mime='image/png',sha256=hashlib.sha256(pixels).hexdigest())
        self.ctx['messages'].append(dict(id='photo241',direction='in',sender_type='client',body='',attachments=[dict(id='p241',type='image')]))
        self.sim.sync(self.ctx['convId'])
        def provider(payload,timeout):
            self.sim.requests.append(payload);role=json.loads(payload['instructions'])['role']
            current=json.loads(payload['input'][-1]['content'][0]['text'])['current']
            output=vision_fixture.observation(current['media']['images'])if role=='research'else dict(kind='review',approved=True,
                violations=[],checked_claims=[0],basis=['current:photo241'])
            return json.dumps(dict(id='automatic-vision241-'+role,model='gpt-6.1-sol',service_tier='default',status='completed',usage=None,
                output=[dict(type='message',role='assistant',status='completed',content=[dict(type='output_text',text=json.dumps(output))])])).encode()
        self.sim.service.request=provider
        self.preview();started,code=self.research();self.assertEqual(code,200,started)
        self.sim.command(dict(op='run_workers'));job=started['research_job_id']
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,job)['state'],'accepted')
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,job)['max_calls'],2)
        final,code=self.research('research_finalize',job);self.assertEqual(code,200,final)
        self.assertTrue(final['visual_observation_ready']);self.assertFalse(final['reply']);self.assertEqual(len(self.sim.requests),2)
        def images(p):return [x for row in p['input']for x in row.get('content',[])if x.get('type')=='input_image']
        self.assertEqual(images(self.sim.requests[0]),images(self.sim.requests[1]));self.assertTrue(images(self.sim.requests[0]))


if __name__=='__main__':unittest.main()
