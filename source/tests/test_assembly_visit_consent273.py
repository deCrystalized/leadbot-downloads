"""Price acceptance and a preferred visit time can share one client turn."""

import unittest

from assistant_prices import consent, prior_quote_verified
from contact_facts import requested_visit
from qualification_state import voluntary_furniture_inventory
from test_assembly_minimum_consent271 import ACCEPT, CONTACTS, history


PREFERENCE = 'Мне удобно 9 ноября 2026 года в 16:00.'


class AssemblyVisitConsent273Tests(unittest.TestCase):
    def test_keeps_original_quote_and_client_ids_and_does_not_confirm_visit(self):
        rows = history(ACCEPT + CONTACTS + ' ' + PREFERENCE, work='В Чите нужно собрать один комод.')
        decision = consent(rows)
        self.assertEqual(decision, dict(status='accepted', amount=1500, message_id='quote',
                                        accepted_message_id='answer'))
        self.assertTrue(prior_quote_verified(rows, dict(direction='mnc', city='Чита'), decision))
        visit = requested_visit(rows)
        self.assertEqual((visit['message_id'], visit['date_iso'], visit['time']), ('answer', '2026-11-09', '16:00'))
        self.assertFalse(visit['appointment_confirmed'])
        self.assertFalse(visit['client_confirmed'])

    def test_allows_a_named_preference_before_contacts_including_year_abbreviation(self):
        preferred = ' Нам удобно 9 ноября 2026 г. в 16:00.'
        rows = history(ACCEPT + preferred + CONTACTS)
        self.assertEqual(consent(rows)['status'], 'accepted')
        self.assertEqual(requested_visit(rows)['date_iso'], '2026-11-09')

    def test_preference_alone_is_not_acceptance(self):
        self.assertEqual(consent(history(PREFERENCE + CONTACTS))['status'], 'pending')

    def test_refusal_and_invalid_quoted_or_conditional_preferences_do_not_accept(self):
        for suffix in (
                ' Мне удобно 9 ноября 2026 года в 16:00 только без доплаты.',
                ' Если мне удобно 9 ноября 2026 года в 16:00, цена подходит.',
                ' Мне удобно 9 ноября 2026 года в 16:00 или 10 ноября 2026 года в 16:00.',
                ' Мне удобно 31 ноября 2026 года в 16:00.',
                ' Сосед сказал, что ему удобно 9 ноября 2026 года в 16:00.',
                ' Мне удобно 9 ноября 2026 года в 16:00. Ещё нужно отремонтировать розетку.',
                ' Мне удобно 9 ноября 2026 года в 16:00. Бюджет не больше 1500 рублей.'):
            with self.subTest(suffix=suffix):
                self.assertNotEqual(consent(history(ACCEPT + CONTACTS + suffix))['status'], 'accepted')
        declined = 'Сборка от 1500 рублей не подходит. ' + PREFERENCE
        self.assertEqual(consent(history(declined))['status'], 'declined')

    def test_wrong_actor_or_unobserved_quote_still_cannot_accept(self):
        answer = ACCEPT + CONTACTS + ' ' + PREFERENCE
        self.assertEqual(consent(history(answer, sender_type='operator'))['status'], 'pending')
        self.assertEqual(consent(history(answer, quote_delivery='queued'))['status'], 'not_quoted')


class AssemblyInventoryAfterPause273Tests(unittest.TestCase):
    report = 'Проверил. Детали и крепёж на месте. Собрать один комод в квартире. Сколько будет стоить сборка?'

    def rows(self):
        return [
            dict(id='work', direction='in', sender_type='client', body='В Чите нужно собрать один комод.'),
            dict(id='question', direction='out', sender_type='operator',
                 delivery_status='delivered', body='Здравствуйте! Материалы есть у вас?'),
            dict(id='pause', direction='in', sender_type='client', body='Одну минуту, посмотрю коробку.'),
            dict(id='voice', direction='in', sender_type='client', voice_transcript_status='ready', body=self.report),
        ]

    def test_ready_literal_report_is_bound_to_prior_delivered_question_and_pause(self):
        value = voluntary_furniture_inventory(self.rows(), 3)
        self.assertEqual(value['value'], 'yes')
        self.assertEqual(value['availability_scope'], 'client_reported_furniture_parts_after_check')
        self.assertEqual((value['question_message_id'], value['check_intent_message_id'], value['message_id']),
                         ('question', 'pause', 'voice'))

    def test_pending_report_or_staff_cannot_supply_inventory(self):
        for change in (dict(voice_transcript_status='processing'), dict(sender_type='operator')):
            rows = self.rows()
            rows[-1].update(change)
            self.assertIsNone(voluntary_furniture_inventory(rows, 3))

    def test_missing_question_and_staff_interruption_break_the_anchor(self):
        rows = self.rows()
        rows[1]['delivery_status'] = 'queued'
        self.assertIsNone(voluntary_furniture_inventory(rows, 3))
        rows = self.rows()
        rows.insert(3, dict(id='staff', direction='out', sender_type='operator',
                            delivery_status='delivered', body='А теперь подскажите улицу.'))
        self.assertIsNone(voluntary_furniture_inventory(rows, 4))

    def test_uncertainty_another_work_and_a_quoted_report_do_not_supply_inventory(self):
        for body in (self.report + ' Но крепежа не хватает.',
                     self.report + ' Новый заказ: нужно установить мойку.',
                     'Сосед сказал: «' + self.report + '»'):
            rows = self.rows()
            rows[-1]['body'] = body
            self.assertIsNone(voluntary_furniture_inventory(rows, 3))
