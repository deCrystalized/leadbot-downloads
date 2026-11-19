"""Only the current verified creation can authorize its one service post."""
import json
import unittest
from contextlib import contextmanager
import test_workflow as fixtures
from assistant_store import digest
import personal_workflow


class IntakeCompletion203Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WorkflowTests();self.f.setUp();self.addCleanup(self.f.tearDown)

    @contextmanager
    def current_creation(self):
        f=self.f;ctx=f.ctx(True)
        self.creation_index=getattr(self,'creation_index',0)+1
        ctx['convId']='synthetic-intake203-'+str(self.creation_index)
        proposal=f.proposal(ctx)
        proposal['lead']['service_comment']='https://lead.test/chats/'+ctx['convId']
        with f.auto():
            gate=f.call('personal_crm_check',ctx=ctx,proposal=proposal)
            self.assertTrue(gate['ready'],gate)
            create=f.operation(ctx,'create_crm',proposal=proposal,snapshot_hash=gate['snapshot_hash'])
            self.assertTrue(f.call('personal_authorize',ctx=ctx,operation=create)['ok'])
            plan=f.call('personal_plan',ctx=ctx)
            proof=dict(crm_request_id='1234567',fields=personal_workflow.CRM_CORE_FIELDS+plan['crm_required_fields'],diffs=[],warnings=[],policy_version=plan['policy_version'],message_revision=plan['message_revision'])
            notify=f.operation(ctx,'notify_created',operation_id='notify:1234567',crm_request_id='1234567',verification=proof,before_link=True)
            yield ctx,notify

    def test_prelink_notification_requires_the_explicit_current_creation_contract(self):
        with self.current_creation() as (ctx,notify):
            for change in ({'before_link':False},{'before_link':1},{'kind':'rename_client','operation_id':'rename:1234567'},{'verification':{}}):
                out=self.f.call('personal_authorize',ctx=ctx,operation={**notify,**change});self.assertFalse(out['ok']);self.assertFalse(out['execution_allowed'])
            out=self.f.call('personal_authorize',ctx=ctx,operation=notify);self.assertTrue(out['ok']);self.assertEqual(out['kind'],'notify_created')
            self.assertEqual(self.f.call('personal_authorize',ctx=ctx,operation=notify)['code'],'already_started')

    def test_different_creation_browser_or_epoch_cannot_authorize_an_unlinked_post(self):
        for field,value in [('sid','another:tab'),('epoch',-1)]:
            with self.subTest(field=field),self.current_creation() as (ctx,notify):
                with self.f.app.store.connect() as db:
                    db.execute('UPDATE workflow_grants SET '+field+'=? WHERE scope=? AND slot=?',(value,digest('owner'),'create_once'))
                self.assertFalse(self.f.call('personal_authorize',ctx=ctx,operation=notify)['ok'])

    def test_changed_id_fields_policy_or_source_are_not_a_verified_receipt(self):
        with self.current_creation() as (ctx,notify):
            for change in ({'crm_request_id':'7654321'},{'fields':[]},{'warnings':['не сверено']},{'message_revision':'later'},{'policy_version':'old'}):
                bad={**notify,'verification':{**notify['verification'],**change}}
                self.assertFalse(self.f.call('personal_authorize',ctx=ctx,operation=bad)['ok'])

    def test_existing_other_order_does_not_gain_an_unlinked_notification_exception(self):
        with self.current_creation() as (ctx,notify):
            ctx={**ctx,'crmRequestId':'7654321'}
            self.assertFalse(self.f.call('personal_authorize',ctx=ctx,operation=notify)['ok'])

    def test_new_primary_job_is_eligible_but_existing_order_service_is_not_claimed(self):
        f=self.f
        for text in ['Жалоба: мастер не приехал в Чите','Перенесите мою заявку на завтра, мастер сегодня не пришёл, я в Чите','Отмените мою заявку на ремонт компьютера в Чите']:
            ctx=f.ctx();ctx['assigneeId']='';ctx['messages'][0]['body']=text
            out=f.call('personal_plan',ctx=ctx)
            self.assertFalse(out['eligible'],(text,out));self.assertNotEqual(out['step'],'claim')
        ctx=f.ctx();ctx['assigneeId']='';self.assertEqual(f.call('personal_plan',ctx=ctx)['step'],'claim')

    def test_new_booking_time_question_is_not_treated_as_an_existing_order(self):
        ctx=self.f.ctx();ctx['messages'][0]['body']='Нужно почистить компьютер в Чите. Можно приехать завтра?';ctx['assigneeId']=''
        self.assertTrue(self.f.call('personal_plan',ctx=ctx)['eligible'])
