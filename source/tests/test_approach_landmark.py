"""Keep a client's approach cue without inventing the destination locality."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from contact_facts import collect


def msg(body, mid='client', direction='in', **extra):
    return dict(id=mid, direction=direction, body=body, **extra)


class ApproachLandmarkTests(unittest.TestCase):
    def test_approach_landmark_is_quoted_and_never_becomes_actual_settlement(self):
        for rows in (
            [msg('Ленина 5'), msg('Не доезжая до Норского', 'approach')],
            [msg('Не доезжая до Норского', 'approach'), msg('Ленина 5')],
        ):
            facts = collect(rows)
            self.assertEqual(facts['address']['street'], 'Ленина')
            self.assertEqual(facts['address']['building'], '5')
            self.assertFalse(facts['address'].get('settlement'))
            self.assertTrue(any(row['message_id'] == 'approach' and row['quote'] == 'Не доезжая до Норского'
                                for row in facts['address_notes']))
            self.assertTrue(any('Не доезжая до Норского' in line for line in facts['comment_lines']))

    def test_private_sector_with_address_is_private_house_not_missing_apartment(self):
        facts = collect([msg('2-я Тутаевская, 20Б частный сектор')])
        self.assertEqual(facts['address']['office'], 'ЧД')
        self.assertFalse(facts['address'].get('floor'))
        self.assertFalse(facts['address_needs_confirmation'])
        self.assertNotEqual(collect([msg('Ленина 5. Частный мастер нужен')])['address'].get('office'), 'ЧД')

    def test_compound_address_keeps_approach_as_a_landmark(self):
        for body in ('Не доезжая до Норского, улица Ленина 5',
                     'Улица Ленина 5, не доезжая до Норского'):
            with self.subTest(body=body):
                facts = collect([msg(body)])
                self.assertEqual(facts['address']['building'], '5')
                self.assertRegex(facts['address']['street'].lower(), r'^(?:улица\s+)?ленина$')
                self.assertFalse(facts['address'].get('settlement'))
                self.assertTrue(any(body in line for line in facts['comment_lines']))

    def test_old_landmark_does_not_survive_an_explicit_destination_change(self):
        facts = collect([msg('Ленина 5'), msg('Не доезжая до Норского', 'old'),
                         msg('Правильный адрес улица Советская 7', 'correction')])
        self.assertEqual(facts['address']['building'], '7')
        self.assertFalse(any('Норского' in line for line in facts['comment_lines']))

    def test_service_messages_do_not_supply_client_approach_landmarks(self):
        for direction, sender in (('out', None), ('note', None), ('in', 'bot'), ('in', 'system'),
                                  ('in', 'operator'), ('in', 'assistant')):
            facts = collect([msg('Ленина 5'), msg('Не доезжая до Норского', 'service',
                                                direction=direction, sender_type=sender)])
            self.assertFalse(any('Норского' in line for line in facts['comment_lines']))


if __name__ == '__main__':
    unittest.main()
