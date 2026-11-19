"""KP minimum retained; MNC superseded129 and BT typed800 superseded223.

Original120/117 assertions and first failures are frozen in latest-turn212;
only explicitly changed BT prices/conditions follow OWNER-BT-800-20261027.
"""
import json
import unittest
import test_diagnostic_reasoning119 as helpers
import assistant_prices as prices
import contact_facts


def rows(*texts):
    return [dict(id=str(i),direction='in',sender_type='client',body=t) for i,t in enumerate(texts)]


class DiagnosticOnlyMinimum120Tests(unittest.TestCase):
    setUp=helpers.DiagnosticReasoning119Tests.setUp
    prepare=helpers.DiagnosticReasoning119Tests.prepare
    candidate=helpers.DiagnosticReasoning119Tests.candidate
    finish=helpers.DiagnosticReasoning119Tests.finish

    def test_all_directions_and_partners_use_minimum_not_fixed_or_refusal_fee(self):
        for direction in ['kp','bt']:
            for partner in ['7','723','748','340','']:
                with self.subTest(direction=direction,partner=partner):
                    ms=rows('Мне нужна только диагностика, без ремонта. Сколько стоит?')
                    out=prices.answer(ms,dict(direction=direction,partner=partner),'')
                    expected=('Диагностика без ремонта — от 500 рублей.' if direction=='kp' else
                        'Первичная диагностика без разбора техники — 800 рублей. '
                        'Техническая диагностика с разбором — от 800 рублей. При продолжении работ диагностика бесплатная.')
                    self.assertEqual(out['reply'],expected)
                    self.assertEqual(out['amounts'],[500 if direction=='kp' else 800])
                    self.assertIn(prices.DIAGNOSTIC_ONLY_RULE if direction=='kp'else prices.BT_800_RULE,out['rules'])
                    self.assertIsNone(prices.partner_visit_terms(ms,dict(direction=direction,partner=partner)))

    def test_diagnostic_service_survives_a_generic_price_followup(self):
        ms=rows('Нужна только диагностика холодильника, ремонт не нужен.','По стоимости сколько выйдет?')
        self.assertTrue(contact_facts.standalone_diagnostic(ms))
        for direction in ['kp','bt']:
            self.assertIn('от 500'if direction=='kp'else'от 800',prices.answer(ms,dict(direction=direction,partner='7'),'')['reply'])

    def test_reported_or_system_service_and_withdrawn_diagnostic_do_not_apply(self):
        for ms in [rows('Мастер сказал, что нужна только диагностика без ремонта.'),
                   [dict(id='a',direction='system',body='Нужна только диагностика без ремонта')],
                   rows('Нужна только диагностика холодильника.','Теперь нужен ремонт'),
                   rows('Нужна только диагностика.','Не нужна диагностика, хочу подключить принтер')]:
            self.assertFalse(contact_facts.standalone_diagnostic(ms))

    def test_negated_diagnostic_and_reported_quote_are_not_client_orders(self):
        for text in ['Мне не нужна только диагностика.',
                     'Вы сказали: «только диагностика без ремонта».',
                     'Только диагностика не нужна. Хочу полноценный ремонт.']:
            self.assertFalse(contact_facts.standalone_diagnostic(rows(text)),text)
        ms=rows('Нужна диагностика холодильника, ремонтировать пока не хочу.')
        self.assertTrue(contact_facts.standalone_diagnostic(ms))
        self.assertIn('от 800',prices.answer(ms,dict(direction='bt',partner='7'),'')['reply'])

    def test_independent_review_negation_change_and_additional_repair(self):
        for ms in [rows('Телевизор не включается. Нужна не только диагностика, но и ремонт. Сколько стоит диагностика?'),
                   rows('Без ремонта не обойтись, нужна диагностика и ремонт. Цена диагностики?'),
                   rows('Нужна только диагностика без ремонта и замените подсветку. Сколько стоит?'),
                   rows('Нужна только диагностика без ремонта.','Передумал: нужен и ремонт телевизора. Цена диагностики?')]:
            self.assertFalse(contact_facts.standalone_diagnostic(ms))
        ms=rows('Другие мастера сказали, что телевизор точно нерабочий. Нужна только диагностика без ремонта. Сколько стоит?')
        self.assertTrue(contact_facts.standalone_diagnostic(ms))
        self.assertIn('от 500',prices.answer(ms,dict(direction='kp',partner='7'),'')['reply'])
        ms=rows('Нужна диагностика телевизора и замена подсветки. Сколько стоит диагностика и сколько ремонт?')
        out=prices.answer(ms,dict(direction='kp',partner='7'),'')
        self.assertIn('1000',out['reply'])
        self.assertIn('Стоимость ремонта определю после осмотра.',out['reply'])

    def test_ordinary_kp_callout_and_unrelated_work_prices_remain(self):
        ms=rows('Принтер не печатает. Сколько стоит выезд и диагностика?')
        self.assertEqual(prices.answer(ms,dict(direction='kp',partner='7'),'')['amounts'],[1000])
        self.assertEqual(prices.select_tariff('Подключение принтера')[1],1000)

    def test_separate_repair_price_question_is_not_lost_or_ordered(self):
        ms=rows('Сколько стоит диагностика без ремонта? И сколько примерно ремонт от минимума до максимума?')
        out=prices.answer(ms,dict(direction='bt',partner='7'),'')
        self.assertIn('от 800',out['reply'])
        self.assertIn('Стоимость ремонта определю после осмотра.',out['reply'])
        self.assertFalse(contact_facts.standalone_diagnostic(ms)['repair_requested'])

    def test_normal_form_quote_verifies_only_the_minimum500(self):
        for direction in ['kp','bt']:
            for quote,valid in [('Диагностика без ремонта — от 500 рублей.',True),
                                ('Диагностика — 500 рублей.',False),
                                ('Выезд и диагностика — 1000 рублей.',False)]:
                ms=rows('Нужна только диагностика, без ремонта. Сколько стоит?')
                ms += [dict(id='quote',direction='out',body=quote),dict(id='yes',direction='in',body='Да, устраивает')]
                self.assertEqual(prices.prior_quote_verified(ms,dict(direction=direction,partner='7'),prices.consent(ms)),valid and direction=='kp')

    def test_native_minimum_proof_and_real_finalize_are_shared(self):
        out,t=self.prepare(job='Нужна только диагностика принтера HP Deskjet 6075, без ремонта.')
        self.assertNotIn('diagnostic_fee_terms',t)
        self.assertEqual(t['diagnostic_only_terms']['minimum_rub'],500)
        self.assertEqual(t['fixed_reply'],'Диагностика без ремонта — от 500 рублей.')
        proof=out['model_task']['response_format']['schema']['properties']['context_review']['properties']['diagnostic_only_review']
        self.assertEqual(proof['properties']['price_kind']['enum'],['minimum'])
        c=self.candidate(t);c['context_review']['note']='Отдельная диагностика без ремонта оценивается от500рублей; это минимум.'
        final=self.finish(out,c)
        self.assertEqual(final['validation'],[])
        self.assertEqual(final['reply'],'Диагностика без ремонта — от 500 рублей.')

    def test_actual_normal_form_uses_same_minimum_without_partner1000_requirement(self):
        for direction,job,title in [('kp','Принтер не печатает.','Ремонт принтеров'),
                                    ('bt','Холодильник не морозит.','Ремонт холодильников')]:
            ms=rows(job+' Нужна только диагностика, без ремонта. Сколько стоит?')
            quote=('Диагностика без ремонта — от 500 рублей.' if direction=='kp' else
                   'Первичная диагностика без разбора — 800 рублей. При продолжении работ диагностика бесплатная.')
            ms += [dict(id='quote',direction='out',body=quote),
                   dict(id='yes',direction='in',body='Да, устраивает')]
            ctx=dict(convId='synthetic-diagonly-form120-'+direction,dir=direction,city='Оренбург',channel='avito',
                     partner='7',accountTitle='Учебный мастер',origin='С1',itemTitle=title,messages=ms)
            out,code=self.app.handle(dict(owner='owner',action='checklist',dir=direction,ctx=ctx))
            self.assertEqual(code,200)
            self.assertNotIn('partner_visit_terms',[r['key'] for r in out['results']])
            self.assertTrue(next(r for r in out['results'] if r['key']=='price_consent')['done'])

    def test_wrong_minimum_type_fixed_price_or_invented_repair_is_rejected(self):
        for field,value in [('minimum_rub',1000),('minimum_rub',500.0),('price_kind','fixed'),('repair_requested',True)]:
            with self.subTest(field=field,value=value):
                self.setUp()
                out,t=self.prepare(job='Нужна только диагностика принтера HP Deskjet 6075, без ремонта.')
                c=self.candidate(t);c['context_review']['diagnostic_only_review'][field]=value
                self.assertIn('diagnostic_only_review_mismatch',self.finish(out,c)['validation'])


if __name__=='__main__':unittest.main()
