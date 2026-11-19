"""Source-bound native business authority, no real transport or model calls."""
import copy
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import personal_workflow
from extension_assistant import _parse
from assistant_store import digest
import test_native_startup240 as fixture
import test_workflow as crm_fixture
import auto_simulator231 as simulation
from native_workflow import NativeWorkflow
import native_execution
import native_execution_protocol as wire


class NativeSourceAdmission241Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.NativeStartup240Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_server_minimal_context_uses_authenticated_assignment_and_channel_permission(self):
        f=self.f
        f.ctx['messages'][0]['body']='Нужно повесить полку на бетонную стену.'
        f.sim.sync(f.ctx['convId'])
        prepared=f.app.research.prepare_source(f.app,dict(f.body,ctx=dict(convId=f.ctx['convId'])))
        chat,messages,known,revision=_parse(prepared['ctx'],f.app.store,'assistant:'+digest(prepared['owner']))
        plan=personal_workflow.plan_for_actor(messages,known,prepared['ctx'],
            prepared['native_run']['operator_id'],0,revision)
        self.assertTrue(plan['eligible'],plan)
        self.assertEqual(plan['step'],'claim')
        self.assertEqual(f.sim.requests,[])

    def test_missing_acceptance_condition_is_not_bypassed_by_source_permission_fix(self):
        f=self.f
        prepared=f.app.research.prepare_source(f.app,dict(f.body,ctx=dict(convId=f.ctx['convId'])))
        _,messages,known,revision=_parse(prepared['ctx'],f.app.store,'assistant:'+digest(prepared['owner']))
        plan=personal_workflow.plan_for_actor(messages,known,prepared['ctx'],
            prepared['native_run']['operator_id'],0,revision)
        self.assertTrue(prepared['ctx']['assignmentKnown'])
        self.assertTrue(prepared['ctx']['channelAssigned'])
        self.assertFalse(plan['eligible'])
        self.assertIn('wall',plan['missing_acceptance_conditions'])

    def test_caller_booleans_cannot_replace_missing_native_assignment_or_channel(self):
        f=self.f;meta=f.sim.sources[f.ctx['convId']]['metadata']
        meta.pop('claimed_by_id');meta.pop('channel');meta.pop('bot_active');meta.pop('transfer_to_id')
        ctx=dict(convId=f.ctx['convId'],assignmentKnown=True,channelAssigned=True,botActive=False,hasTransfer=False)
        prepared=f.app.research.prepare_source(f.app,dict(f.body,ctx=ctx))
        self.assertFalse(prepared['ctx']['assignmentKnown'])
        self.assertFalse(prepared['ctx']['channelAssigned'])
        self.assertIsNone(prepared['ctx']['botActive'])
        self.assertIsNone(prepared['ctx']['hasTransfer'])


