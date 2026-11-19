"""Normal-form minima, exact commitments and independent client consent."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_prices as prices
from assistant_store import Store
from extension_assistant import Assistant


def history(job, quote, reply='Да, устраивает'):
    return [dict(id=str(i), direction=d, body=b) for i, (d, b) in enumerate(
        [('in', job), ('out', quote)] + ([('in', reply)] if reply else []))]


class ManualHangingPrinterPrices(unittest.TestCase):
    def form(self, rows, direction='mnc'):
        ctx=dict(convId='synthetic-manual-minimum', city='Череповец', dir=direction,
                 channel='avito', partner='7', accountTitle='Михаил МНЧ' if direction=='mnc' else 'Новый КП',
                 origin='В75', itemTitle='Мастер на час' if direction=='mnc' else 'Ремонт принтеров', messages=rows)
        with tempfile.TemporaryDirectory() as tmp:
            out, code=Assistant(Store(tmp+'/db')).handle(dict(owner='offline', action='checklist', ctx=ctx))
        self.assertEqual(code, 200);self.assertFalse(out['auto_enabled'])
        return out

    def test_documented_hanging_minimum_is_valid_independently_of_script_stage(self):
        rows=history('Сколько стоит повесить карниз? Стены бетон.', 'От 800 рублей, точнее по объёму на месте. Такая стоимость вас устраивает?')
        self.assertEqual(prices.price_turns(rows), 1)
        out=self.form(rows)
        self.assertFalse(out['hard_block']);self.assertIn('DOC-L0353',out['rule_ids'])
        consent_row=next(r for r in out['results'] if r['key']=='price_consent')
        self.assertTrue(consent_row['done'])
        self.assertEqual([r['message_id'] for r in consent_row['evidence']],['1','2'])
        answer=prices.answer(rows[:1],dict(direction='mnc'),rows[0]['body'])
        self.assertEqual(answer['amounts'],[])

    def test_pending_minimum_is_not_accepted_by_previous_material_answer_or_later_time_ok(self):
        rows=history('Повесить карниз, стены бетон.', 'От 800 рублей', None)
        rows += [dict(id='time',direction='out',body='В 12 удобно?'),dict(id='ok',direction='in',body='Ок')]
        out=self.form(rows)
        self.assertTrue(out['hard_block']);self.assertIn('явное согласие',out['reason'])
        self.assertFalse(next(r for r in out['results'] if r['key']=='price_consent')['done'])

    def test_undocumented_exact_hanging_commitment_remains_blocked_with_original_quote_and_recovery(self):
        # DOC-L0525 explicitly prices one curtain rail at 800; a mirror is
        # 1000 (DOC-L0521), so its unsupported 800 total still needs review.
        rows=history('Цена повесить зеркало. Бетон.', '800 рублей работа будет')
        out=self.form(rows)
        self.assertTrue(out['hard_block']);self.assertIn('фиксированная',out['reason'])
        self.assertEqual(out['price_review']['quote'],'800 рублей работа будет')
        self.assertIn('от 800',out['price_review']['recovery'])
        self.assertEqual(out['price_review']['message_id'],'1')

    def test_fixed_unit_wrong_amount_bundle_or_fee_never_become_hanging_minimum(self):
        for quote in ('От 1000 рублей', 'От 800 рублей за час', 'От 800 рублей за штуку',
                      'От 800 рублей за всё', 'Диагностика от 800 рублей', 'От 800 рублей, максимум 800 рублей'):
            self.assertTrue(self.form(history('Повесить карниз, стены бетон',quote))['hard_block'],quote)
        out=self.form(history('Повесить карниз и установить унитаз','От 800 рублей'))
        self.assertTrue(out['hard_block'])

    def test_documented_curtain_rail_fixed_price_is_not_rewritten_as_a_minimum(self):
        for quote in ('800 рублей', '800 рублей работа будет', '800 рублей за штуку'):
            out=self.form(history('Повесить карниз, стены бетон',quote))
            self.assertFalse(out['hard_block']); self.assertIn('DOC-L0525',out['rule_ids'])
            self.assertTrue(next(r for r in out['results'] if r['key']=='price_consent')['done'])

    def test_ordinary_printer_repair_minimum_is_not_confused_with_bot_speech_order(self):
        rows=history('Canon PIXMA G3430 пропускает жёлтый цвет. Сколько стоит ремонт?',
                     'От 500 рублей такая услуга, точнее на месте', 'Хорошо')
        out=self.form(rows,'kp')
        self.assertFalse(out['hard_block']);self.assertIn('DOC-L0743',out['rule_ids'])
        self.assertTrue(next(r for r in out['results'] if r['key']=='price_consent')['done'])
        self.assertEqual(prices.answer(rows[:1],dict(direction='kp'),rows[0]['body'])['amounts'],[])

    def test_printer_fixed_total_unit_and_wrong_minimum_remain_blocked(self):
        for quote in ('500 рублей ремонт', 'От 500 рублей за час', 'От 1000 рублей', 'От 500 рублей за всё'):
            self.assertTrue(self.form(history('Canon G3430 не печатает',quote),'kp')['hard_block'],quote)

    def test_repair_minimum_does_not_certify_partner_diagnostic_fee(self):
        out=self.form(history('Принтер Canon не печатает. Сколько стоит диагностика?', 'Диагностика от 500 рублей'),'kp')
        self.assertTrue(out['hard_block'])

    def test_accepted_repair_minimum_does_not_answer_separate_visit_fee_question(self):
        rows=history('Принтер Canon не печатает. Сколько стоит ремонт и выезд?', 'От 500 рублей такая услуга', 'Хорошо')
        out=self.form(rows,'kp')
        self.assertTrue(out['hard_block']);self.assertIn('условия партнёра не озвучены',out['reason'])
        self.assertTrue(next(r for r in out['results'] if r['key']=='price_consent')['done'])
        self.assertFalse(next(r for r in out['results'] if r['key']=='partner_visit_terms')['done'])
        rows += [dict(id='fee',direction='out',body='Выезд и диагностика бесплатны при выполнении работ. При отказе от работ стоимость составит 1000 рублей.'),dict(id='yes',direction='in',body='Да')]
        self.assertTrue(next(r for r in self.form(rows,'kp')['results'] if r['key']=='partner_visit_terms')['done'])

    def test_device_diagnostic_status_is_not_a_fee_question(self):
        rows=history('Принтер не печатает. Диагностика пишет ошибка. Сколько стоит ремонт?', 'От 500 рублей', 'Да')
        self.assertIsNone(prices.partner_visit_terms(rows,dict(direction='kp',partner='7')))
        rows=history('Нужен выезд. Принтер не печатает. Сколько стоит ремонт?', 'От 500 рублей', 'Да')
        self.assertIsNone(prices.partner_visit_terms(rows,dict(direction='kp',partner='7')))

    def test_real_budget_cap_and_declined_price_are_not_removed_by_valid_minimum(self):
        for reply in ('Не согласен', 'Бюджет максимум 800 рублей'):
            self.assertTrue(self.form(history('Повесить карниз', 'От 800 рублей',reply))['hard_block'])

    def test_compound_yes_is_price_consent_only_in_an_actual_price_answer(self):
        for reply in ('Да, устраивает', 'Да, подходит', 'Хорошо.\nВам завтра будет удобно подъехать?',
                      'Хорошо. Вам завтра удобно? Потому что я уже не знаю что с ним делать'):
            self.assertEqual(prices.consent(history('Повесить карниз','От 800 рублей',reply))['status'],'accepted')
        for reply in ('Да, но только 800', 'Да, а сколько точно?', 'Думаю да. Позже подтвержу',
                      'Хорошо. Вам завтра удобно? Не знаю что с ним делать, но бюджет только 800 рублей'):
            self.assertNotEqual(prices.consent(history('Повесить карниз','От 800 рублей',reply))['status'],'accepted')
        rows=history('Повесить карниз','От 800 рублей',None)+[dict(id='time',direction='out',body='В 12 удобно?'),dict(id='yes',direction='in',body='Да, подходит')]
        self.assertNotEqual(prices.consent(rows)['status'],'accepted')


if __name__=='__main__':
    unittest.main()
