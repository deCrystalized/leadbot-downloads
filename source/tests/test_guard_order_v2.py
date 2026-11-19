"""A new pause cannot erase prior appointment, complaint or source evidence."""
import copy,json,unittest
import test_lifecycle_port124 as helper
from guard_order_cases import CASES,KNOWN,ROOT_CASES,ROOT_KNOWN,EXTRA_CASES,MORE_CASES
import assistant_policy as policy
import contact_facts
import extension_assistant as ext


class GuardOrderV2Tests(unittest.TestCase):
    setUp=helper.LifecyclePort124Tests.setUp
    tearDown=helper.LifecyclePort124Tests.tearDown

    def context_for(self,f,defaults=KNOWN):
        k=dict(defaults,**f.get('known',{}))
        return dict(convId='synthetic-guard-order-'+f['id'],city=k['city'],dir=k['direction'],channel=k['channel'],partner=k['partner'],accountTitle=k['account_name'],itemTitle=k['title'],crmRequestId=k.get('crm_request_id',''),origin='С1',messages=copy.deepcopy(f['messages']))

    def semantic(self,ctx):
        _,ms,k,_=ext._parse(ctx);return policy.assess(ms,k,contact_facts.collect(ms,k))

    def native(self,ctx,kind='wait'):
        owner='synthetic-lifecycle-port-test'
        out,status=self.app.handle(dict(owner=owner,action='preview',wording_mode='neural_review',ctx=ctx));self.assertEqual(status,200)
        if out.get('pending_model'):
            task=json.loads(out['model_task']['task'])
            meaning='Клиент отложил обсуждение сборки мебели; визит не подтверждён.'
            if kind=='photo':meaning='Клиент спрашивает разрешение прислать фото после отсрочки.'
            if kind=='callback':meaning='Клиент просит оператора перезвонить через полчаса и откладывает обсуждение.'
            review=dict(last_intent='Текущий вопрос клиента по сборке мебели',latest_client_meaning=meaning,selected_step_fits=True,evidence_ids=[task['latest_client_message']['evidence_id']],note='Авторский synthetic review; не подтверждает запись, звонок, визит или перевозку.')
            for field,proof in [('pickup_delivery_condition','pickup_delivery_review'),('photo_work_clarification','photo_work_review')]:
                if task.get(field):review[proof]=copy.deepcopy(task[field]['required_review'])
            value=dict(reply=task['proposed_reply'],needs_operator=False,context_review=review)
            final,status=self.app.handle(dict(owner=owner,action='finalize',request_id=out['request_id'],revision=out['revision'],candidate=value));self.assertEqual(status,200);self.assertEqual(final.get('validation'),[]);return final
        return out

    def check(self,f):
        ctx=self.context_for(f);d=self.semantic(ctx);e=f['expected'];kind=e['kind'];final=self.native(ctx,kind);reply=final.get('reply','');prep=d.get('crm_preparation')or{}
        if kind=='wait':self.assertEqual(d['action'],'wait');self.assertEqual(d.get('client_wait_intent'),'deferred')
        if e.get('ack')is True:self.assertTrue(reply);self.assertIn('когда будете готовы',reply)
        if e.get('ack')is False:self.assertEqual(reply,'')
        if kind in('source','existing','booking','complaint'):self.assertIn(d['action'],('handoff','question'));self.assertFalse(prep)
        if kind=='source':self.assertRegex(d['reason'],r'источник|объявлен|аккаунт|Партнёр|город|филиал|территор')
        if kind=='booking':self.assertEqual(d['staff_booking_claim']['message_id'],e['witness']);self.assertIs(d['staff_booking_claim']['crm_write_confirmed'],False)
        if e.get('no_booking'):self.assertNotIn('staff_booking_claim',d)
        if kind=='price':self.assertEqual(d['action'],'price');self.assertTrue(reply)
        if kind in('active','not_furniture_wait'):self.assertNotEqual(d['action'],'wait')
        if kind=='declined':self.assertEqual(d['action'],'wait');self.assertEqual(d.get('client_wait_intent'),'declined');self.assertFalse(prep);self.assertEqual(reply,'')
        if kind=='photo':self.assertIn('можете прислать фото',reply);self.assertNotRegex(reply,r'телефон|номер')
        if kind=='callback':
            self.assertEqual(d['action'],'wait');self.assertTrue(reply);pref=prep['callback_preference'];self.assertEqual(pref['message_id'],e['witness']);self.assertEqual(pref['after_minutes'],30);self.assertEqual(pref['preferred_at'],'2026-10-21T04:30:00+00:00');self.assertIs(pref['execution_confirmed'],False)
        if e.get('prep'):
            self.assertEqual(prep.get('time_policy'),'nearest_branch_normative')
            for k in('ready','can_create_automatically','visit_time_confirmed'):self.assertIs(prep[k],False)
        self.assertFalse(final.get('auto_enabled'));self.assertNotRegex(reply,r'уже создал|вы записаны|точно приедет|я позвоню')

    def check_root(self,f):
        ctx=self.context_for(f,ROOT_KNOWN);d=self.semantic(ctx);e=f['expected']
        if e=='wait':self.assertEqual(d['action'],'wait')
        elif e=='excluded':self.assertEqual(d['action'],'handoff');self.assertFalse(d.get('forced_reply'))
        else:self.assertIn(d['action'],('handoff','question'))
        if e=='existing_lookup_before_wait':self.assertTrue(d.get('staff_booking_claim'));self.assertFalse(d.get('crm_preparation'))

    def veto(self,kind):
        f=copy.deepcopy(CASES[0]);f['messages'].insert(-1,dict(id='staff-evidence',direction='out',sender_type='operator',body='Понял.',created_at='2026-10-21T04:00:00+00:00',delivery_status='delivered',attachments=[]))
        ctx=self.context_for(f);owner='synthetic-lifecycle-port-test';p,status=self.app.handle(dict(owner=owner,action='preview',wording_mode='neural_review',ctx=ctx));self.assertTrue(p.get('pending_model'))
        t=json.loads(p['model_task']['task']);r=dict(last_intent='Клиент откладывает обсуждение сборки',latest_client_meaning='Клиент вернётся к разговору позже',selected_step_fits=True,evidence_ids=[t['latest_client_message']['evidence_id']],note='Ручной synthetic review, действий не было.')
        value=dict(reply=t['proposed_reply'],needs_operator=False,context_review=r)
        if kind=='actor':r['evidence_ids']=['staff-evidence']
        if kind=='step':r['selected_step_fits']=False
        if kind=='promise':value['reply']='Я уже создал заявку, мастер точно приедет завтра.'
        final,status=self.app.handle(dict(owner=owner,action='finalize',request_id=p['request_id'],revision=p['revision'],candidate=value));self.assertEqual(status,200);self.assertEqual(final['action'],'handoff');self.assertEqual(final['reply'],'');self.assertTrue(final['validation'])

    def test_native_actor_veto(self):self.veto('actor')
    def test_native_step_veto(self):self.veto('step')
    def test_native_promise_veto(self):self.veto('promise')


def case_method(f,root=False):
    def test(self):self.check_root(f)if root else self.check(f)
    return test

for case in CASES+EXTRA_CASES+MORE_CASES:setattr(GuardOrderV2Tests,'test_boundary_'+case['id'].replace('-','_'),case_method(case))
for case in ROOT_CASES:setattr(GuardOrderV2Tests,'test_root_'+case['id'].replace('-','_'),case_method(case,True))
