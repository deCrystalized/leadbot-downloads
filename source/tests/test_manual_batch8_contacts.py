"""Preserve a client's access condition without claiming a completed call."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import contact_facts


def msg(body, direction='in'):
    return dict(id=direction + body[:40], direction=direction, body=body)


class ManualBatch8ContactTests(unittest.TestCase):
    def test_access_request_and_explicit_staff_callback_commitment_are_preserved(self):
        rows = [msg('Ленина 5, квартира 32'), msg('За мин 10, чтобы открыть вам'),
                msg('Наберу вам за 10 минут', 'out')]
        facts = contact_facts.collect(rows)
        self.assertTrue(facts['call_before_visit'])
        self.assertEqual(facts['address']['building'], '5')
        self.assertTrue(any('10 минут' in text for text in facts['comment_lines']))
        self.assertFalse(facts.get('call_completed'))
        self.assertEqual(facts['evidence']['call_before_visit']['commitment_message_id'], rows[-1]['id'])

    def test_generic_callback_is_not_a_pre_visit_request_and_explicit_no_call_wins(self):
        rows = [msg('Как дела?'), msg('Наберу вам за 10 минут', 'out')]
        self.assertFalse(contact_facts.collect(rows)['call_before_visit'])

    def test_signed_reversed_intercom_and_relative_callback_are_preserved(self):
        rows = [msg('Напишите полный адрес, квартиру, подъезд и домофон', 'out'),
                msg('9-20-127\n8 подъезд\n5 этаж\n127 домофон'),
                msg('За час желательно позвоните, вдруг отлучусь от дома')]
        facts = contact_facts.collect(rows, dict(city='Нефтеюганск'))
        self.assertEqual(facts['address']['intercom'], '127')
        self.assertTrue(facts['call_before_visit'])
        self.assertIn('Домофон: 127.', facts['comment_lines'])
        self.assertFalse(facts['address_needs_confirmation'])

    def test_access_written_in_words_is_kept_with_its_landmarks(self):
        rows = [msg('Советская, 83, квартира 30. Подъезд первый, нумерация подъездов наоборот. Этаж девятый, лифт работает, домофон тоже.')]
        facts = contact_facts.collect(rows)
        self.assertEqual(facts['address']['entrance'], '1')
        self.assertEqual(facts['address']['floor'], '9')
        self.assertTrue(any('нумерация подъездов наоборот' in line and 'лифт работает' in line for line in facts['comment_lines']))

    def test_dismantling_quantity_is_not_a_street_and_callback_minutes_are_kept(self):
        facts = contact_facts.collect([msg('Снять 4 двойные розетки и люстру в саманном доме. Только демонтаж.')])
        self.assertFalse(facts['address'].get('building'))
        self.assertFalse(facts['address'].get('street'))
        facts = contact_facts.collect([msg('Иркутский 154, позвоните на номер, я там не живу, поэтому лучше позвонить минут за 40, я подъеду')])
        self.assertTrue(facts['call_before_visit'])
        rows = [msg('За мин 10, чтобы открыть вам'), msg('Наберу вам за 10 минут', 'out'), msg('Не звоните')]
        self.assertFalse(contact_facts.collect(rows)['call_before_visit'])


if __name__ == '__main__':
    unittest.main()
