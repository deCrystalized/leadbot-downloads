"""Client arrival-call wording from a manually checked dialogue, without PII."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from contact_facts import collect


class ArrivalCallbackTests(unittest.TestCase):
    def test_how_and_when_arriving_are_arrival_calls_not_departure_calls(self):
        for body in ('Позвоните как подъедете, я вас встречу. Домофон не работает',
                     'Наберите как приедете', 'Позвоните когда подъедете',
                     'Позвоните как будете подъезжать'):
            with self.subTest(body=body):
                facts = collect([dict(id='client', direction='in', body=body)])
                self.assertTrue(facts['call_before_visit'])
                self.assertEqual(facts['call_timing'], 'upon_arrival')
                self.assertEqual(facts['evidence']['call_before_visit']['message_id'], 'client')
                self.assertIn('Позвонить при подъезде по просьбе клиента.', facts['comment_lines'])
                self.assertNotIn('Позвонить перед выездом по просьбе клиента.', facts['comment_lines'])

    def test_negative_or_later_withdrawn_request_does_not_leave_a_call_flag(self):
        for messages in (
            [dict(id='client', direction='in', body='Звонить не нужно как подъедете')],
            [dict(id='first', direction='in', body='Позвоните как подъедете'),
             dict(id='last', direction='in', body='Не звоните, я буду у входа')],
        ):
            facts = collect(messages)
            self.assertFalse(facts['call_before_visit'])
            self.assertEqual(facts['call_timing'], 'not_stated')
            self.assertNotIn('call_before_visit', facts['evidence'])

    def test_staff_message_and_a_plain_arrival_question_are_not_client_call_requests(self):
        for direction, body in (('out', 'Позвоните как подъедете'),
                                ('note', 'Позвоните как подъедете'),
                                ('in', 'Когда подъедете?')):
            facts = collect([dict(id='message', direction=direction, body=body)])
            self.assertFalse(facts['call_before_visit'])
            self.assertEqual(facts['call_timing'], 'not_stated')


if __name__ == '__main__':
    unittest.main()
