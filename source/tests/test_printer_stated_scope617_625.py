"""Synthetic printer scope, evidence, price-stage and native safety controls."""
import copy,json,os,tempfile,unittest
from unittest.mock import patch
import qualification_state as qs
import assistant_prices as prices
import assistant_catalog as catalog
from assistant_store import Store
from extension_assistant import Assistant

ADF='Нужно снять верхнюю крышку автоподачи бумаги, сохранив стекло сканера на МФУ Pantum BF5100ADW.'
INK='У меня в принтере засохла краска.'
def rows(*bodies):
    return [dict(id='m'+str(i),direction='in' if not isinstance(b,tuple) else b[0],
                 sender_type='client' if not isinstance(b,tuple) or b[0]=='in' else 'operator',
                 body=b if not isinstance(b,tuple) else b[1]) for i,b in enumerate(bodies)]
KNOWN=dict(direction='kp',channel='avito',partner='7',city='Нижний Новгород',title='Ремонт принтеров',account_name='Учебный мастер')

class PrinterScopeTests(unittest.TestCase):
    def test_cover_operation_keeps_exact_source_offsets(self):
        body='Здравствуйте, подскажите. '+ADF
        match=qs.printer_problem_match(body);self.assertEqual(match.lastgroup,'adf_cover')
        self.assertEqual(body[match.start():match.end()],match[0])
        state=qs.inspect(rows(body))['problem'];self.assertEqual(state['value'],match[0]);self.assertEqual(state['message_id'],'m0')
    def test_dried_ink_keeps_exact_source_offsets(self):
        body='Здравствуйте, '+INK
        match=qs.printer_problem_match(body);self.assertEqual(match.lastgroup,'dry_ink')
        self.assertEqual(body[match.start():match.end()],'засохла краска')
        self.assertEqual(qs.inspect(rows(body))['problem']['value'],'засохла краска')
    def test_reverse_order_dried_ink_is_a_stated_symptom(self):
        self.assertEqual(qs.printer_problem_match('Засохла краска в принтере.').lastgroup,'dry_ink')
    def test_taking_a_photo_or_renting_is_not_a_cover_operation(self):
        for text in ['Нужно снять фото принтера.','Хочу снять квартиру, рядом есть принтер.']:
            self.assertIsNone(qs.printer_problem_match(text))
    def test_negation_or_third_party_does_not_create_the_new_scope(self):
        for text in ['В МФУ не нужно снимать верхнюю крышку автоподачи.',
                     'В принтере краска не засохла.',
                     'Другой мастер написал: «В принтере засохла краска».',
                     'Сосед просит снять верхнюю крышку автоподачи на его МФУ.']:
            self.assertIsNone(qs.printer_problem_match(text),text)
    def test_dry_material_on_another_object_is_not_printer_ink(self):
        for text in ['Принтер Epson. На столе засохла краска для стен.',
                     'В принтере лежит ручка, в ней засохли чернила.',
                     'Если в принтере засохли чернила, что делать?']:
            self.assertIsNone(qs.printer_problem_match(text),text)
    def test_staff_operation_is_not_client_evidence(self):
        self.assertIsNone(qs.printer_stated_scope(rows(('out',ADF),'Здравствуйте')))
    def test_brand_and_model_are_distinct(self):
        brand=qs.inspect(rows(INK,('out','Марку и модель?'),'Эпсон'))
        model=qs.inspect(rows(INK,('out','Марку и модель?'),'L366 Epson'))
        self.assertEqual(brand['problem']['status'],'answered');self.assertEqual(brand['model']['status'],'missing')
        self.assertEqual(model['model']['status'],'answered');self.assertEqual(model['problem']['message_id'],'m0')
    def test_new_enquiry_does_not_keep_old_dry_ink_as_its_problem(self):
        data=rows('Принтер Epson L366: засохли чернила.',('out','Обсудили прошлую проблему.'),
                  'Новая заявка: другой принтер HP LaserJet 1020 не включается.')
        self.assertIsNone(qs.printer_stated_scope(data));self.assertEqual(qs.inspect(data)['problem']['message_id'],'m2')
    def test_cover_only_is_not_conversion_but_explicit_conversion_is_agreement(self):
        self.assertEqual(catalog.choose(ADF,KNOWN)['status'],'supported')
        converted=catalog.choose(ADF+' Переделайте принтер из лазерного в струйный.',KNOWN)
        self.assertEqual(converted['status'],'agree');self.assertIn('DOC-L0187',converted['rules'])
    def test_currency_unit_task_and_stage_are_checked_for_old_minimum(self):
        data=rows(ADF,('out','от 500 рублей услуга'),'И до скольки?')
        self.assertTrue(prices.prior_quote_verified(data,KNOWN,prices.consent(data)))
        for quote in ['500 рублей за всё, окончательная цена.','от 500 рублей за метр.',
                      'от 500 рублей диагностика и выезд.','от 700 рублей услуга.','от 500 услуга.']:
            data=rows(ADF,('out',quote),'Хорошо.')
            self.assertFalse(prices.prior_quote_verified(data,KNOWN,prices.consent(data)),quote)
    def test_named_head_cleaning_does_not_become_general_minimum(self):
        data=rows('Нужно почистить печатающую головку Epson L366.',('out','от 500 рублей услуга.'),'Хорошо.')
        self.assertFalse(prices.prior_quote_verified(data,KNOWN,prices.consent(data)))

class PrinterNativeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='owner',LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start();self.addCleanup(env.stop);self.app=Assistant(Store(tmp.name+'/db'));self.serial=0
    def prepare(self,data):
        self.serial+=1
        ctx=dict(convId='synthetic-printer-scope-'+str(self.serial),city='Нижний Новгород',dir='kp',channel='avito',partner='7',
                 accountTitle='Учебный мастер',origin='С1',itemTitle='Ремонт принтеров',messages=data)
        out,status=self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(status,200);self.assertFalse(out['auto_enabled'])
        if not out.get('model_task'):return out,None,None
        task=json.loads(out['model_task']['task']);candidate=dict(reply=task.get('fixed_reply') or task.get('proposed_reply') or task['decision']['next_question']['question'],needs_operator=False,
            context_review=dict(last_intent='Фактическая названная работа или симптом принтера',latest_client_meaning='Актуальная реплика в контексте предыдущего запроса',selected_step_fits=True,evidence_ids=[data[-1]['id']],note='Ручной synthetic review, без подтверждения результата операции, потолка цены, визита или номера.'))
        if task.get('item_fitment_context'):
            candidate['context_review']['item_fitment_review'] = copy.deepcopy(task['item_fitment_context']['required_review'])
        return out,task,candidate
    def finish(self,out,candidate):
        final,status=self.app.handle(dict(owner='owner',action='finalize',request_id=out['request_id'],revision=out['revision'],candidate=candidate))
        self.assertEqual(status,200);self.assertFalse(final['auto_enabled']);return final
    def test_cover_native_keeps_described_job_without_reasking_problem(self):
        out,task,c=self.prepare(rows(ADF));self.assertIsNotNone(task)
        self.assertNotIn('Что у вас случилось',c['reply']);self.assertNotIn('подключ',c['reply'].lower())
        final=self.finish(out,c);self.assertEqual(final['validation'],[]);self.assertFalse(final['needs_operator'])
    def test_dry_ink_native_asks_model_then_uses_supplied_model(self):
        out,task,c=self.prepare(rows(INK));self.assertIn('модел',c['reply'].lower());self.assertNotIn('случилось',c['reply'])
        self.assertEqual(self.finish(out,c)['validation'],[])
        out,task,c=self.prepare(rows(INK,('out','Марку и модель?'),'L366 Epson'))
        self.assertNotIn('модел',c['reply'].lower());self.assertNotIn('случилось',c['reply'])
        self.assertEqual(self.finish(out,c)['validation'],[])
    def test_range_question_is_answered_without_invented_ceiling(self):
        out,task,c=self.prepare(rows(ADF,('out','от 500 рублей услуга'),'И до скольки?'))
        final=self.finish(out,c);self.assertEqual(final['validation'],[])
        self.assertIn('Верхнюю границу',final['reply']);self.assertIn('не подтверждаю',final['reply'])
        self.assertNotIn('устраивает',final['reply']);self.assertNotIn('3000',final['reply'])
    def test_understood_is_not_new_booking_or_price_consent(self):
        data=rows(ADF,('out','от 500 рублей услуга'),('out','Без осмотра потолок не подтверждаю.'),'Ясно')
        out,task,c=self.prepare(data);self.assertEqual(out['action'],'wait')
        final=self.finish(out,c);self.assertEqual(final['validation'],[])
        self.assertNotIn('номер',final['reply']);self.assertEqual(prices.consent(data)['status'],'pending')
    def test_retailer_delivery_is_not_an_accepted_visit(self):
        data=rows(ADF,('out','Когда удобно?'),'Принтер пока в доставке, будет завтра скорее всего.')
        self.assertEqual(qs.inspect(data)['visit_time']['status'],'missing')
        out,task,c=self.prepare(data)
        if task:
            final=self.finish(out,c);self.assertEqual(final['validation'],[]);self.assertNotIn('приеду завтра',final['reply'].lower())
    def test_glass_result_and_provider_number_are_not_promised(self):
        for claim,error in [('Стекло точно останется целым.','unconfirmed_printer_operation_outcome'),
                            ('Номер мастера 79990000001.','unverified_provider_phone')]:
            out,task,c=self.prepare(rows(ADF));c['reply']=claim+' '+c['reply'];final=self.finish(out,c)
            self.assertFalse(final['reply']);self.assertIn(error,final['validation'])
    def test_explicit_restricted_printer_jobs_are_not_auto_accepted(self):
        for body in ['Нужно заменить картридж в принтере.','Нужно установить СНПЧ на Epson L366.',
                     'Переделайте принтер из лазерного в струйный.',
                     'Принтер переделан из одного типа в другой, нужен ремонт.']:
            out,task,c=self.prepare(rows(body));self.assertEqual(out['action'],'handoff');self.assertIsNone(task)

if __name__=='__main__':unittest.main()
