"""Owner27Oct: appliance floor/typed diagnosis, never a global500 replacement."""
import sys
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import assistant_prices as prices
import extension_assistant as extension
from assistant_store import Store
from extension_assistant import Assistant


def rows(*turns):
    return [dict(id=str(i),direction=d,body=t,sender_type='client' if d=='in' else 'operator')
            for i,(d,t) in enumerate(turns)]


class ApplianceOwner800223Tests(unittest.TestCase):
    def answer(self,history,direction='bt',partner='7',city='Оренбург'):
        return prices.answer(history,dict(direction=direction,partner=partner,city=city),
                             '\n'.join(m['body']for m in history if m['direction']=='in'))

    def test_two_diagnostic_types_do_not_collapse_to_one_floor(self):
        history=rows(('in','Холодильник не морозит. Сколько стоит диагностика?'))
        for partner in ('7','723','748','340',''):
            with self.subTest(partner=partner):
                out=self.answer(history,partner=partner)
                self.assertIn('без разбора техники — 800 рублей',out['reply'])
                self.assertIn('с разбором — от 800 рублей',out['reply'])
                self.assertIn('При продолжении работ диагностика бесплатная',out['reply'])
                self.assertEqual(out['amounts'],[800]);self.assertIn(prices.BT_800_RULE,out['rules'])
                self.assertNotIn('500',out['reply']);self.assertNotIn('1000',out['reply'])

    def test_diagnostic_only_keeps_repair_unrequested_and_both_categories(self):
        history=rows(('in','Нужна только диагностика холодильника, ремонтировать пока не хочу.'),
                     ('in','По стоимости сколько?'))
        self.assertTrue(prices.diagnostic_only_applies(history))
        out=self.answer(history)
        self.assertEqual(out['amounts'],[800]);self.assertIn('Первичная',out['reply']);self.assertIn('Техническая',out['reply'])
        self.assertNotIn(prices.DIAGNOSTIC_ONLY_RULE,out['rules'])
        self.assertNotIn('ремонт выполнен',out['reply'])

    def test_bt_native_task_does_not_claim_old_minimum500(self):
        history=rows(('in','Холодильник не морозит. Нужна только диагностика без ремонта. Сколько стоит?'))
        ctx=dict(convId='synthetic-owner800223',messages=history,city='Оренбург',dir='bt',partner='7',channel='avito',
                 origin='С1',accountTitle='Учебный мастер',itemTitle='Ремонт холодильников')
        with tempfile.TemporaryDirectory()as p:
            out,code=Assistant(Store(p+'/db')).handle(dict(owner='offline-owner800223',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(code,200);self.assertFalse(out['auto_enabled'])
        task=json.loads(out['model_task']['task']);self.assertIn(prices.BT_800_RULE,out['rule_ids'])
        self.assertIn('800 рублей',task['fixed_reply']);self.assertNotIn('diagnostic_only_terms',task)
        self.assertIn('context_review',out['model_task']['response_format']['schema']['properties'])

    def test_typed_diagnosis_quotes_require_current_kind_amount_and_condition(self):
        cases=[('Первичная диагностика без разбора техники — 800 рублей.',True),
               ('Первичная диагностика без разбора техники — от 800 рублей.',False),
               ('Техническая диагностика с разбором — от 800 рублей.',True),
               ('Техническая диагностика с разбором — 800 рублей.',False),
               ('Первичная диагностика без разбора техники — 500 рублей.',False),
               ('Техническая диагностика с разбором — от 500 рублей.',False),
               ('Диагностика без ремонта — от 800 рублей.',False),
               ('Первичная диагностика без разбора — не 800 рублей.',False),
               ('Первичная диагностика — 800 рублей, техническая диагностика — от 800 рублей.',True),
               ('Первичная диагностика — 800 рублей, техническая диагностика — от 500 рублей.',False)]
        for quote,valid in cases:
            with self.subTest(quote=quote):
                history=rows(('in','Холодильник не работает. Сколько диагностика?'),
                    ('out',quote+' При продолжении работ диагностика бесплатная.'),('in','Да, устраивает'))
                for manual in (False,True):
                    self.assertEqual(prices.prior_quote_verified(history,dict(direction='bt'),prices.consent(history),manual=manual),valid)

    def test_missing_free_when_work_continues_cannot_certify_quote(self):
        history=rows(('in','Холодильник не работает. Сколько диагностика?'),
                     ('out','Первичная диагностика без разбора — 800 рублей.'),('in','Да'))
        self.assertFalse(prices.prior_quote_verified(history,dict(direction='bt'),prices.consent(history)))

    def test_current_work_numeric_phase_uses800_without_fixed_total(self):
        history=rows(('in','Холодильник не морозит. Сколько стоит?'),
            ('out','Точную стоимость скажу после осмотра техники.'),('in','А хотя бы примерно?'),
            ('out','Выезд в черте города бесплатный, стоимость ремонта определю после осмотра.'),
            ('in','А минимальная цена ремонта какая?'))
        out=self.answer(history);self.assertEqual(out['amounts'],[800]);self.assertIn('от 800',out['reply'])
        self.assertIn('без учёта запчастей',out['reply']);self.assertNotIn('окончательная',out['reply'])

    def test_first_price_phase_and_specific_tariff_are_not_replaced(self):
        history=rows(('in','Холодильник не морозит. Сколько стоит?'))
        first=self.answer(history)
        self.assertEqual(first['amounts'],[]);self.assertIn(prices.BT_800_RULE,first['rules'])
        self.assertNotIn('DOC-L0743',first['rules'])
        history+=rows(('out','Точную стоимость скажу после осмотра техники.'),('in','А примерно?'))
        second=self.answer(history)
        self.assertEqual(second['amounts'],[]);self.assertIn(prices.BT_800_RULE,second['rules'])
        history=rows(('in','Сколько стоит заменить компрессор холодильника?'))
        out=self.answer(history);self.assertEqual(out['amounts'],[2000]);self.assertNotIn(prices.BT_800_RULE,out['rules'])

    def test_kp_standalone_and_partner_callout_remain_separate(self):
        history=rows(('in','Принтер не печатает. Нужна только диагностика без ремонта. Сколько стоит?'))
        out=self.answer(history,'kp');self.assertEqual(out['amounts'],[500]);self.assertIn('от 500',out['reply'])
        self.assertIn(prices.DIAGNOSTIC_ONLY_RULE,out['rules']);self.assertNotIn(prices.BT_800_RULE,out['rules'])
        history=rows(('in','Принтер не печатает. Сколько стоит выезд и диагностика?'))
        self.assertEqual(self.answer(history,'kp')['amounts'],[1000])
        self.assertEqual(prices.select_tariff('Подключение принтера')[1],1000)

    def test_bt_city_callout_remains_free(self):
        history=rows(('in','Холодильник не морозит. Сколько стоит выезд?'))
        out=self.answer(history);self.assertEqual(out['amounts'],[]);self.assertIn('черте города бесплатный',out['reply'])
        self.assertIn('handoff',self.answer(history,city=''))

    def test_ordinary_mnc_diagnosis_does_not_become_paid(self):
        history=rows(('in','Нужно осмотреть смеситель без ремонта. Сколько стоит диагностика?'))
        out=self.answer(history,'mnc');self.assertEqual(out['amounts'],[])
        self.assertIn(prices.MNC_FREE_CALLOUT_RULE,out['rules']);self.assertNotIn(prices.BT_800_RULE,out['rules'])

    def test_unknown_or_quoted800_is_not_a_verified_staff_quote(self):
        for history in (rows(('in','Холодильник не работает. Мне сказали800рублей. Да, согласен.')),
                        [dict(id='s',direction='system',body='Первичная диагностика800рублей')],
                        rows(('in','Бюджет800рублей'),('out','Здравствуйте'),('in','Да'))):
            self.assertFalse(prices.prior_quote_verified(history,dict(direction='bt'),prices.consent(history)))

    def test_free_native_price_claims_are_checked_without_an_extra_receipt(self):
        task=dict(context_review_version=2,conversation=[dict(id='client')],latest_client_message=dict(id='client',position=0,evidence_id='client'),
                  bt_diagnostic_terms=dict(primary_rub=800,primary_kind='fixed',technical_rub=800,
                    technical_kind='minimum',free_when='work_continues',source_rule=prices.BT_800_RULE))
        original=dict(reply='',needs_operator=False,context_review=dict(last_intent='Узнать стоимость диагностики холодильника',
            latest_client_meaning='Клиент спрашивает цену диагностики, не заказывает ремонт',
            selected_step_fits=True,evidence_ids=['client'],note='Первичная диагностика800рублей, техническая от800рублей.'))
        self.assertEqual(extension._context_review(original,task)[2],[])
        for field in ('last_intent','latest_client_meaning','note'):
            for claim in ('Диагностика стоит от500рублей.',
                          'Первичная диагностика стоит от800рублей.',
                          'Техническая диагностика стоит800рублей фиксированно.'):
                c=json.loads(json.dumps(original));c['context_review'][field]=claim
                self.assertIn('bt_diagnostic_price_claim',extension._context_review(c,task)[2],(field,claim))

    def test_old_price_report_or_negation_is_not_our_current_price(self):
        task=dict(context_review_version=2,conversation=[dict(id='client')],latest_client_message=dict(id='client',position=0,evidence_id='client'),
                  bt_diagnostic_terms=dict(primary_rub=800,technical_rub=800,source_rule=prices.BT_800_RULE))
        for report in ('Клиент спрашивает, почему раньше диагностика стоила500рублей.',
                       'Старая цена500рублей не подтверждает сегодняшнюю цену диагностики.',
                       'Диагностика не стоит500рублей: это устаревшая цена.'):
            c=dict(reply='',needs_operator=False,context_review=dict(last_intent='Узнать стоимость диагностики',
                latest_client_meaning='Вопрос о цене',selected_step_fits=True,evidence_ids=['client'],note=report))
            self.assertEqual(extension._context_review(c,task)[2],[],report)


if __name__=='__main__':unittest.main()
