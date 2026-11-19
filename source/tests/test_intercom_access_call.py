"""Retain the client's access-call request without inventing an advance call."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from contact_facts import collect


class IntercomAccessCallTests(unittest.TestCase):
    def test_written_access_request_retains_exact_evidence_and_arrival_comment(self):
        body = 'Домофона нет, поэтому потребуется набрать по номеру'
        facts = collect([dict(id='client', direction='in', body=body)])
        self.assertTrue(facts['call_before_visit'])
        self.assertEqual(facts['call_timing'], 'upon_arrival')
        self.assertFalse(facts['intercom_working'])
        self.assertEqual(facts['evidence']['call_before_visit'],
                         dict(message_id='client', quote=body))
        self.assertIn('Позвонить при подъезде по просьбе клиента.', facts['comment_lines'])
        self.assertIn('Условия звонка со слов клиента: «' + body + '».', facts['comment_lines'])
        self.assertNotIn('Позвонить перед выездом по просьбе клиента.', facts['comment_lines'])

    def test_same_clause_causal_variants(self):
        for body in ('Домофон не работает, так что позвоните мне.',
                     'Домофон отсутствует, поэтому нужно набрать по телефону.'):
            with self.subTest(body=body):
                facts = collect([dict(id='client', direction='in', body=body)])
                self.assertTrue(facts['call_before_visit'])
                self.assertEqual(facts['call_timing'], 'upon_arrival')
                self.assertFalse(facts['intercom_working'])

    def test_explicit_advance_timing_keeps_priority(self):
        for body in ('Домофона нет, поэтому позвоните перед выездом.',
                     'Домофон не работает, поэтому наберите заранее.',
                     'Домофона нет, поэтому позвоните за 15 минут.'):
            with self.subTest(body=body):
                facts = collect([dict(id='client', direction='in', body=body)])
                self.assertTrue(facts['call_before_visit'])
                self.assertEqual(facts['call_timing'], 'before_visit')

    def test_missing_intercom_alone_does_not_invent_request(self):
        for body in ('Домофона нет.', 'Домофон не работает, номер оставил.',
                     'Домофон работает, поэтому позвоните мне.',
                     'Раньше домофона не было. Поэтому позвоните мне.'):
            with self.subTest(body=body):
                facts = collect([dict(id='client', direction='in', body=body)])
                self.assertFalse(facts['call_before_visit'])

    def test_staff_and_notes_cannot_create_client_request(self):
        for direction in ('out', 'note'):
            with self.subTest(direction=direction):
                facts = collect([dict(id='staff', direction=direction,
                    body='Домофона нет, поэтому нужно набрать по номеру')])
                self.assertFalse(facts['call_before_visit'])

    def test_negated_or_withdrawn_request_clears_flag(self):
        for last in ('Не набирайте, я буду у входа.',
                     'Не нужно набирать, я открою.',
                     'Домофона нет, поэтому звонить не нужно.'):
            with self.subTest(last=last):
                facts = collect([dict(id='first', direction='in', body='Позвоните как подъедете'),
                                 dict(id='last', direction='in', body=last)])
                self.assertFalse(facts['call_before_visit'])
                self.assertEqual(facts['call_timing'], 'not_stated')

    def test_explicit_other_time_is_not_promoted_to_arrival(self):
        for body in ('Домофона нет, поэтому позвоните сейчас.',
                     'Домофона нет, поэтому позвоните после ремонта.'):
            with self.subTest(body=body):
                facts = collect([dict(id='client', direction='in', body=body)])
                self.assertFalse(facts['call_before_visit'])
                self.assertEqual(facts['call_timing'], 'not_stated')

    def test_long_message_keeps_call_evidence_instead_of_truncating_it_away(self):
        request = 'Домофона нет, поэтому потребуется набрать по номеру.'
        body = 'Дополнительные указания по адресу. ' * 30 + request
        facts = collect([dict(id='client', direction='in', body=body)])
        self.assertTrue(facts['call_before_visit'])
        self.assertEqual(facts['call_timing'], 'upon_arrival')
        quote = facts['evidence']['call_before_visit']['quote']
        self.assertLessEqual(len(quote), 500)
        self.assertIn(request, quote)
        self.assertIn(quote, body)


if __name__ == '__main__':
    unittest.main()
