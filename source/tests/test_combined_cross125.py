"""Cross-candidate native controls with explicitly synthetic image receipts/reviews."""
import copy,json,re,unittest
import test_lifecycle_port124 as helper
from combined_cross_cases import CASES,KNOWN
import assistant_policy as policy
import extension_assistant as ext
import personal_media
import contact_facts
from assistant_store import digest


class CombinedCross125Tests(unittest.TestCase):
    setUp=helper.LifecyclePort124Tests.setUp
    tearDown=helper.LifecyclePort124Tests.tearDown

    def check(self,f):
        k=dict(KNOWN,**f['known']);ctx=dict(convId='synthetic-cross-'+f['id'],city=k['city'],dir=k['direction'],channel=k['channel'],partner=k['partner'],accountTitle=k['account_name'],itemTitle=k['title'],origin='С1',messages=copy.deepcopy(f['messages']))
        owner='synthetic-lifecycle-port-test'
        if f['review']:
            with self.store.connect()as db:
                personal_media.schema(db)
                for row in ctx['messages']:
                    if row.get('attachments'):
                        signature=digest(row['attachments'])if f['review']is True else'wrong-signature'
                        db.execute('INSERT INTO personal_media_reviews VALUES (?,?,?,?,?,?,?,?)',('assistant:'+digest(owner),ctx['convId'],row['id'],signature,policy.VERSION,'synthetic-media-receipt',0,json.dumps({'content_kind':'product_photo'})))
        _,parsed,known,_=ext._parse(ctx,self.store,'assistant:'+digest(owner))
        semantic=policy.assess(parsed,known,contact_facts.collect(parsed,known))
        prepared,status=self.app.handle(dict(owner=owner,action='preview',ctx=ctx,wording_mode='neural_review'));self.assertEqual(status,200);self.assertFalse(prepared['auto_enabled'])
        task=json.loads(prepared['model_task']['task'])if prepared.get('pending_model')else{}
        e=f['expected'];kind=e['kind'];reply=task.get('proposed_reply')or prepared.get('reply','');final=prepared
        if task and kind not in('adult','guard','media','actor','restricted'):
            meaning='Клиент уточняет текущий вопрос без принятой записи или разрешения перевозки.'
            intent='Сборка мебели и текущий вопрос клиента'
            if kind=='unknown_work':intent='Требуемая работа пока не указана';meaning='Клиент прислал фото без указания желаемого действия.'
            if kind=='callback':meaning='Клиент просит оператора перезвонить через полчаса; визит не подтверждён.'
            if kind=='permission':meaning='Клиент спрашивает разрешение прислать фото объявления после отсрочки.'
            if kind=='materials':intent='Клиент просит заменить провода';meaning='Клиент спрашивает, будет ли у мастера провод с собой.'
            if kind in('electrical','capability','named_work'):intent='Клиент просит названную электрическую работу';meaning='Клиент спрашивает, возьмёмся ли за названную работу.'
            review=dict(last_intent=intent,latest_client_meaning=meaning,selected_step_fits=True,evidence_ids=[task['latest_client_message']['evidence_id']],note='Ручной synthetic review; запас, машина, цена доставки, запись и выполненный звонок не подтверждены.')
            if task.get('latest_visual_message_context'):
                self.assertFalse(task['latest_client_message']['body'].strip())
                review['latest_client_meaning'] = task['output_contract']['fixed_latest_client_meaning']
            for field,proof in [('pickup_delivery_condition','pickup_delivery_review'),('photo_work_clarification','photo_work_review')]:
                if task.get(field):review[proof]=copy.deepcopy(task[field]['required_review'])
            if task.get('client_background_work'):review['background_work_review']=dict(evidence_ids=list(dict.fromkeys(x['evidence_id']for x in task['client_background_work'])),actor='client',ordered_from_service=False)
            candidate=dict(reply=reply,needs_operator=False,context_review=review)
            final,status=self.app.handle(dict(owner=owner,action='finalize',request_id=prepared['request_id'],revision=prepared['revision'],candidate=candidate));self.assertEqual(status,200);self.assertEqual(final.get('validation'),[])
            reply=final.get('reply','')
        prep=final.get('crm_preparation')or{};pref=prep.get('callback_preference')or{}
        if kind=='permission':self.assertIn('можете прислать фото',reply);self.assertNotRegex(reply,r'номер|телефон|инструкц')
        if kind=='future':
            self.assertTrue(reply);self.assertNotRegex(reply,r'номер|телефон|когда.{0,20}принять|после осмотра');self.assertFalse(final.get('lead',{}).get('can_create_automatically'))
        if kind=='mandatory_pickup':self.assertIn('уточнить у филиала',reply);self.assertNotIn('Нужна сборка отдельно',reply);self.assertNotIn('подтверждён.',reply.replace('не подтверждён.',''))
        if kind=='pickup':self.assertIn('уточнить у филиала',reply);self.assertTrue(reply)
        if kind=='unknown_work':self.assertIn('Что требуется сделать?',reply);self.assertEqual(task['service_constraints']['status'],'unknown');self.assertNotRegex(reply,r'щиток|номер|по материалам|согласован')
        if kind=='electrical':self.assertIn('Где расположен щиток или автомат?',reply)
        if kind=='capability':self.assertIn('Да, помогу.',reply);self.assertNotIn('По материалам',reply)
        if kind=='materials':self.assertIn('По материалам смогу сориентировать после осмотра.',reply)
        if kind=='callback':
            self.assertEqual(final['action'],'wait');self.assertTrue(reply);self.assertEqual(pref.get('message_id'),e['witness']);self.assertEqual(pref.get('after_minutes'),30);self.assertEqual(pref.get('preferred_at'),'2026-10-21T03:30:00+00:00');self.assertIs(pref.get('execution_confirmed'),False)
        if kind=='bad_contact':self.assertFalse(pref);self.assertFalse(prep);self.assertNotIn('Понял, сейчас не отвлекаю',reply)
        if kind=='declined':self.assertEqual(final['action'],'wait');self.assertEqual(semantic.get('client_wait_intent'),'declined');self.assertFalse(prep)
        if kind=='price_joke':self.assertNotEqual(semantic.get('client_wait_intent'),'declined');self.assertIn('1500',reply);self.assertNotRegex(reply,r'номер|телефон|\bитого\b|\bровно\b')
        if kind in('named_work','new_work'):self.assertNotIn('photo_work_clarification',task);self.assertNotEqual(final.get('client_wait_intent'),'deferred');self.assertNotIn('Что требуется сделать?',reply)
        if kind in('guard','media'):self.assertEqual(prepared['action'],'handoff');self.assertFalse(prepared.get('pending_model'));self.assertFalse(prep)
        if kind=='actor':self.assertNotIn('photo_work_clarification',task)
        if kind=='adult':self.assertRegex(reply+' '+prepared.get('reason',''),r'взросл');self.assertNotIn('Что требуется сделать?',reply);self.assertNotIn('photo_work_clarification',task)
        if kind=='restricted':self.assertNotIn('photo_work_clarification',task);self.assertEqual(prepared['action'],'handoff')
        if kind=='delivery_price':self.assertTrue(reply);self.assertNotRegex(reply,r'1500|500|бесплат')
        if e.get('prep'):self.assertEqual(prep.get('time_policy'),e['prep'])
        if e.get('no_preference'):self.assertFalse(pref)
        if e.get('no_pickup_proof'):self.assertNotIn('pickup_delivery_condition',task)
        if e.get('no_assembly'):self.assertNotRegex(reply,r'сборк|собер')
        if prep:
            for key in('ready','can_create_automatically','visit_time_confirmed'):self.assertIs(prep[key],False)
        self.assertNotRegex(reply,r'заберу|доставлю|перевезу|привезу|уже создал|точно приедет')


def make_case(f):
    def test(self):self.check(f)
    return test

for case in CASES:setattr(CombinedCross125Tests,'test_'+case['id'].replace('-','_'),make_case(case))