class NativeActionAuthority241Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.NativeStartup240Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f
        f.ctx['messages'][0]['body']='Нужно повесить полку на бетонную стену.'
        f.sim.sync(f.ctx['convId'])
        self.now=f.app.research.jobs.clock()
        self.broker=NativeWorkflow(f.app,enabled=True,clock=lambda:self.now)

    def operation(self):
        plan=self.broker.plan(self.f.body)
        self.assertTrue(plan['eligible'],plan)
        return dict(kind='claim',revision=plan['revision'],operation_id=plan['operation_id'])

    def rows(self):
        with self.f.app.store.connect()as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='native_workflow_grants'").fetchone()
            return list(db.execute('SELECT *FROM native_workflow_grants'))if exists else []

    def test_reserve_is_not_execution_and_consume_is_durable_once(self):
        op=self.operation();reserved=self.broker.reserve(self.f.body,op)
        self.assertTrue(reserved['ok'],reserved);self.assertFalse(reserved['execution_allowed'])
        again=self.broker.reserve(self.f.body,op)
        self.assertEqual(again['grant_id'],reserved['grant_id']);self.assertTrue(again['recovered'])
        started=self.broker.consume(self.f.body,op,reserved['grant_id'])
        self.assertTrue(started['execution_allowed'],started)
        self.assertFalse(started['customer_effect_confirmed'])
        self.assertEqual(self.rows()[0]['state'],'started')
        self.assertFalse(self.broker.consume(self.f.body,op,reserved['grant_id'])['execution_allowed'])
        self.assertFalse(self.broker.reserve(self.f.body,op)['ok'])
        with self.f.app.store.connect()as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='personal_sessions'").fetchone())
        self.assertEqual(self.f.sim.requests,[])

    def test_recreated_authority_recovers_same_reservation_and_original_deadline(self):
        op=self.operation();one=self.broker.reserve(self.f.body,op)
        fresh=NativeWorkflow(self.f.app,enabled=True,clock=lambda:self.now)
        two=fresh.reserve(self.f.body,op)
        self.assertEqual(one['grant_id'],two['grant_id'])
        self.assertEqual(one['expires_at'],two['expires_at'])
        self.assertEqual(len(self.rows()),1)

    def test_default_capability_and_rehearsal_cannot_grant_actions(self):
        op=self.operation()
        self.assertFalse(NativeWorkflow(self.f.app).reserve(self.f.body,op)['ok'])
        self.f.mode='rehearsal'
        out=self.broker.reserve(self.f.body,op)
        self.assertFalse(out['ok']);self.assertEqual(out['code'],'native_rehearsal_has_no_action_authority')
        self.assertEqual(self.rows(),[])

    def test_expiry_or_run_stop_does_not_renew_or_consume(self):
        op=self.operation();grant=self.broker.reserve(self.f.body,op)
        self.now=grant['expires_at']+1
        self.assertFalse(self.broker.consume(self.f.body,op,grant['grant_id'])['ok'])
        self.assertEqual(self.rows()[0]['state'],'reserved')
        self.f.live=False
        self.assertFalse(self.broker.reserve(self.f.body,op)['ok'])
        self.assertEqual(len(self.rows()),1)

    def test_same_id_client_edit_and_other_assignee_block_original_action(self):
        op=self.operation();grant=self.broker.reserve(self.f.body,op)
        self.f.ctx['messages'][0]['body']='Нужно повесить две полки на бетонную стену.'
        self.f.sim.sync(self.f.ctx['convId'])
        self.assertFalse(self.broker.consume(self.f.body,op,grant['grant_id'])['ok'])
        self.assertEqual(self.rows()[0]['state'],'reserved')
        self.f.ctx['assigneeId']=str(uuid.uuid4());self.f.sim.sync(self.f.ctx['convId'])
        self.assertFalse(self.broker.plan(self.f.body)['eligible'])

    def test_preflight_creates_no_action_grant(self):
        op=dict(self.operation(),preflight_only=True)
        out=self.broker.reserve(self.f.body,op)
        self.assertTrue(out['ok'],out);self.assertFalse(out['execution_allowed'])
        self.assertEqual(self.rows(),[])
        self.assertFalse(self.broker.consume(self.f.body,op,'missing')['execution_allowed'])

    def test_old_browser_slot_blocks_native_reservation(self):
        op=self.operation();chat=self.f.ctx['convId']
        with self.f.app.store.connect()as db:
            personal_workflow.grant_schema(db)
            db.execute('INSERT INTO workflow_grants(scope,chat,slot,sid,revision,expires,epoch,reviewed)VALUES(?,?,?,?,?,?,?,?)',
                ('prior-browser',chat,'claim:'+op['operation_id'],'old-browser',op['revision'],self.now-1,1,0))
        result=self.broker.reserve(self.f.body,op)
        self.assertEqual(result['code'],'prior_browser_action')
        self.assertEqual(self.rows(),[])

    def test_native_slot_blocks_browser_authorization(self):
        op=self.operation();grant=self.broker.reserve(self.f.body,op);self.assertTrue(grant['ok'],grant)
        f=self.f;f.sim.identity()
        body=dict(owner=simulation.OWNER,ctx=f.ctx,mine_count=0,**f.sim.last_identity)
        start,code=f.sim.app.handle(dict(body,action='personal_start'));self.assertEqual(code,200,start)
        active,code=f.sim.app.handle(dict(body,action='personal_mode',execution_mode='auto',confirmed=True,
            activation_nonce=start['activation_nonce'],policy_ack=start['policy_version'],client_version='2.8.39'))
        self.assertTrue(active['auto_enabled'],active)
        planned,code=f.sim.app.handle(dict(body,action='personal_plan'));self.assertEqual(code,200,planned)
        self.assertEqual(planned['operation_id'],op['operation_id'])
        out,code=f.sim.app.handle(dict(body,action='personal_authorize',operation=op))
        self.assertEqual(code,403,out);self.assertEqual(out['code'],'already_started')
        self.assertEqual(self.rows()[0]['state'],'reserved')

    def test_broker_rejects_actor_overrides_credentials_and_followup_without_proof(self):
        for extra in [dict(operator_id='other'),dict(headers={'Authorization':'synthetic'}),dict(kind='notify_created')]:
            out=self.broker.reserve(self.f.body,dict(self.operation(),**extra))
            self.assertFalse(out['ok'],out)
        bad=dict(self.f.body,browser_session='synthetic-browser-session')
        self.assertFalse(self.broker.reserve(bad,self.operation())['ok'])
        self.assertEqual(self.rows(),[])

    def reply(self):
        f=self.f;f.ctx['assigneeId']=simulation.ACTOR;f.sim.sync(f.ctx['convId'])
        f.body['ctx']=f.ctx;f.preview()
        start,code=f.call('research_start');self.assertEqual(code,200,start)
        f.body['research_job_id']=start['research_job_id'];f.workers()
        out,code=f.call('research_finalize');self.assertEqual(code,200,out);self.assertTrue(out.get('draft_id'),out)
        planned=self.broker.plan(f.body)
        return dict(kind='reply',revision=planned['revision'],operation_id=planned['operation_id'],draft_id=out['draft_id']),out

    def test_actual_shared_native_draft_gets_one_reply_grant_not_a_customer_send(self):
        op,draft=self.reply()
        grant=self.broker.reserve(self.f.body,op);self.assertTrue(grant['ok'],grant)
        out=self.broker.consume(self.f.body,op,grant['grant_id'])
        self.assertTrue(out['execution_allowed'],out);self.assertEqual(out['reply'],draft['reply'])
        self.assertFalse(out['customer_effect_confirmed'])
        self.assertEqual(len(self.f.sim.requests),2)

    def test_reply_cannot_change_text_or_use_draft_from_prior_launch(self):
        op,draft=self.reply()
        bad=self.broker.reserve(self.f.body,dict(op,reply='Непроверенный другой ответ'))
        self.assertFalse(bad['ok']);self.assertEqual(bad['code'],'native_draft_text_changed')
        self.f.generation+=1;self.f.body['native_run']['generation']=self.f.generation
        old=self.broker.reserve(self.f.body,op)
        self.assertFalse(old['ok']);self.assertEqual(old['code'],'native_draft_launch_changed')
        self.assertEqual(self.rows(),[])

    def test_native_authority_does_not_hold_write_lock_during_remote_source_checks(self):
        op=self.operation();original=self.f.app.research.prepare_source
        def checked(*args,**kwargs):
            with self.f.app.store.connect()as db:
                db.execute('PRAGMA busy_timeout=50');db.execute('BEGIN IMMEDIATE')
            return original(*args,**kwargs)
        with patch.object(self.f.app.research,'prepare_source',side_effect=checked):
            out=self.broker.reserve(self.f.body,op)
        self.assertTrue(out['ok'],out)

    def test_two_consumers_cannot_dispatch_the_same_action(self):
        op=self.operation();grant=self.broker.reserve(self.f.body,op)
        self.assertTrue(grant['ok'],grant)
        with ThreadPoolExecutor(max_workers=2)as pool:
            results=list(pool.map(lambda _:self.broker.consume(self.f.body,op,grant['grant_id']),range(2)))
        self.assertEqual(sum(r.get('execution_allowed')is True for r in results),1,results)
        self.assertEqual(self.rows()[0]['state'],'started')
        self.assertEqual(self.f.sim.requests,[])

    def crm_form(self):
        f=self.f;cid=f.ctx['convId'];f.sim.command(dict(op='ready',cid=cid))
        f.ctx=f.sim.contexts[cid];f.body['ctx']=f.ctx;f.app.research.intake_form_enabled=True
        prepared,code=f.app.handle(dict(f.body,action='form_preview',wording_mode='neural_auto',
                                       _trusted_research_profile='sol_only'))
        self.assertEqual(code,200,prepared);self.assertTrue(prepared.get('pending_model'),prepared)
        f.body.update(request_id=prepared['request_id'],revision=prepared['revision'])
        start,code=f.call('research_start');self.assertEqual(code,200,start)
        f.body['research_job_id']=start['research_job_id'];f.workers()
        final,code=f.call('research_finalize');self.assertEqual(code,200,final)
        self.assertTrue(final.get('intake_form_ready'),final)
        planned=self.broker.plan(f.body);self.assertEqual(planned['step'],'prepare_crm',planned)
        proposal=crm_fixture.WorkflowTests().proposal(f.ctx)
        proposal['revision']=planned['revision']
        proposal['lead'].update(copy.deepcopy(final['form_extraction']['lead']))
        proposal['lead']['service_comment']='https://lead.test/chats/'+cid
        proposal['form_reference']=final['form_reference']
        return dict(kind='create_crm',revision=planned['revision'],operation_id=planned['operation_id'],
                    proposal=proposal,snapshot_hash=digest(proposal))

    def test_reviewed_native_form_can_reserve_one_creation_without_creating_an_order(self):
        op=self.crm_form();grant=self.broker.reserve(self.f.body,op)
        self.assertTrue(grant['ok'],grant)
        result=self.broker.consume(self.f.body,op,grant['grant_id'])
        self.assertTrue(result['execution_allowed'],result)
        self.assertFalse(result['customer_effect_confirmed'])
        self.assertFalse(self.broker.consume(self.f.body,op,grant['grant_id'])['ok'])
        with self.f.app.store.connect()as db:
            required=db.execute('SELECT fields FROM workflow_crm_requirements WHERE chat=?',(self.f.ctx['convId'],)).fetchone()
        self.assertIsNotNone(required)
        self.assertEqual(len(self.f.sim.requests),2)

    def test_native_form_description_cannot_be_changed_after_acceptance(self):
        op=self.crm_form()
        op['proposal']['lead']['problem']='Другой непроверенный ремонт'
        op['snapshot_hash']=digest(op['proposal'])
        self.assertFalse(self.broker.reserve(self.f.body,op)['ok'])
        self.assertEqual(self.rows(),[])

    def inspect_rpc(self,change_during_check=False):
        f=self.f;prepared=f.app.research.prepare_source(f.app,f.body)
        queue=[];key=b'synthetic-native-intake-inspection-key'
        gateway=native_execution.Gateway(f.sim.root/'inspect-commands',key=lambda:key,
            app_factory=lambda principal:f.app,schedule=queue.append,clock=lambda:1793524000)
        command=dict(v=1,command_id=str(uuid.uuid4()),operation='inspect',principal_id=simulation.PRINCIPAL,
            operator_id=simulation.ACTOR,run_id=f.run_id,generation=f.generation,
            arguments=dict(cid=f.ctx['convId'],source_sha256=prepared['ctx']['sourceSnapshotSha256']))
        raw,headers=wire.request(key,command,now=1793524000)
        status,result,signed=gateway.handle(raw,{k.lower():v for k,v in headers.items()})
        self.assertEqual(status,202)
        original=NativeWorkflow.plan
        def changed(broker,body):
            f.ctx['messages'][0]['body']='Нужно повесить две полки на бетонную стену.'
            f.sim.sync(f.ctx['convId'])
            return original(broker,body)
        if change_during_check:
            with patch.object(NativeWorkflow,'plan',new=changed):queue.pop(0)()
        else:queue.pop(0)()
        with gateway.connect()as db:
            return db.execute('SELECT *FROM commands WHERE id=?',(command['command_id'],)).fetchone()

    def test_authenticated_intake_inspect_rpc_can_screen_without_model_or_action_admission(self):
        row=self.inspect_rpc();self.assertEqual(row['state'],'done')
        out=wire.decode(row['response'],wire.MAX_RESPONSE)['data']
        self.assertTrue(out['eligible'],out);self.assertEqual(out['step'],'claim')
        self.assertFalse(out['execution_allowed']);self.assertEqual(self.rows(),[])
        with self.f.app.research.jobs.connect()as db:
            self.assertEqual(db.execute('SELECT count(*)FROM grants').fetchone()[0],0)
        self.assertEqual(self.f.sim.requests,[])

    def test_existing_order_is_excluded_by_native_inspect(self):
        self.f.ctx['crmRequestId']='123456';self.f.sim.sync(self.f.ctx['convId'])
        row=self.inspect_rpc();self.assertEqual(row['state'],'done')
        out=wire.decode(row['response'],wire.MAX_RESPONSE)['data']
        self.assertFalse(out['eligible']);self.assertIn('уже есть заявка',out['reason'])
        self.assertEqual(self.rows(),[]);self.assertEqual(self.f.sim.requests,[])

    def test_changed_source_during_inspection_does_not_expose_an_old_claim_plan(self):
        row=self.inspect_rpc(change_during_check=True)
        self.assertEqual(row['state'],'uncertain');self.assertIsNone(row['response'])
        self.assertEqual(self.rows(),[]);self.assertEqual(self.f.sim.requests,[])


if __name__=='__main__':unittest.main()
