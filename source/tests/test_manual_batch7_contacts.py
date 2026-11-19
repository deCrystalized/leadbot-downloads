"""Contact conditions read in complete expert histories and actual CRM cards."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import contact_facts


def history(*rows):
    return [dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)]


class ManualBatch7ContactTests(unittest.TestCase):
    def test_door_code_and_button_instruction_reach_crm_comment(self):
        f = contact_facts.collect(history(('in', 'Юных коммунаров 117, 3 подъезд, 1 этаж, 18 кв. Код на двери 25 (зажать обе кнопки)')))
        self.assertEqual(f['address']['intercom'], '25')
        self.assertIn('зажать обе кнопки', ' '.join(f['comment_lines']))
        self.assertEqual(f['address']['office'], '18')

    def test_serial_or_repair_price_is_not_a_door_code(self):
        for text in ('Ленина 5. Код модели 25', 'Ленина 5. Домофон 2500 рублей', 'Код на двери 25'):
            with self.subTest(text=text):
                f = contact_facts.collect(history(('in', text)))
                self.assertFalse(f['address'].get('intercom'))

    def test_minutes_before_visit_callback_keeps_exact_condition(self):
        f = contact_facts.collect(history(('in', 'Моторы 24, 2 этаж. Позвоните минут за 15, я подъеду')))
        self.assertTrue(f['call_before_visit'])
        self.assertIn('минут за 15', ' '.join(f['comment_lines']))
        cancelled = contact_facts.collect(history(('in', 'Ленина 5. Позвоните за 15 минут'), ('in', 'Не звоните перед выездом')))
        self.assertFalse(cancelled['call_before_visit'])

    def test_confirmed_street_name_is_not_guessed_before_client_yes(self):
        rows = [('in', 'Моторы 24, 2 этаж'), ('out', 'моторостроителей же правильно понимаю?')]
        self.assertEqual(contact_facts.collect(history(*rows))['address']['street'], 'Моторы')
        f = contact_facts.collect(history(*rows, ('in', 'Да')))
        self.assertEqual(f['address']['street'], 'моторостроителей')
        self.assertEqual(f['evidence']['address.street']['confirmation_question'], rows[-1][1])
        self.assertFalse(f['address_needs_confirmation'])
        for question in ('Квартира же правильно понимаю?', 'Домофон же правильно понимаю?', 'Все правильно понимаю?', 'Я правильно понимаю?', 'Это правильно понимаю?', 'Москва же правильно понимаю?', 'Руслан же правильно понимаю?'):
            self.assertEqual(contact_facts.collect(history(rows[0], ('out', question), ('in', 'Да')))['address']['street'], 'Моторы')
        explicit = contact_facts.collect(history(rows[0], ('out', 'Улица Чехова, правильно понимаю?'), ('in', 'Да')))
        self.assertEqual(explicit['address']['street'], 'Чехова')

    def test_numbered_street_in_snt_is_not_replaced_with_street_number_as_house(self):
        f = contact_facts.collect(history(('in', 'Снт расцвет ул 4 дом 92')))
        self.assertEqual(f['address']['street'], '4')
        self.assertEqual(f['address']['building'], '92')
        self.assertIn('расцвет', f['address']['settlement'].lower())

    def test_parenthetical_place_is_preserved_without_guessing_its_type(self):
        f = contact_facts.collect(history(('in', 'Гор Липецк ул Крайняя(Подгорное) д 1. Мы получается в Подгорное. А то в Липецке же тоже есть крайняя')))
        self.assertEqual(f['address']['building'], '1')
        self.assertIn('Подгорное', ' '.join(f['comment_lines']))

    def test_unlabelled_hyphen_unit_remains_a_confirmable_candidate(self):
        f = contact_facts.collect(history(('out', 'Напишите полный адрес — квартира, подъезд, этаж'), ('in', 'Моторы 24- 113\nПодъезд крайний, не знаю номер\n2 этаж')))
        self.assertEqual(f['address']['building'], '24')
        self.assertFalse(f['address'].get('office'))
        self.assertTrue(f['address_needs_confirmation'])
        self.assertEqual(f['address_ambiguities'][0]['value'], '113')
        self.assertIn('Подъезд крайний', ' '.join(f['comment_lines']))

    def test_two_adjacent_client_messages_identify_the_village(self):
        f = contact_facts.collect(history(('in', 'Мы живем в деревне рядом с городом'), ('in', 'Терновое')))
        self.assertEqual(f['address']['settlement'], 'Терновое')
        self.assertFalse(f['address'].get('building'))
        other = contact_facts.collect(history(('in', 'Мы живем в деревне рядом с городом'), ('out', 'Какая модель?'), ('in', 'Тритон')))
        self.assertNotEqual(other['address'].get('settlement'), 'Тритон')


if __name__ == '__main__':
    unittest.main()
