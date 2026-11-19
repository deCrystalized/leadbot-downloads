"""Direct owner clarification; service scope and client consent stay separate."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog as catalog
import assistant_prices as prices
import assistant_policy as policy
from assistant_store import Store
from extension_assistant import Assistant

OWNER_RULE = 'OWNER-FURNITURE-REPAIR-MIN-20261018'


def rows(*pairs):
    return [dict(id=str(i), direction=d, body=b) for i, (d, b) in enumerate(pairs)]


class FurnitureOwnerAmendmentTests(unittest.TestCase):
    known = dict(direction='mnc', city='Оренбург', partner='7')

    def form(self, messages):
        ctx = dict(convId='synthetic-owner41', city='Оренбург', dir='mnc',
                   partner='7', channel='avito', origin='С79.2', accountTitle='Григорий МНЧ',
                   itemTitle='Мастер на час', messages=messages)
        with tempfile.TemporaryDirectory() as p:
            result, code = Assistant(Store(p+'/db')).handle(dict(owner='offline-owner41', action='checklist', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(result['auto_enabled'])
        return result

    def quote(self, job, price='Работа от 1500 рублей, точнее после осмотра', ack='Хорошо'):
        return rows(('in', job), ('out', 'Здравствуйте!'), ('in', 'Цена?'),
                    ('out', price), ('in', ack))

    def test_explicit_owner_source_is_available_to_extension(self):
        sources = policy.retrieve('ремонт мебели', refs=[OWNER_RULE], applied_only=True)
        self.assertTrue(any(s['id'] == OWNER_RULE for s in sources))

    def test_third_price_answer_uses_owner_repair_minimum(self):
        for job in ('Починить дверь шкафа', 'Отремонтировать кровать',
                    'Двери шкафа отвалились, отверстия креплений разбиты, надо заделать и прикрутить'):
            messages = rows(('in', job+' сколько стоит?'), ('out', 'Стоимость после осмотра'),
                            ('in', 'А примерно?'), ('out', 'Цена зависит от объёма'),
                            ('in', 'Скажите хотя бы от скольки?'))
            out = prices.answer(messages, self.known, job)
            self.assertEqual(out['amounts'], [1500], job)
            self.assertIn(OWNER_RULE, out['rules'])
            self.assertIn('от 1500', out['reply'])

    def test_accepted_human_minimum_is_shared_by_bot_and_form(self):
        for job in ('Починить дверь шкафа', 'Отремонтировать кровать', 'Собрать комод'):
            messages = self.quote(job)
            state = prices.consent(messages)
            self.assertEqual(state['status'], 'accepted')
            self.assertTrue(prices.prior_quote_verified(messages, self.known, state))
            out = self.form(messages)
            self.assertFalse(out['hard_block'], job)
            if 'Собрать' not in job:
                self.assertIn(OWNER_RULE, out['rule_ids'])

    def test_timing_acknowledgement_cannot_accept_minimum(self):
        messages = self.quote('Починить дверь шкафа')[:-1]
        messages += [dict(id='time', direction='out', body='Завтра в 10 удобно?'),
                     dict(id='time-ack', direction='in', body='Хорошо')]
        self.assertEqual(prices.consent(messages)['status'], 'pending')
        self.assertTrue(self.form(messages)['hard_block'])

    def test_wrong_units_fixed_totals_bundles_and_special_jobs_stay_blocked(self):
        for job, quote in [
            ('Починить дверь шкафа','Ремонт 1500 рублей'),
            ('Починить дверь шкафа','От 1500 рублей за всё, окончательная стоимость'),
            ('Починить дверь шкафа','От 1500 рублей за час'),
            ('Починить дверь шкафа','От 1500 рублей, сборка 2000 рублей'),
            ('Починить дверь шкафа и установить мойку','От 1500 рублей'),
            ('Отреставрировать кровать','От 1500 рублей'),
            ('Заменить пружинный блок дивана','От 1500 рублей')]:
            with self.subTest(job=job, quote=quote):
                self.assertFalse(prices.prior_quote_verified(self.quote(job,quote), self.known,
                                                            prices.consent(self.quote(job,quote))))
                self.assertTrue(self.form(self.quote(job,quote))['hard_block'])

    def test_own_first_answer_does_not_skip_price_order(self):
        for job in ('Починить дверь шкафа', 'Собрать комод'):
            messages = rows(('in', job+' сколько стоит?'))
            out = prices.answer(messages,self.known,job)
            self.assertEqual(out['amounts'], [])
            self.assertNotIn('1500', out['reply'])

    def test_broken_fasteners_are_repair_without_assembly_instructions(self):
        service = catalog.choose('Двери шкафа отвалились, отверстия креплений разбиты, заделать и прикрутить',self.known)
        self.assertEqual(service['items'][0]['questions'], ['furniture_problem'])
        self.assertTrue(service['items'][0]['repair_only'])


if __name__ == '__main__':
    unittest.main()
