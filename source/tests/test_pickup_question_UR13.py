"""Synthetic public controls. No history IDs, names, addresses or credentials."""
import copy,json,os,tempfile,unittest
from unittest.mock import patch
import assistant_policy as policy
from assistant_store import Store
from extension_assistant import Assistant

def rows(*bodies):
    return [dict(id='m'+str(i),direction='in',sender_type='client',body=b) for i,b in enumerate(bodies)]

class PickupStateTests(unittest.TestCase):
    def state(self,messages):return policy.furniture_logistics_state(messages,dict(direction='mnc'))
    def test_assembly_and_pickup_are_separate(self):
        out=self.state(rows('Собрать шкаф. Забрать из ВБ сможете?'))
        self.assertTrue(out['assembly']);self.assertEqual(out['evidence_ids'],['m0'])
        self.assertEqual(out['source_ids'],['DOC-L0323','DOC-L0453'])
    def test_pure_transport_does_not_invent_assembly(self):
        for text in ['Нужно перевезти шкаф. Сборка не нужна.','Нужно забрать комод из пункта выдачи.']:
            self.assertFalse(self.state(rows(text))['assembly'])
    def test_client_or_retailer_transport_is_not_an_order(self):
        for text in ['Заберу шкаф из ВБ сам. Нужна только сборка.',
                     'Доставку перенесли на пятницу. Нужно собрать комод.',
                     'Перевозка не нужна, мебель уже дома. Соберите шкаф.',
                     'Собрать шкаф, доставку сделал магазин.']:
            self.assertIsNone(self.state(rows(text)))
    def test_staff_speech_and_attributed_quote_are_not_client_orders(self):
        data=rows('Нужно собрать шкаф.');data.append(dict(id='staff',direction='out',body='Нужно забрать из ВБ?'))
        data+=rows('Нет, нужна только сборка шкафа.')
        self.assertIsNone(self.state(data))
        self.assertIsNone(self.state(rows('Курьер спросил: «Забрать из ВБ?» Нам нужна только сборка шкафа.')))
    def test_deferred_conversation_stays_deferred(self):
        data=rows('Нужно собрать шкаф.','Спасибо, вернёмся к разговору позднее.')
        self.assertEqual(self.state(data)['kind'],'deferred')
        data.append(dict(id='staff',direction='out',body='Напишите позже.'))
        data+=rows('Хорошо')
        self.assertEqual(self.state(data)['kind'],'deferred')
    def test_operator_mislabeled_incoming_is_not_the_client(self):
        data=rows('Собрать шкаф. Забрать из ВБ сможете?');data[0]['sender_type']='operator'
        self.assertIsNone(self.state(data))

class PickupNativeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='owner',LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start();self.addCleanup(env.stop)
        self.app=Assistant(Store(temp.name+'/db'));self.serial=0
    def prepare(self,text='Собрать шкаф. Забрать из ВБ сможете?',data=None):
        self.serial+=1
        ctx=dict(convId='synthetic-pickup-'+str(self.serial),city='Санкт-Петербург',dir='mnc',channel='avito',
                 partner='7',accountTitle='Учебный мастер',origin='С85',itemTitle='Сборка мебели',messages=data or rows(text))
        preview,status=self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(status,200);self.assertTrue(preview.get('pending_model'),preview.get('reason'))
        self.assertFalse(preview['auto_enabled'])
        task=json.loads(preview['model_task']['task']);self.assertIn('pickup_delivery_condition',task)
        proof=copy.deepcopy(task['pickup_delivery_condition']['required_review'])
        review=dict(last_intent='Сборка мебели и отдельно вопрос о получении',latest_client_meaning='Спрашивает о получении мебели мастером',
                    selected_step_fits=True,evidence_ids=[ctx['messages'][-1]['id']],note='Ручной synthetic review, логистика и запись не подтверждены.',pickup_delivery_review=proof)
        candidate=dict(reply=task.get('fixed_reply') or task['decision']['next_question']['question'],needs_operator=False,context_review=review)
        return preview,task,candidate
    def finish(self,preview,candidate):
        final,status=self.app.handle(dict(owner='owner',action='finalize',request_id=preview['request_id'],revision=preview['revision'],candidate=candidate))
        self.assertEqual(status,200);self.assertFalse(final['auto_enabled']);return final
    def test_useful_native_answer_precedes_contact_collection(self):
        preview,task,c=self.prepare();final=self.finish(preview,c)
        self.assertEqual(final['validation'],[]);self.assertFalse(final['needs_operator'])
        self.assertIn('Со сборкой мебели помогу.',final['reply'])
        self.assertIn('уточнить у филиала; пока не подтверждаю',final['reply'])
        self.assertIn('Нужна сборка отдельно от получения?',final['reply'])
        self.assertFalse(policy.requests_contact(final['reply']))
    def test_assembly_minimum_is_scoped_and_server_built(self):
        preview,task,c=self.prepare('Собрать шкаф и забрать его из ВБ. Какая цена?')
        final=self.finish(preview,c);self.assertEqual(final['validation'],[])
        self.assertIn('Сборка мебели — от 1500 рублей.',final['reply'])
        self.assertIn('DOC-L0326',task['primary_sources'].__str__())
    def test_delivery_price_question_does_not_quote_assembly(self):
        preview,task,c=self.prepare('Собрать комод. Сколько стоит доставка из пункта выдачи?')
        final=self.finish(preview,c);self.assertEqual(final['validation'],[])
        self.assertNotIn('1500',final['reply']);self.assertNotIn('руб',final['reply'])
    def test_existing_phone_is_not_requested_again(self):
        data=rows('Собрать шкаф. Телефон 79990000001.')
        data.append(dict(id='staff',direction='out',body='Спасибо, номер получил.'))
        data.append(dict(id='pickup',direction='in',sender_type='client',body='А забрать шкаф из ВБ сможете?'))
        preview,task,c=self.prepare(data=data);final=self.finish(preview,c)
        self.assertEqual(final['validation'],[]);self.assertFalse(policy.requests_contact(final['reply']))
    def test_vehicle_availability_is_not_inferred(self):
        preview,task,c=self.prepare('Собрать шкаф. У мастера есть машина, чтобы забрать мебель?')
        final=self.finish(preview,c);self.assertEqual(final['validation'],[])
        self.assertNotIn('машин',final['reply'].lower())
    def test_promise_candidates_are_rejected_with_correct_next_step(self):
        bad=[('Да, заберу шкаф и привезу к вам.','unconfirmed_pickup_delivery_promise'),
             ('У меня есть машина, заберу комод.','unverified_vehicle_fact'),
             ('Машины нет, поэтому не заберу.','unverified_vehicle_fact'),
             ('Записал вас, завтра приеду.','unconfirmed_action_or_visit'),
             ('Доставка стоит 500 рублей.','unapproved_price'),
             ('Привезу все детали шкафа.','unconfirmed_materials_promise'),
             ('Точно соберу за один визит.','unconfirmed_repair_outcome')]
        for text,error in bad:
            with self.subTest(error=error):
                preview,task,c=self.prepare();c['reply']=text+' '+c['reply'];final=self.finish(preview,c)
                self.assertFalse(final['reply']);self.assertIn(error,final['validation'])
    def test_wrong_source_actor_or_evidence_proof_is_rejected(self):
        for field,value in [('source_rule','DOC-L0323'),('requested_by','staff'),('evidence_id','not-observed'),('logistics_confirmed',True),('logistics_confirmed',0)]:
            with self.subTest(field=field,value=value):
                preview,task,c=self.prepare();c['context_review']['pickup_delivery_review'][field]=value
                final=self.finish(preview,c);self.assertFalse(final['reply']);self.assertIn('pickup_delivery_review_mismatch',final['validation'])
    def test_client_cannot_confirm_our_logistics_capability(self):
        preview,task,c=self.prepare();c['context_review']['last_intent']='Клиент должен подтвердить возможность доставки мастером.'
        final=self.finish(preview,c);self.assertFalse(final['reply']);self.assertIn('pickup_delivery_actor_reversed',final['validation'])
    def test_phone_collection_is_not_the_clients_goal(self):
        preview,task,c=self.prepare();c['context_review']['last_intent']='Главная цель клиента — сообщить телефон.'
        final=self.finish(preview,c);self.assertFalse(final['reply']);self.assertIn('pickup_question_as_contact_goal',final['validation'])
    def test_wrong_step_cannot_replace_pickup_answer(self):
        preview,task,c=self.prepare();c['reply']='Номер для связи подскажите?'
        final=self.finish(preview,c);self.assertFalse(final['reply']);self.assertIn('required_question_missing',final['validation'])
    def test_ambiguous_evidence_id_fails_closed(self):
        data=rows('Собрать шкаф.');data.append(dict(id='same',direction='out',body='Уточню.'))
        data.append(dict(id='same',direction='in',sender_type='client',body='А забрать из ВБ сможете?'))
        ctx=dict(convId='synthetic-ambiguous',city='Санкт-Петербург',dir='mnc',channel='avito',partner='7',accountTitle='Учебный мастер',origin='С85',itemTitle='Сборка мебели',messages=data)
        preview,status=self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(status,200);self.assertFalse(preview.get('pending_model'));self.assertTrue(preview['needs_operator'])

if __name__=='__main__':unittest.main()
