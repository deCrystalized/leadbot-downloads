"""A literal unknown/denial/report is not an unblocking order or tariff consent."""
import unittest
import assistant_catalog as catalog
import assistant_prices as prices
import contact_facts
from test_history_intake106 import assess,known


def history(*turns):
    return [dict(id='c'+str(i),direction=d,sender_type='client'if d=='in'else'operator',body=t,
                 **({'delivery_status':'delivered'}if d=='out'else{}))for i,(d,t)in enumerate(turns)]


def symptom():
    return history(('in','Вода в унитазе медленно уходит, потом всё-таки сходит.'))


class ClogScope210Tests(unittest.TestCase):
    def source(self,city='Чита'):
        return dict(known('mnc','Сантехник'),city=city)

    def answered(self,answer):
        return history(('in','Вода в унитазе медленно уходит, потом всё-таки сходит.'),
                       ('out','У вас засор в унитазе?'),('in',answer))

    def test_actual_uncertainty_is_not_a_drain_service_or_unconditional_tariff(self):
        messages=self.answered('Я не знаю, засор ли это. Вода уходит, просто медленно.')
        out=assess(messages,self.source())
        self.assertEqual(contact_facts.collect(messages,self.source())['confirmed_clog'],{})
        self.assertNotIn('drain',[i['id']for i in out['service']['items']])
        self.assertNotIn('mandatory_price',out);self.assertIn(out['action'],('question','draft'))
        self.assertNotEqual(out['next_question']['kind'],'clog_confirmation')
        self.assertIn('причин',' '.join(out['required_text']).lower())

    def test_pure_pricing_and_service_view_use_the_same_uncertainty_boundary(self):
        messages=self.answered('Я не знаю, засор ли это. Вода уходит медленно.')
        facts=contact_facts.collect(messages,self.source());text='\n'.join(m['body']for m in messages if m['direction']=='in')
        selection=contact_facts.intent_text(text,facts)
        self.assertNotIn('drain',[i['id']for i in catalog.choose(selection,self.source())['items']])
        self.assertIsNone(prices.mandatory(messages,self.source(),text))
        row=facts['clog_work_context']['uncertain_reports'][-1]
        self.assertEqual(row['message_id'],'c2');self.assertIn('не знаю',row['quote'])
        self.assertEqual(row['question_message_id'],'c1')

    def test_uncertain_word_orders_do_not_require_one_frozen_sentence(self):
        for text in ('Не уверен, что это засор.', 'Возможно, засор, я не знаю.',
                     'Засор ли это, не знаю.', 'Может быть засор?', 'Это засор?'):
            out=assess(self.answered(text),self.source())
            self.assertNotIn('mandatory_price',out,text)
            self.assertNotIn('drain',[i['id']for i in out['service']['items']],text)

    def test_short_unknown_answer_does_not_repeat_the_same_diagnostic_question(self):
        for text in ('Не знаю','Не уверен','Не понимаю'):
            out=assess(self.answered(text),self.source())
            self.assertNotEqual(out.get('next_question',{}).get('kind'),'clog_confirmation',text)
            self.assertNotIn('mandatory_price',out)

    def test_explicit_blockage_report_and_unblocking_questions_keep_city_metre_price(self):
        for text in ('Нужно устранить засор унитаза', 'Прочистить канализацию',
                     'Сколько стоит устранить засор?', 'Засор в унитазе',
                     'Сможете устранить засор?', 'Можете прочистить канализацию?'):
            for city,amount in [('Чита',500),('Москва',800)]:
                out=assess(history(('in',text)),self.source(city))
                self.assertIn(amount,out['mandatory_price']['amounts'],(text,city))
                self.assertIn('погонный метр',out['mandatory_price']['reply'])

    def test_real_yes_to_the_observed_question_keeps_the_source_and_tariff(self):
        messages=self.answered('Да');facts=contact_facts.collect(messages,self.source())
        self.assertEqual(facts['confirmed_clog']['message_id'],'c2')
        self.assertEqual(facts['confirmed_clog']['question_message_id'],'c1')
        self.assertIn(500,assess(messages,self.source())['mandatory_price']['amounts'])

    def test_our_delivered_bot_question_is_real_history_not_a_planned_question(self):
        for role in ('bot','assistant'):
            messages=self.answered('Да');messages[-2]['sender_type']=role
            self.assertEqual(contact_facts.confirmed_clog(messages)['question_message_id'],'c1')
            messages[-1]['body']='Не знаю'
            out=assess(messages,self.source())
            self.assertNotEqual(out.get('next_question',{}).get('kind'),'clog_confirmation')
            self.assertNotIn('mandatory_price',out)

    def test_negative_or_foreign_report_does_not_order_unblocking(self):
        for text in ('Засора нет.', 'Это не засор.', 'Сосед сказал: «Засор в унитазе».',
                     'Мастер сказал, что это засор.', 'Если засор когда-нибудь появится, напишу.'):
            out=assess(self.answered(text),self.source())
            self.assertNotIn('mandatory_price',out,text)
            self.assertNotIn('drain',[i['id']for i in out['service']['items']],text)

    def test_role_and_failed_question_cannot_supply_confirmation(self):
        for role in ('system','operator','avito','assistant'):
            messages=self.answered('Да');messages[-1]['sender_type']=role
            self.assertEqual(contact_facts.confirmed_clog(messages),{},role)
        for status in ('pending','failed','sending'):
            messages=self.answered('Да');messages[-2]['delivery_status']=status
            self.assertEqual(contact_facts.confirmed_clog(messages),{},status)

    def test_a_quoted_staff_question_cannot_be_answered_as_our_qualification(self):
        messages=self.answered('Да');messages[-2]['body']='Сосед спрашивал: «У вас засор?»'
        self.assertEqual(contact_facts.confirmed_clog(messages),{})

    def test_later_uncertainty_retracts_confirmation_without_inventing_a_cause(self):
        for earlier in (self.answered('Да'), history(('in','Засор в унитазе'))):
            messages=earlier+[dict(id='correction',direction='in',sender_type='client',body='Нет, я не уверен, что это засор в унитазе.')]
            self.assertEqual(contact_facts.confirmed_clog(messages),{})
            out=assess(messages,self.source());self.assertNotIn('mandatory_price',out)
            self.assertNotIn('drain',[i['id']for i in out['service']['items']])

    def test_new_order_does_not_inherit_old_clog_confirmation(self):
        messages=self.answered('Да')+[dict(id='new',direction='in',sender_type='client',body='Новая заявка: нужно собрать комод.')]
        self.assertEqual(contact_facts.confirmed_clog(messages),{})
        out=assess(messages,self.source());self.assertNotIn('mandatory_price',out)

    def test_actual_other_unblocking_job_survives_a_separate_uncertain_toilet_report(self):
        messages=history(('in','Унитаз медленно смывает, не знаю, засор ли это. Но нужно прочистить засор в раковине.'))
        out=assess(messages,self.source());self.assertIn('drain',[i['id']for i in out['service']['items']])
        self.assertIn(500,out['mandatory_price']['amounts'])

    def test_nonclient_duplicate_cannot_erase_a_real_client_order(self):
        messages=history(('in','Нужно устранить засор унитаза'),('in','Нужно устранить засор унитаза'))
        messages[-1]['sender_type']='system'
        out=assess(messages,self.source());self.assertIn(500,out['mandatory_price']['amounts'])

    def test_nonclient_clog_words_do_not_add_a_new_drain_service(self):
        messages=symptom()+[dict(id='system-new',direction='in',sender_type='system',body='Нужно устранить засор унитаза')]
        messages[-1]['sender_type']='system'
        facts=contact_facts.collect(messages,self.source());view=contact_facts.intent_text('\n'.join(m['body']for m in messages if m['direction']=='in'),facts)
        self.assertNotIn('drain',[i['id']for i in catalog.choose(view,self.source())['items']])

    def test_conditional_price_question_is_answered_conditionally_without_tariff_consent(self):
        messages=symptom()+[dict(id='conditional',direction='in',sender_type='client',body='Если это засор, сколько будет стоить устранить?')]
        out=assess(messages,self.source())
        self.assertIn('если',out.get('forced_reply','').lower())
        self.assertIn('500',out['forced_reply']);self.assertIn('погонный метр',out['forced_reply'])
        self.assertNotIn('устраивает',out['forced_reply'].lower());self.assertNotIn('mandatory_price',out)
        self.assertNotIn('drain',[i['id']for i in out['service']['items']])

    def test_two_genuinely_unanswered_questions_keep_the_old_terminal_guard(self):
        messages=history(('in','Унитаз медленно смывает'),('out','У вас засор?'),('in','Не понимаю'),
                         ('out','Это засор?'),('in','Не знаю'))
        self.assertEqual(assess(messages,self.source())['action'],'handoff')

    def test_input_history_is_not_rewritten_by_the_selection_projection(self):
        messages=self.answered('Не знаю, засор ли это.');before=[dict(x)for x in messages]
        facts=contact_facts.collect(messages,self.source());contact_facts.intent_text('\n'.join(x['body']for x in messages),facts)
        self.assertEqual(messages,before)
