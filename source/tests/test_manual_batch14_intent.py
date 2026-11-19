"""Paired controls from frozen501–540 and the verified primary documents.

Synthetic variants exercise the mechanism; historical targets stay immutable.
No live customer, CRM or final-holdout access.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog as catalog
import assistant_policy as policy
import assistant_prices as prices
import contact_facts
import assistant_qualifiers


def history(*rows):
    return [dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)]


class Batch14IntentTests(unittest.TestCase):
    def test_printer_error_indicator_is_not_a_household_bulb_job(self):
        for body in ('Принтер не берет бумагу, лампочка моргает три раза.',
                     'ПринтерCanonG1411, индикаторная лампа мигает.',
                     'Не печатает принтер. Мигает лампочка.'):
            out = catalog.choose(body, dict(direction='kp'))
            self.assertEqual([r['id'] for r in out['items']], ['printer'])
            self.assertEqual(out['status'], 'supported')

    def test_independent_bulb_work_survives_printer_symptom(self):
        for body in ('Принтер не берет бумагу, лампочка моргает. Ещё заменить лампочку в коридоре.',
                     'Починить принтер и заменить лампочку.',
                     'Принтер не печатает, заменить лампочку, она мигает.',
                     'Принтер не печатает. Лампочка в коридоре мигает.'):
            out = catalog.choose(body, dict(direction='kp'))
            self.assertEqual(out['status'], 'mixed')
            self.assertIn('bulb', [r['id'] for r in out['items']])

    def test_discussion_clock_cannot_become_a_visit(self):
        for body in ('Напишите часиков в 10, обсудим.', 'Напиште в 11 обсудим',
                     'Созвонимся к 12.', 'В 13 обсудим стоимость.'):
            m = history(('in', 'Собрать шкаф'), ('out', body), ('in', 'Хорошо'))
            self.assertIsNone(policy._accepted_staff_visit(m, include_later_questions=True))

    def test_visit_with_onsite_discussion_keeps_its_commitment(self):
        for body in ('Приеду к 12, обсудим на месте.', 'Буду у вас в 13, созвонимся перед выездом.',
                     'К 10 часам могу. По цене на месте обсудим с вами.'):
            self.assertIsNotNone(policy._accepted_staff_visit(history(('out', body), ('in', 'Хорошо'))))

    def test_explicit_later_contact_and_condition_pause_intake(self):
        for body in ('Когда буду планировать приехать, я напишу.',
                     'Напишу вам, если не получится собрать.',
                     'Я напишу чуть позже. Фото могу кинуть.',
                     'Мама проснётся, с ней договорюсь и вам обо всём напишу.'):
            self.assertTrue(policy._client_deferred([body]), body)

    def test_deferral_does_not_silence_a_current_question(self):
        for body in ('Напишу, если не получится собрать. А сколько стоит выезд?',
                     'Мама проснётся, договорюсь. Вы работаете завтра?',
                     'Когда буду планировать приехать, напишу. Сейчас цену подскажите.'):
            self.assertFalse(policy._client_deferred([body]), body)

    def test_confirmed_clog_requires_per_metre_quote(self):
        m = history(('in', 'Вода в унитазе медленно уходит, какая цена?'),
                    ('out', 'Засор у вас?'), ('in', 'Да'))
        facts = contact_facts.collect(m, dict(direction='mnc'))
        text = contact_facts.intent_text(m[0]['body'] + '\nДа', facts)
        self.assertEqual([r['id'] for r in catalog.choose(text, dict(direction='mnc'))['items']], ['drain'])
        for city, amount in [('Оренбург', 500), ('Москва', 800)]:
            out = prices.mandatory(m, dict(direction='mnc', city=city), text)
            self.assertEqual(out['amounts'], [amount])
            self.assertRegex(out['reply'], 'погонный метр')
        self.assertEqual(facts['confirmed_clog']['question_message_id'], '1')
        self.assertEqual(facts['confirmed_clog']['message_id'], '2')

    def test_staff_clog_guess_is_not_a_client_fact(self):
        for question, answer in [('Засор у вас?', 'Не знаю'), ('Засор или заменить унитаз?', 'Да'),
                                 ('Это не засор?', 'Да'), ('Засор у вас?', 'Нет')]:
            facts = contact_facts.collect(history(('out', question), ('in', answer)))
            self.assertFalse(facts.get('confirmed_clog'))
        m = history(('out', 'Засор у вас?'), ('in', 'Да'))
        m[0]['out_pending'] = True
        self.assertFalse(contact_facts.collect(m).get('confirmed_clog'))

    def test_later_correction_withdraws_confirmed_clog(self):
        m = history(('out', 'Засор у вас?'), ('in', 'Да'),
                    ('in', 'Нет, засора нет, нужна замена кнопки.'))
        self.assertFalse(contact_facts.collect(m).get('confirmed_clog'))

    def test_clog_amount_without_unit_does_not_satisfy_mandatory_quote(self):
        for quote in ('Устранение засора — 500 рублей.',
                      '500 рублей за выезд.', 'Windows — 500 рублей.'):
            m = history(('in', 'Устранить засор'), ('out', quote), ('in', 'Хорошо'))
            self.assertIsNotNone(prices.mandatory(m, dict(direction='mnc', city='Оренбург'), 'Устранить засор'))
        m = history(('in', 'Устранить засор'), ('out', 'Устранение засора — 500 рублей за погонный метр.'), ('in', 'Хорошо'))
        self.assertIsNone(prices.mandatory(m, dict(direction='mnc', city='Оренбург'), 'Устранить засор'))

    def test_ambiguous_decimal_access_is_retained_without_guessing(self):
        f = contact_facts.collect(history(('in', 'Ленина 8, кв20, 3.5 этаж')))
        self.assertFalse(f['address'].get('floor'))
        self.assertFalse(f['address'].get('entrance'))
        self.assertTrue(any('3.5 этаж' in r['quote'] for r in f['address_notes']))
        explicit = contact_facts.collect(history(('in', 'Ленина 8, кв20, 3 подъезд, 5 этаж')))
        self.assertEqual(explicit['address']['floor'], '5')
        self.assertEqual(explicit['address']['entrance'], '3')

    def test_ordinary_mnc_first_price_question_does_not_require_a_minimum(self):
        m = history(('in', 'Сколько стоит собрать шкаф?'), ('out', 'В наличии?'), ('in', 'Да'))
        out = prices.answer(m, dict(direction='mnc', city='Оренбург'), m[0]['body'])
        self.assertEqual(out['amounts'], [])
        self.assertIn('DOC-L0713', out['rules'])

    def test_unlisted_intercom_job_is_not_lost_in_an_accepted_tv_bundle(self):
        out = catalog.choose('Установить два телевизора на кронштейны, установить видео домофон.', dict(direction='mnc'))
        self.assertNotEqual(out['status'], 'supported')
        self.assertIn('video-intercom', [r['id'] for r in out['items']])
        self.assertIn('tv-mount', [r['id'] for r in out['items']])
        self.assertIn('DOC-L0453', out['rules'])

    def test_intercom_as_access_information_is_not_an_additional_service(self):
        out = catalog.choose('Повесить телевизор на кронштейн. Видеодомофон уже установлен, код38.', dict(direction='mnc'))
        self.assertNotIn('video-intercom', [r['id'] for r in out['items']])
        self.assertEqual(out['status'], 'supported')

    def test_company_payment_qualification_precedes_repeated_assembly_questions(self):
        m = history(('in', 'Собрать10шкафов, г.Оренбург, Ленина8.'), ('out', 'Организация?'), ('in', 'Да'))
        k = dict(direction='mnc', city='Оренбург', partner='7', channel='avito')
        f = contact_facts.collect(m, k)
        q = assistant_qualifiers.next_question(m, k, f)
        self.assertEqual(q['kind'], 'business_payment')
        self.assertRegex(q['question'], 'сч[её]ту')
        self.assertRegex(q['question'], 'на месте')
        self.assertEqual(f['business_customer']['question_message_id'], '1')

    def test_quantity_and_unanswered_company_question_do_not_prove_a_company(self):
        for rows in [(('in', 'Собрать10шкафов'),),
                     (('out', 'Организация?'), ('in', 'Нет')),
                     (('out', 'Организация или квартира?'), ('in', 'Да'))]:
            self.assertFalse(contact_facts.collect(history(*rows)).get('business_customer'))


if __name__ == '__main__':
    unittest.main()
