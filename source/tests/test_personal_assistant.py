import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_assistant import context, message
from assistant_store import Store
from extension_assistant import Assistant
import personal_assistant as personal


class PersonalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name)/'db'))
        self.env = patch.dict(os.environ, {'LEADBOT_PERSONAL_OWNER_ID':'owner', 'LEADBOT_PERSONAL_OPERATOR_ID':'george'})
        self.env.start()
        self.app = Assistant(self.store)
        self.identity = {'owner':'owner','browser_session':'browser:tab:1','operator_id':'george'}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def call(self, action, **extra):
        return self.app.handle({**self.identity,'action':action,**extra})[0]

    def ctx(self, body='Почистить компьютер в Чите', **extra):
        return context([message(body)],assigneeId='',assignmentKnown=True,conversationStatus='in_progress',botActive=False,
                       hasTransfer=False,channelAssigned=True,**extra)

    def start(self):
        self.assertTrue(self.call('personal_start')['active'])

    def test_only_configured_token_owner_has_assistant_access(self):
        for action in ('status','preview','personal_start'):
            out,code=self.app.handle({**self.identity,'owner':'colleague','action':action,'ctx':self.ctx()})
            self.assertEqual(code,403);self.assertEqual(out['code'],'personal_owner')

    def test_wrong_operator_is_not_paired(self):
        self.assertEqual(self.call('personal_start',operator_id='colleague')['code'],'personal_identity')

    def test_session_is_single_tab_and_reloads_same_tab(self):
        self.start();self.start()
        self.assertEqual(self.call('personal_start',browser_session='browser:tab:2')['code'],'personal_busy')
        self.assertFalse(self.call('personal_status',browser_session='browser:tab:2')['active'])
        self.assertTrue(self.call('personal_status')['active'])

    def test_lost_heartbeat_expires_without_server_worker(self):
        body=self.identity
        self.assertTrue(personal.session(self.store,'owner','personal_start',body,now=100)['active'])
        self.assertTrue(personal.session(self.store,'owner','personal_heartbeat',body,now=130)['active'])
        self.assertFalse(personal.session(self.store,'owner','personal_status',body,now=176)['active'])
        self.assertEqual(personal.session(self.store,'owner','screen',body,now=176)['code'],'personal_expired')

    def test_stop_and_other_tab_do_not_release_owner_session(self):
        self.start()
        self.assertEqual(self.call('personal_stop',browser_session='browser:tab:2')['code'],'personal_expired')
        self.assertTrue(self.call('personal_status')['active'])
        self.assertFalse(self.call('personal_stop')['active'])
        self.assertEqual(self.call('screen',ctx=self.ctx(),mine_count=0)['code'],'personal_expired')

    def test_legacy_limit_values_cannot_reintroduce_a_cap(self):
        for value in (0,6,True,'3'):
            self.assertEqual(self.call('personal_start',max_dialogs=value)['max_dialogs'],0)

    def test_screen_requires_known_load(self):
        self.start()
        for count in (None,-1,True,'0'):
            self.assertFalse(self.call('screen',ctx=self.ctx(),mine_count=count)['ok'])

    def test_normal_free_job_is_only_planned_never_taken(self):
        self.start();out=self.call('screen',ctx=self.ctx(),mine_count=0)
        self.assertTrue(out['eligible']);self.assertEqual(out['scope'],'free')
        self.assertEqual(out['planned_actions'][0],'Взять диалог на себя')
        self.assertFalse(out['auto_enabled']);self.assertNotIn('model_task',out)

    def test_existing_work_count_does_not_limit_free_jobs(self):
        self.start()
        from assistant_store import digest
        with self.store.connect() as db:
            personal.jobs_schema(db)
            db.executemany('INSERT INTO personal_jobs VALUES(?,?,1,0)',[(digest('owner'),str(i)) for i in range(3)])
        out=self.call('screen',ctx=self.ctx(),mine_count=0)
        self.assertTrue(out['eligible']);self.assertEqual(out['managed_dialogs'],3)

    def test_mine_can_be_reviewed_at_capacity(self):
        self.start();ctx=self.ctx();ctx['assigneeId']='george'
        self.assertTrue(self.call('screen',ctx=ctx,mine_count=3)['eligible'])

    def test_other_assignee_or_unknown_permissions_are_rejected(self):
        self.start()
        for key,value in [('assigneeId','colleague'),('conversationStatus','closed'),('botActive',True),
                          ('hasTransfer',True),('channelAssigned',False),('hasCrmJob',True),('assignmentKnown',False),('botActive',None)]:
            ctx=self.ctx();ctx[key]=value
            self.assertFalse(self.call('screen',ctx=ctx,mine_count=0)['eligible'],key)

    def test_agreements_conflicts_mixed_and_escalations_do_not_enter_queue(self):
        self.start()
        for text in ['Заправить картридж принтера в Чите','В Чите ремонт матрицы монитора',
                     'В Чите настроить спутниковое ТВ','В Чите починить компьютер и стиральную машину',
                     'Разбита матрица телевизора в Чите','Здравствуйте','Жалоба: мастер не приехал в Чите']:
            self.assertFalse(self.call('screen',ctx=self.ctx(text),mine_count=0)['eligible'],text)

    def test_unknown_acceptance_condition_is_not_a_free_job(self):
        self.start();out=self.call('screen',ctx=self.ctx('Настроить роутер в Чите'),mine_count=0)
        self.assertFalse(out['eligible']);self.assertEqual(out['admission'],'needs_facts')
        out=self.call('screen',ctx=self.ctx('Настроить роутер в Чите, интернет уже проведен'),mine_count=0)
        self.assertTrue(out['eligible'])
        out=self.call('screen',ctx=self.ctx('Настроить телевизор в Чите'),mine_count=0)
        self.assertFalse(out['eligible']);self.assertEqual(out['admission'],'needs_facts')

    def test_sport_installation_wall_is_a_question_not_branch_approval(self):
        self.start()
        for text in ('Можете повесить турник? Сколько это будет по стоимости?',
                     'В Чите нужно установить шведскую стенку'):
            out=self.call('screen',ctx=self.ctx(text,dir='mnc'),mine_count=0)
            self.assertTrue(out['eligible'],out)
            self.assertIn('DOC-L0355',out['candidate_service_rule_ids'])
            self.assertFalse(out['auto_enabled'])
        ctx=self.ctx('В Чите повесить турник',city='Чита',dir='mnc')
        checklist=self.call('checklist',ctx=ctx)
        self.assertTrue(any(row['key']=='wall' and not row['done'] for row in checklist['results']))
        self.assertFalse(self.call('screen',ctx=self.ctx('В Чите ремонт турника',dir='mnc'),mine_count=0)['eligible'])

    def test_no_personal_action_can_enable_claim_send_or_crm(self):
        self.start()
        for action in ('send','enable','auto','crm_write','personal_claim','personal_enable'):
            self.assertFalse(self.call(action)['ok']);self.assertFalse(self.call(action)['auto_enabled'])

    def test_owner_guard_does_not_break_internal_territory_bridge(self):
        out,code=self.app.handle({'owner':'territory-registry','action':'geography','city':'Чита','dir':'kp'})
        self.assertEqual(code,200);self.assertTrue(out['ok'])

    def test_minor_adult_condition_precedes_city_and_contact_collection(self):
        for messages in ([message('Мне 16 лет, компьютер сломался')],
                         [message('Здравствуйте','in'),message('Вам сколько лет?','out','2'),message('Здравствуйте, 15, а вопрос к чему?','in','3')]):
            out=self.call('preview',ctx=context(messages))
            self.assertIn('DOC-L1572',out['rule_ids'])
            self.assertEqual(out['action'],'question')
            self.assertRegex(out['reply'],'взросл')
            self.assertNotRegex(out['reply'],'номер|телефон|город')
            self.assertFalse(out['lead']['can_create_automatically'])

    def test_quantities_and_age_of_equipment_are_not_customer_age(self):
        for text in ('Мне 15 розеток установить в Чите','Компьютеру 16 лет, почистить в Чите'):
            out=self.call('preview',ctx=context([message(text)]));self.assertNotIn('DOC-L1572',out.get('rule_ids',[]))

    def test_agreed_visit_is_not_started_as_a_new_lead(self):
        messages=[message('Почистить компьютер в Чите'),message('Через час буду у вас','out','2'),message('Спасибо, жду вас','in','3')]
        out=self.call('preview',ctx=context(messages));self.assertTrue(out['needs_operator']);self.assertRegex(out['reason'],'выезд')

    def test_repairing_furniture_starts_with_the_fault_and_special_work_needs_approval(self):
        ctx=self.ctx('Здравствуйте, сможете починить кровать в Чите?');ctx['dir']='mnc'
        out=self.call('preview',ctx=ctx);self.assertTrue(out['pending_model']);self.assertIn('furniture_problem',out['model_task']['task'])
        ctx=self.ctx('В Чите заменить пружины в диване');ctx['dir']='mnc'
        ctx['convId']='furniture-special'
        out=self.call('preview',ctx=ctx);self.assertTrue(out['needs_operator']);self.assertIn('DOC-L0325',out['rule_ids'])

    def test_tv_chip_replacement_is_not_priced_as_old_firmware_attempt(self):
        ctx=context([message('Телевизор в Чите, ранее обновлял прошивку, теперь требуется замена чипа памяти eMMC. Сколько стоит?')],itemTitle='Ремонт телевизоров')
        out=self.call('preview',ctx=ctx)
        self.assertIn('5000',out['reply']);self.assertNotIn('2500',out['reply']);self.assertIn('DOC-L0195',out['rule_ids'])

    def test_reassignment_invalidates_a_prepared_reply(self):
        ctx=self.ctx();ctx['assigneeId']='george'
        p=self.call('preview',ctx=ctx)
        result=self.call('finalize',request_id=p['request_id'],revision=p['revision'],candidate={'reply':'Марку и модель подскажите?','needs_operator':False})
        ctx['assigneeId']='colleague'
        checked=self.call('validate',ctx=ctx,draft_id=result['draft_id'])
        self.assertFalse(checked['ok']);self.assertFalse(checked['reply'])

    def test_wording_model_receives_one_approved_question_not_customer_history(self):
        ctx=self.ctx('Почистить компьютер в Чите, секретное слово: НЕ-ПЕРЕДАВАТЬ')
        out=self.call('preview',ctx=ctx)
        task=out['model_task']['task']
        self.assertNotIn('НЕ-ПЕРЕДАВАТЬ',task)
        self.assertNotIn('history',task);self.assertNotIn('sources',task)
        self.assertIn('Марку и модель',task)

    def test_reviewed_question_mode_does_not_request_model(self):
        with patch.dict(os.environ,{'LEADBOT_ASSISTANT_WORDING':'reviewed'}):
            out=self.call('preview',ctx=self.ctx())
            self.assertNotIn('model_task',out);self.assertEqual(out['response_source'],'reviewed_question')
            self.assertFalse(out['needs_operator']);self.assertTrue(out['reply']);self.assertFalse(out['auto_enabled'])

    def test_reviewed_choice_question_keeps_the_whole_choice(self):
        with patch.dict(os.environ,{'LEADBOT_ASSISTANT_WORDING':'reviewed'}):
            ctx=self.ctx('В Чите телевизор не включается');ctx['itemTitle']='Ремонт телевизоров'
            out=self.call('preview',ctx=ctx)
            self.assertIn('ЖК',out['reply']);self.assertIn('плазменный',out['reply']);self.assertIn('кинескопный',out['reply'])

    def test_reviewed_wall_question_does_not_guess_the_material(self):
        with patch.dict(os.environ,{'LEADBOT_ASSISTANT_WORDING':'reviewed'}):
            ctx=self.ctx('Повесить карниз в Чите');ctx['dir']='mnc'
            out=self.call('preview',ctx=ctx);self.assertRegex(out['reply'],'материал|Из чего');self.assertNotRegex(out['reply'],'бетонная')


if __name__=='__main__':unittest.main()
