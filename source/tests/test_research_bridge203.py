import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import assistant_policy as policy
import assistant_catalog
from assistant_store import Store, digest
from extension_assistant import Assistant
from experienced_dialogues import Reader, create_index
from research_pipeline import Corpus, schema_matches
from research_workflow import ResearchService
from test_assistant import context, message
import test_research_pipeline218 as fixtures


class ResearchBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='owner',LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start();self.addCleanup(env.stop)
        self.app=Assistant(Store(Path(self.tmp.name)/'assistant.sqlite3'))
        self.ctx=context([message('Нужно повесить полку.',mid='client')],dir='mnc',city='Чита',itemTitle='Мастер на час')
        self.prepared,code=self.app.handle(dict(owner='owner',action='preview',ctx=self.ctx,wording_mode='neural_review'))
        self.assertEqual(code,200);self.assertTrue(self.prepared['pending_model'])
        self.task=json.loads(self.prepared['model_task']['task'])
        source=fixtures.ResearchTests().record('old-a')
        self.archive=Path(self.tmp.name)/'archive.sqlite3';create_index(self.archive,[source],approved_cids=['old-a'])
        def corpus():return Corpus(Reader(self.archive),policy.registry()['sources']+assistant_catalog.data()['owner_amendments'],allowed_cids=['old-a'],guard=lambda ids:None,versions=lambda:'stable')
        self.work=[];self.requests=[];self.identity=dict(principal_id='admin',operator_id='operator')
        self.scope='assistant:'+digest('owner')
        verify=patch('personal_assistant.operator_identity.verify',side_effect=lambda *args,**kwargs:self.identity)
        verify.start();self.addCleanup(verify.stop)
        self.body=dict(owner='owner',ctx=self.ctx,request_id=self.prepared['request_id'],revision=self.prepared['revision'],identity_proof='verified-by-test-verifier')
        self.service=ResearchService(Path(self.tmp.name)/'research',shared_lock=Path(self.tmp.name)/'shared.lock',
            corpus_factory=corpus,request=self.provider,identity=lambda body:self.identity,
            schedule=lambda fn:self.work.append(fn))
        self.app.research=self.service

    def provider(self,payload,timeout):
        self.requests.append(payload);role=json.loads(payload['instructions'])['role']
        basis=['current:client']
        if role=='review':out=dict(kind='review',approved=True,violations=[],checked_claims=[0],basis=basis)
        else:
            candidate=dict(reply=self.task['decision']['next_question']['question'],needs_operator=False,
                context_review=dict(last_intent='Клиент просит повесить полку.',latest_client_meaning='Нужно повесить полку.',selected_step_fits=True,evidence_ids=['client'],note='Материал стены ещё не указан.'))
            out=dict(kind='draft',reply=candidate['reply'],candidate=candidate,evidence_ids=['client'],basis=basis,
                claims=[dict(scope='question',text=candidate['reply'],basis=basis)])
        return json.dumps(dict(id='resp-'+str(len(self.requests)),model='gpt-6.1-sol',status='completed',service_tier='default',
            usage=dict(input_tokens=1000,output_tokens=200,input_tokens_details=dict(cached_tokens=0,cache_write_tokens=0)),
            output=[dict(type='message',role='assistant',status='completed',content=[dict(type='output_text',text=json.dumps(out,ensure_ascii=False))])]),ensure_ascii=False).encode()

    def call(self,action,**extra):
        return self.app.handle(dict(self.body,action=action,**extra))

    def start(self):
        self.service.admit(self.app,self.body,max_calls=4,seconds=300)
        out,code=self.call('research_start');self.assertEqual(code,200);self.assertTrue(out['pending_research'])
        self.assertEqual(self.requests,[]);self.assertEqual(len(self.work),1)
        self.work.pop(0)()
        return out['research_job_id']

    def test_default_service_is_disabled_and_browser_cannot_configure_it(self):
        app=Assistant(self.app.store)
        out,code=app.handle(dict(self.body,action='research_start',profile='sol_only',api_key='do-not-use'))
        self.assertEqual(code,403);self.assertEqual(out['code'],'research_disabled');self.assertEqual(self.requests,[])

    def test_browser_cannot_admit_calls_or_supply_candidate_or_model(self):
        out,code=self.call('research_start',max_calls=20,grant_id='mine',candidate={'reply':'fake'},model='gpt-6-luna')
        self.assertEqual(code,403);self.assertEqual(self.requests,[]);self.assertEqual(self.work,[])

    def test_start_is_nonblocking_and_requires_fresh_identity_and_current_request(self):
        self.service.admit(self.app,self.body,max_calls=4,seconds=300)
        self.identity=None
        out,code=self.call('research_start');self.assertEqual(code,403);self.assertEqual(self.requests,[])

    def test_actual_preview_research_root_accept_and_legacy_finalize(self):
        job=self.start();out,code=self.call('research_status',research_job_id=job)
        self.assertEqual(code,200);self.assertEqual(out['research_state'],'awaiting_root')
        self.assertEqual(len(self.requests),2);self.assertEqual(out['reply'],'')
        _,payload=self.app.store.request(self.scope,self.prepared['request_id']);self.assertNotIn('draft_id',payload)
        self.service.jobs.decide(job,out['result_sha256'],accepted=True,reviewer='root')
        final,code=self.call('research_finalize',research_job_id=job)
        self.assertEqual(code,200);self.assertEqual(final['validation'],[])
        self.assertEqual(final['context_review']['last_intent'],'Клиент просит повесить полку.')
        self.assertFalse(final['auto_enabled']);self.assertTrue(final['requires_operator_review'])
        self.assertEqual(self.app.store.request(self.scope,self.prepared['request_id'])[0],'done')

    def test_request_context_full_messages_once_and_server_native_schema_is_exact(self):
        job=self.start();packet=self.requests[0];dynamic=json.loads(packet['input'][-1]['content'][0]['text'])
        self.assertEqual(len(dynamic['current']['messages']),1)
        self.assertNotIn('conversation',dynamic['current']['candidate_contract']['task'])
        original=self.prepared['model_task']['response_format']['schema']
        self.assertEqual(dynamic['current']['candidate_contract']['schema'],original)
        wire=packet['text']['format']['schema']['properties']['candidate']
        # The exact native contract remains bound. Only its redundant common
        # parent is omitted on the wire; every conditional branch is identical.
        self.assertEqual(wire['anyOf'],original['anyOf'])
        self.assertEqual(set(wire),{'anyOf'})
        candidate=json.loads(self.service.jobs._file(job,'result.json').read_bytes())['candidate']
        self.assertTrue(schema_matches(candidate,original));self.assertTrue(schema_matches(candidate,wire))
        veto=copy.deepcopy(candidate);veto.update(reply='',needs_operator=True);veto['context_review']['selected_step_fits']=False
        self.assertTrue(schema_matches(veto,original));self.assertTrue(schema_matches(veto,wire))
        for invalid in (dict(candidate,reply='Выдуманная стоимость 9999 рублей'),dict(candidate,extra='not allowed'),
                        dict(candidate,needs_operator=True)):
            self.assertFalse(schema_matches(invalid,original));self.assertFalse(schema_matches(invalid,wire))

    def test_both_root_and_model_review_cannot_bypass_old_client_goal_validator(self):
        original=self.provider
        def wrong(payload,timeout):
            raw=json.loads(original(payload,timeout))
            if json.loads(payload['instructions'])['role']=='research':
                value=json.loads(raw['output'][0]['content'][0]['text'])
                value['candidate']['context_review']['last_intent']='Запрос информации о материале стен.'
                raw['output'][0]['content'][0]['text']=json.dumps(value,ensure_ascii=False)
            return json.dumps(raw,ensure_ascii=False).encode()
        self.service.request=wrong;job=self.start();status,_=self.call('research_status',research_job_id=job)
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='root')
        final,code=self.call('research_finalize',research_job_id=job)
        self.assertEqual(code,200);self.assertEqual(final['reply'],'');self.assertIn('staff_question_as_client_goal',final['validation'])

    def test_fabricated_price_is_rejected_by_original_wire_schema(self):
        original=self.provider
        def wrong(payload,timeout):
            raw=json.loads(original(payload,timeout))
            if json.loads(payload['instructions'])['role']=='research':
                value=json.loads(raw['output'][0]['content'][0]['text'])
                value['candidate']['reply']='Работа будет стоить 9999 рублей. Из какого материала стена?'
                value['reply']=value['candidate']['reply']
                raw['output'][0]['content'][0]['text']=json.dumps(value,ensure_ascii=False)
            return json.dumps(raw,ensure_ascii=False).encode()
        self.service.request=wrong;job=self.start();status,_=self.call('research_status',research_job_id=job)
        self.assertEqual(status['research_state'],'rejected')
        self.assertEqual(len(self.requests),1)

    def test_native_unknown_evidence_id_rejected_before_root_acceptance(self):
        original=self.provider
        def wrong(payload,timeout):
            raw=json.loads(original(payload,timeout))
            if json.loads(payload['instructions'])['role']=='research':
                value=json.loads(raw['output'][0]['content'][0]['text'])
                value['candidate']['context_review']['evidence_ids']=['not-current-client']
                raw['output'][0]['content'][0]['text']=json.dumps(value,ensure_ascii=False)
            return json.dumps(raw,ensure_ascii=False).encode()
        self.service.request=wrong;job=self.start();status,_=self.call('research_status',research_job_id=job)
        self.assertEqual(status['research_state'],'rejected')
        with self.assertRaises(ValueError):self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='root')

    def test_operator_takeover_context_change_and_actor_change_stop_completion(self):
        job=self.start();status,_=self.call('research_status',research_job_id=job)
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='root')
        self.identity=dict(principal_id='admin',operator_id='another')
        out,code=self.call('research_finalize',research_job_id=job)
        self.assertEqual(code,403);self.assertEqual(out['reply'],'');self.assertEqual(len(self.requests),2)

    def test_changed_client_message_and_other_owner_job_do_not_leak_draft(self):
        job=self.start();self.ctx['messages'].append(message('Секунду, подождите.',mid='new'))
        out,code=self.call('research_status',research_job_id=job)
        self.assertEqual(code,403);self.assertEqual(out['reply'],'')
        out,code=self.app.handle(dict(self.body,owner='another',action='research_status',research_job_id=job))
        self.assertEqual(code,403);self.assertNotIn('result_sha256',out)

    def test_root_denial_closes_only_own_pending_request_without_native_acceptance(self):
        job=self.start();status,_=self.call('research_status',research_job_id=job)
        self.service.jobs.decide(job,status['result_sha256'],accepted=False,reviewer='root')
        out,code=self.call('research_status',research_job_id=job)
        self.assertEqual(out['reply'],'');self.assertEqual(self.app.store.request(self.scope,self.prepared['request_id'])[0],'done')
        self.assertEqual(len(self.requests),2)

    def test_new_message_during_generation_fences_worker_before_another_call(self):
        original=self.provider
        def arrival(payload,timeout):
            raw=original(payload,timeout)
            self.ctx['messages'].append(message('Секунду, подождите.',mid='new'))
            job=next(iter(self.service.scheduled))
            self.call('research_status',research_job_id=job)
            return raw
        self.service.request=arrival;job=self.start()
        self.assertEqual(len(self.requests),1)
        self.assertNotIn(self.service.jobs.status('owner',job)['state'],('running','queued','awaiting_root'))
        self.assertEqual(self.app.store.request(self.scope,self.prepared['request_id'])[0],'done')

    def test_current_operator_takeover_invalidates_root_approved_draft(self):
        job=self.start();status,_=self.call('research_status',research_job_id=job)
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='root')
        self.app.store.observe(self.scope,self.prepared['chat_id'],self.prepared['revision'],takeover=True)
        final,code=self.call('research_finalize',research_job_id=job)
        self.assertEqual(code,403);self.assertEqual(final['reply'],'')

    def test_lost_finalize_observer_reconciles_same_existing_draft(self):
        job=self.start();status,_=self.call('research_status',research_job_id=job)
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='root')
        original=self.app.finalize;calls=[]
        def died(scope,body):calls.append(body);original(scope,body);raise SystemExit('lost observer')
        self.app.finalize=died
        with self.assertRaises(SystemExit):self.call('research_finalize',research_job_id=job)
        out,code=self.call('research_finalize',research_job_id=job)
        self.assertEqual(code,200);self.assertTrue(out['draft_id']);self.assertEqual(len(calls),1)

    def test_cancel_uses_bound_request_and_does_not_close_another_request(self):
        job=self.start();wrong=dict(self.body,request_id='different-request',action='research_cancel',research_job_id=job)
        out,code=self.app.handle(wrong)
        self.assertEqual(code,403)
        self.assertEqual(self.service.jobs.status('owner',job)['state'],'awaiting_root')

    def test_repeated_start_does_not_relaunch_completed_research_or_discard_root_candidate(self):
        job=self.start();out,code=self.call('research_start')
        self.assertEqual(code,200);self.assertEqual(out['research_job_id'],job)
        self.assertEqual(out['research_state'],'awaiting_root');self.assertEqual(self.work,[])
        self.assertEqual(len(self.requests),2)
        self.service.jobs.decide(job,out['result_sha256'],accepted=True,reviewer='root')
        final,_=self.call('research_finalize',research_job_id=job)
        repeated,code=self.call('research_start')
        self.assertEqual(code,200);self.assertEqual(repeated['draft_id'],final['draft_id'])
        self.assertEqual(self.work,[]);self.assertEqual(len(self.requests),2)

    def test_owner_can_read_search_and_basis_journal_without_resuming_work(self):
        job=self.start();out,code=self.call('research_audit',research_job_id=job)
        self.assertEqual(code,200);self.assertTrue(out['chain_valid'])
        events=[e['event']for e in out['events']]
        for name in ('context_observed','source_tool_requested','source_tool_result','decision_basis','review_result'):
            self.assertIn(name,events)
        self.ctx['messages'].append(message('Пока не нужно.',mid='new'))
        before=len(self.requests);out,code=self.call('research_audit',research_job_id=job)
        self.assertEqual(code,200);self.assertEqual(len(self.requests),before)
        bad,code=self.app.handle(dict(self.body,owner='another',action='research_audit',research_job_id=job))
        self.assertEqual(code,403);self.assertNotIn('events',bad)

    def test_expired_root_wait_closes_pending_request_without_resetting_deadline(self):
        job=self.start();status=self.service.jobs.status('owner',job)
        self.service.jobs.clock=lambda:status['deadline']+1
        out,code=self.call('research_status',research_job_id=job)
        self.assertEqual(out['research_state'],'stopped');self.assertEqual(len(self.requests),2)
        self.assertEqual(self.app.store.request(self.scope,self.prepared['request_id'])[0],'done')

    def test_other_observer_does_not_stop_same_live_worker(self):
        self.service.admit(self.app,self.body,max_calls=4,seconds=300)
        out,_=self.call('research_start');job=out['research_job_id']
        with self.service.jobs.session_worker(job):
            self.service.run(self.app,self.body,job)
            self.assertEqual(self.service.jobs.status('owner',job)['state'],'queued')
            self.assertEqual(self.requests,[])

    def test_explicit_research_profile_does_not_reuse_old_provider_draft(self):
        candidate=dict(reply=self.task['decision']['next_question']['question'],needs_operator=False,
            context_review=dict(last_intent='Клиент просит повесить полку.',latest_client_meaning='Нужно повесить полку.',
                selected_step_fits=True,evidence_ids=['client'],note='Материал стены ещё не указан.'))
        self.app.finalize(self.scope,dict(request_id=self.prepared['request_id'],revision=self.prepared['revision'],candidate=candidate))
        out,code=self.app.handle(dict(owner='owner',action='preview',ctx=self.ctx,wording_mode='neural_review',_trusted_research_profile='sol_only'))
        self.assertEqual(code,200);self.assertTrue(out['pending_model'])
        self.assertNotEqual(out['request_id'],self.prepared['request_id'])

    def printer(self,invented=False):
        import test_printer_item_newness175 as printer_fixture
        self.ctx=context([message('Принтер плохо печатает цветом, картридж новый.',mid='client')],dir='kp',city='Коломна',itemTitle='Ремонт принтеров')
        self.ctx['convId']='synthetic-conditional-research'
        self.prepared,code=self.app.handle(dict(owner='owner',action='preview',ctx=self.ctx,wording_mode='neural_review'))
        self.assertEqual(code,200);self.task=json.loads(self.prepared['model_task']['task'])
        self.body.update(ctx=self.ctx,request_id=self.prepared['request_id'],revision=self.prepared['revision'])
        original=self.provider
        def provider(payload,timeout):
            value=json.loads(original(payload,timeout))
            if json.loads(payload['instructions'])['role']=='research':
                candidate=printer_fixture.PrinterAttributeNativeTests.candidate(self,self.task)
                candidate['context_review']['evidence_ids']=['client']
                if invented:candidate['context_review']['last_intent']='Помощь с принтером и установленным новым картриджем.'
                out=json.loads(value['output'][0]['content'][0]['text'])
                out.update(candidate=candidate,reply=candidate['reply'],claims=[dict(scope='question',text=candidate['reply'],basis=['current:client'])])
                value['output'][0]['content'][0]['text']=json.dumps(out,ensure_ascii=False)
            return json.dumps(value,ensure_ascii=False).encode()
        self.service.request=provider
        return self.start()

    def test_full_conditional_receipts_survive_source_pipeline_and_legacy_finalize(self):
        job=self.printer();status,_=self.call('research_status',research_job_id=job)
        self.assertEqual(status['research_state'],'awaiting_root')
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='root')
        final,code=self.call('research_finalize',research_job_id=job)
        self.assertEqual(code,200);self.assertEqual(final['validation'],[])
        self.assertIn('item_fitment_review',final['context_review'])
        self.assertFalse(final['context_review']['item_fitment_review']['work_execution_verified'])

    def test_correct_receipts_do_not_license_free_invented_installation_even_after_two_approvals(self):
        job=self.printer(invented=True);status,_=self.call('research_status',research_job_id=job)
        self.assertEqual(status['research_state'],'awaiting_root')
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='root')
        final,code=self.call('research_finalize',research_job_id=job)
        self.assertEqual(code,200);self.assertEqual(final['reply'],'')
        self.assertIn('item_fitment_not_observed',final['validation'])

    def test_research_draft_is_actor_bound_even_if_original_preview_had_no_identity_proof(self):
        job=self.start();status,_=self.call('research_status',research_job_id=job)
        self.service.jobs.decide(job,status['result_sha256'],accepted=True,reviewer='root')
        final,_=self.call('research_finalize',research_job_id=job)
        self.assertEqual(final['operator_binding'],['admin','operator'])
        self.identity=dict(principal_id='admin',operator_id='another')
        out,code=self.app.handle(dict(self.body,action='validate',draft_id=final['draft_id']))
        self.assertEqual(code,200);self.assertFalse(out['ok']);self.assertEqual(out['reply'],'')

    def test_original_finalize_endpoint_cannot_bypass_research_root_gate(self):
        job=self.start()
        result=json.loads(self.service.jobs._file(job,'result.json').read_bytes())
        out,code=self.app.handle(dict(self.body,action='finalize',candidate=result['candidate']))
        self.assertEqual(code,403);self.assertEqual(out['reply'],'')
        self.assertEqual(self.app.store.request(self.scope,self.prepared['request_id'])[0],'pending')
        self.assertEqual(self.service.jobs.status('owner',job)['state'],'awaiting_root')

    def test_concurrent_initial_observer_does_not_cancel_input_writer(self):
        self.service.admit(self.app,self.body,max_calls=4,seconds=300)
        original=self.service.jobs._save;repeat=[]
        def reentrant(path,raw):
            if path.name.endswith('-input.json')and not repeat:
                repeat.append(self.call('research_start'))
            return original(path,raw)
        self.service.jobs._save=reentrant
        out,code=self.call('research_start')
        self.assertEqual(code,200);self.assertEqual(repeat[0][1],200)
        self.assertEqual(repeat[0][0]['research_job_id'],out['research_job_id'])
        self.assertEqual(self.service.jobs.status('owner',out['research_job_id'])['state'],'queued')
        self.assertEqual(len(self.work),1);self.assertEqual(self.requests,[])


if __name__=='__main__':unittest.main()
