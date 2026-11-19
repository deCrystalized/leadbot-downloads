"""Synthetic boundary controls derived from a fully read historical BT case.

These tests are not model generations, manual case credit or customer writes.
"""
import json
import tempfile
import unittest
from unittest.mock import patch

import assistant_prices as prices
import assistant_policy as policy
import contact_facts
from assistant_store import Store
from extension_assistant import Assistant
from test_assistant import context


def m(body, direction='in', mid='client', **extra):
    return dict(id=mid, direction=direction, body=body, **extra)


def known():
    return dict(direction='bt', city='Орёл', channel='avito', partner='7')


def quote_rows(quote='От 800 рублей, точнее после осмотра'):
    # Synthetic current-tariff variant223; archived source140 stays unchanged.
    return [m('Бойлер Электролюкс 25 литров не греет. Сколько ремонт стоит?',mid='job'),
            m(quote,'out','price'),m('Хорошо',mid='yes')]


class BoilerHistory140Tests(unittest.TestCase):
    def prepare(self, rows):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        env=patch.dict('os.environ',LEADBOT_PERSONAL_OWNER_ID='offline140',LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start();self.addCleanup(env.stop)
        app=Assistant(Store(temp.name+'/db'))
        ctx=context(rows,convId='synthetic-boiler140',city='Орёл',dir='bt',channel='avito',
                    accountTitle='Матвей БТ',itemTitle='Ремонт бойлеров / Выезд по городу')
        d,c=app.handle(dict(owner='offline140',action='preview',ctx=ctx,wording_mode='neural_review'))
        self.assertEqual(c,200);self.assertFalse(d['auto_enabled'])
        return app,d,json.loads(d['model_task']['task'])if d.get('model_task')else None

    def test_explicit_repair_question_gets_qualified_capability_answer_before_gas_question(self):
        _,d,t=self.prepare([m('Здравствуйте, бойлер перестал греть воду. Вы занимаетесь ремонтом?')])
        self.assertTrue(d['pending_model']);self.assertIn('Электрические бойлеры ремонтируем.',t['proposed_reply'])
        self.assertIn('DOC-L0389',d['rule_ids'])
        self.assertEqual(t['decision']['next_question']['kind'],'gas_type')
        self.assertEqual(t['device_power_condition']['status'],'missing')

    def test_brand_capacity_and_hypothetical_heater_do_not_establish_absence_of_gas(self):
        _,_,t=self.prepare([m('Бойлер не греет',mid='job'),m('Какой он?','out','asked'),
                           m('Электролюкс 25 литров',mid='brand'),m('Скорее всего тэны, реле всё время горело',mid='guess')])
        self.assertFalse(t['device_power_condition']['brand_capacity_proves_no_gas'])
        self.assertEqual(t['device_power_condition']['status'],'missing')
        self.assertFalse(t['device_power_condition']['evidence_id'])

    def test_confirmed_gas_does_not_get_the_positive_repair_acknowledgement(self):
        _,d,t=self.prepare([m('Газовый бойлер, ремонтируете?')])
        self.assertEqual(d['action'],'refuse')
        self.assertNotIn('Электрические бойлеры ремонтируем.',t['proposed_reply'] if t else d.get('reply',''))

    def test_native_question_enum_keeps_the_empty_operator_exit(self):
        app,d,t=self.prepare([m('Бойлер не греет')])
        schema=d['model_task']['response_format']['schema']
        self.assertEqual(schema['properties']['reply']['enum'],['',t['decision']['next_question']['question']])
        self.assertIn('selected_step_fits',schema['properties']['reply']['description'])
        for fits,needs in [(True,False),(False,True)]:
            with self.subTest(fits=fits):
                # Each finalization has its own temporary request, not a retry.
                app,d,t=self.prepare([m('Бойлер не греет')])
                review=dict(last_intent='Ремонт бойлера',latest_client_meaning='Бойлер не греет',
                            selected_step_fits=fits,evidence_ids=['client'],note='Ручной синтетический контроль.',
                            device_power_review=t['device_power_condition']['required_review'])
                out,c=app.handle(dict(owner='offline140',action='finalize',request_id=d['request_id'],revision=d['revision'],
                                     candidate=dict(reply='',needs_operator=needs,context_review=review)))
                self.assertEqual(c,200);self.assertFalse(out['reply']);self.assertTrue(out['needs_operator'])
                if fits:self.assertIn('accepted_step_empty_reply',out['validation'])
                else:self.assertIn('model_context_mismatch',out['validation'])

    def test_native_power_proof_is_grounded_and_does_not_force_model_approval(self):
        _,d,t=self.prepare([m('Бойлер Электролюкс 25 литров, наверное ТЭН',mid='guess')])
        proof=d['model_task']['response_format']['schema']['properties']['context_review']['properties']['device_power_review']
        self.assertEqual(proof['properties']['status']['enum'],['missing'])
        self.assertEqual(proof['properties']['client_answer_evidence_id']['enum'],[''])
        self.assertEqual(proof['properties']['type_established_by_client']['enum'],[False])
        self.assertNotIn('enum',d['model_task']['response_format']['schema']['properties']['context_review']['properties']['selected_step_fits'])
        self.assertLess(d['model_task']['system'].index('device_power_condition'),d['model_task']['system'].index('История conversation'))
        self.assertLess(list(t).index('device_power_condition'),list(t).index('decision'))

    def test_wrong_power_proof_cannot_promote_brand_or_hypothesis_to_a_client_answer(self):
        for proof in [None,dict(status='answered',client_answer_evidence_id='client',type_established_by_client=True),
                      dict(status='missing',client_answer_evidence_id='',type_established_by_client=0)]:
            with self.subTest(proof=proof):
                app,d,t=self.prepare([m('Бойлер Электролюкс 25 литров, наверное ТЭН')])
                review=dict(last_intent='Ремонт бойлера',latest_client_meaning='Предполагает проблему с ТЭНом',
                            selected_step_fits=True,evidence_ids=['client'],note='Требуется уточнение типа.')
                if proof is not None:review['device_power_review']=proof
                out,c=app.handle(dict(owner='offline140',action='finalize',request_id=d['request_id'],revision=d['revision'],
                                     candidate=dict(reply=t['decision']['next_question']['question'],needs_operator=False,context_review=review)))
                self.assertEqual(c,200);self.assertTrue(out['needs_operator']);self.assertFalse(out['reply'])
                self.assertTrue(out['validation'])

    def test_explicit_electric_answer_moves_to_another_question_without_power_proof(self):
        _,d,t=self.prepare([m('Бойлер не греет',mid='job'),m('Газовый или электрический?','out','asked'),
                           m('Электрический, без газа',mid='answer')])
        self.assertNotEqual(t['decision']['next_question']['kind'],'gas_type')
        self.assertNotIn('device_power_condition',t)

    def test_second_bt_price_stage_uses_free_city_callout_after_a_real_inspection_answer(self):
        rows=[m('Сколько ремонт стоит?',mid='first'),
              m('Давайте проиеду посмотрю все и вас на месте сортирую','out','answer'),
              m('Приблизительно можете сказать, потолок цены?',mid='second')]
        self.assertEqual(prices.price_turns(rows),2)
        out=prices.answer(rows,known(),'Бойлер перестал греть')
        self.assertFalse(out['amounts']);self.assertIn('Выезд в черте города бесплатный',out['reply'])
        self.assertIn('DOC-L0722',out['rules'])

    def test_documented_bt_minimum_is_independent_of_bot_wording_stage(self):
        rows=quote_rows();state=prices.consent(rows)
        self.assertLess(prices.price_turns(rows),3)
        self.assertTrue(prices.prior_quote_verified(rows,known(),state))
        self.assertTrue(prices.prior_quote_verified(rows,known(),state,manual=True))

    def test_wrong_bt_total_fee_units_and_special_minima_stay_unverified(self):
        for quote in ['500 рублей ремонт','От 1000 рублей','От 500 рублей за час',
                      'От 500 рублей за всё','Выезд от 500 рублей','Диагностика от 500 рублей',
                      'От 500 рублей с запчастями','От 500 рублей, все материалы включены',
                      'От 800 рублей за час','От 800 рублей за всё','Выезд от 800 рублей',
                      'Диагностика от 800 рублей','От 800 рублей с запчастями',
                      'От 800 рублей, все материалы включены']:
            rows=quote_rows(quote)
            with self.subTest(quote=quote):self.assertFalse(prices.prior_quote_verified(rows,known(),prices.consent(rows)))
        for job in ['Замена подшипника стиральной машины','Заправка фреоном холодильника','Замена компрессора холодильника']:
            rows=[m(job),m('От 500 рублей','out','price'),m('Да',mid='yes')]
            self.assertFalse(prices.prior_quote_verified(rows,known(),prices.consent(rows)))

    def test_company_question_gets_the_known_service_format_not_an_invented_legal_status(self):
        rows=quote_rows()[:2]+[m('Вы фирма?',mid='company')]
        _,d,t=self.prepare(rows)
        self.assertIn('с выездом на адрес',t['proposed_reply'])
        self.assertNotIn('Такая стоимость вас устраивает',t['proposed_reply'])
        self.assertNotRegex(t['proposed_reply'],r'частный|компани|фирм|ООО|ИП')
        self.assertEqual(prices.consent(rows)['status'],'pending')

    def test_time_question_is_answered_while_price_consent_remains_pending(self):
        rows=quote_rows()[:2]+[m('Вы фирма?',mid='company'),m('Нет','out','staff'),
                             m('Хорошо, сегодня во сколько можете подъехать?',mid='time')]
        _,d,t=self.prepare(rows)
        self.assertNotIn('Такая стоимость вас устраивает',t['proposed_reply'])
        self.assertRegex(t['proposed_reply'],r'Через|Часы приёма')
        self.assertEqual(prices.consent(rows)['status'],'pending')
        self.assertFalse(d.get('lead',{}).get('can_create_automatically'))

    def test_short_minimum_repeat_preserves_the_actual_currency_quote_without_new_consent(self):
        rows=quote_rows('От 500 рублей, точнее после осмотра')[:2]+[m('500 рублей замена тэнов?',mid='ask'),m('От 500','out','short')]
        self.assertFalse(prices.unverified_bare_quote(rows))
        state=prices.consent(rows);self.assertEqual(state['message_id'],'price')
        self.assertEqual(state['status'],'pending');self.assertEqual(state['amount'],500)

    def test_unbound_changed_and_foreign_currency_short_quotes_stay_unverified(self):
        for rows in [[m('От 500','out','short')],
                     [m('От 800 рублей','out','old'),m('От 500','out','short')],
                     [m('От 500 рублей','out','old'),m('От 500 долларов','out','foreign'),m('От 500','out','short')]]:
            self.assertTrue(prices.unverified_bare_quote(rows))

    def test_price_minimum_question_is_answered_without_certifying_replacement_for_500(self):
        # Historical test ID retained; today's800floor is the positive variant.
        rows=quote_rows()[:2]+[m('800 рублей замена тэнов?',mid='ask')]
        out=prices.clarify_named_tariff(rows,known())
        self.assertIn('а не фиксированная цена замены',out['reply'])
        self.assertIn('после осмотра',out['reply']);self.assertEqual(out['amounts'],[800])
        self.assertEqual(prices.consent(rows)['status'],'pending')
        old=quote_rows('От 500 рублей, точнее после осмотра')[:2]+[m('500 рублей замена тэнов?',mid='ask')]
        self.assertIsNone(prices.clarify_named_tariff(old,known()))
        self.assertFalse(prices.prior_quote_verified(old,known(),prices.consent(old)))

    def test_explicit_visit_withdrawal_and_courtesy_are_not_a_new_sales_opportunity(self):
        for text in ['Не нужно ко мне приезжать, я нашла человека, кто назвал мне сумму ремонта. Спасибо за беспокойство.',
                     'Не приезжайте. Спасибо.', 'Не надо к нам приходить, уже нашли другого. Благодарю за помощь.']:
            with self.subTest(text=text):self.assertTrue(contact_facts.explicit_help_withdrawal(text))

    def test_quoted_conditional_date_change_and_new_work_do_not_become_unconditional_withdrawal(self):
        for text in ['Если не договоримся, не нужно ко мне приезжать', 'Не нужно ко мне приезжать?',
                     'Мастер сказал: «Не нужно ко мне приезжать»', 'Не нужно ко мне приезжать сегодня, лучше завтра',
                     'Не приезжайте. Но всё же помощь нужна, приезжайте.', 'Не нужно менять ТЭН, нужен только осмотр']:
            with self.subTest(text=text):self.assertFalse(contact_facts.explicit_help_withdrawal(text))

    def test_literal_relative_hour_confirmation_is_existing_visit_evidence_not_creation(self):
        rows=[m('Сегодня во сколько можете подъехать?',mid='time'),m('Через час-полтора удобно вам будет?','out','offer'),
              m('Адрес и телефон?','out','contacts'),m('ул. Ленина 28, кв42',mid='address'),m('Через час, удобно будет',mid='accept')]
        evidence=policy._accepted_staff_visit(rows)
        self.assertEqual(evidence['proposal_message_id'],'offer');self.assertEqual(evidence['answer_message_id'],'accept')
        self.assertNotIn('crm_request_id',evidence)
        rows += [m('Хорошо, ожидайте','out','ok'),m('Не нужно ко мне приезжать. Спасибо за беспокойство.',mid='cancel')]
        _,d,_=self.prepare(rows)
        self.assertEqual(d['action'],'handoff');self.assertIn('отмену',d['reason'])
        self.assertFalse(d['client_decline_evidence']['crm_cancellation_confirmed'])

    def test_relative_echo_without_a_valid_visit_offer_is_not_accepted(self):
        for proposal in [None,'Позвоню через час, удобно?', 'Через два часа удобно?',
                         'Детали доставят через час, удобно?', 'Ремонт будет готов через час, удобно?',
                         'Через час-полтора удобно?']:
            rows=[m('Ремонт бойлера',mid='job')]
            if proposal:rows.append(m(proposal,'out','offer',out_pending=proposal=='Через час-полтора удобно?'))
            rows.append(m('Через час, удобно будет',mid='accept'))
            self.assertIsNone(policy._accepted_staff_visit(rows))

    def test_decline_evidence_does_not_move_to_a_later_staff_price_pitch(self):
        rows=[m('Ремонт бойлера',mid='job'),m('Не нужно ко мне приезжать. Спасибо за беспокойство.',mid='decline'),
              m('От 500 рублей работа','out','late-staff')]
        _,d,_=self.prepare(rows)
        self.assertEqual(d['client_decline_evidence']['message_id'],'decline')
        self.assertEqual(d['client_decline_evidence']['quote'],rows[1]['body'])
        self.assertEqual(d['client_decline_evidence']['source'],'client_message')
        self.assertFalse(d['client_decline_evidence']['crm_cancellation_confirmed'])

    def test_following_thanks_keeps_the_actual_decline_quote_and_client_identity(self):
        rows=[m('Ремонт бойлера',mid='job'),m('Помощь не нужна, нашла другого мастера.',mid='decline'),
              m('Спасибо!',mid='thanks'),m('От 500 рублей работа','out','late-staff')]
        _,d,_=self.prepare(rows)
        self.assertEqual(d['client_decline_evidence']['message_id'],'decline')
        self.assertEqual(d['client_decline_evidence']['quote'],rows[1]['body'])
        self.assertFalse(d['reply']);self.assertFalse(d['lead']['can_create_automatically'])


if __name__=='__main__':unittest.main()
