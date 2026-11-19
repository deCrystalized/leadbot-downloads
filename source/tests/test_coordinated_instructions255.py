"""Retain a literal shared possession claim without sharing other predicates."""
import unittest

import qualification_state as qs


def row(text, **extra):
    return dict(id='literal', direction='in', sender_type='client', body=text, **extra)


class CoordinatedInstructions255Tests(unittest.TestCase):
    def test_comma_joins_the_same_supported_inventory_subjects(self):
        for text in ('Схема, все детали и крепёж есть.',
                     'Инструкция сборки, комплект крепежа есть.',
                     'Схема и все детали и крепёж есть.'):
            with self.subTest(text=text):
                result = qs.inspect([row(text)])['instructions']
                self.assertEqual(result['status'], 'answered')
                self.assertEqual(result['message_id'], 'literal')
                self.assertIn('есть', result['value'])
                self.assertIn('Схема' if text.startswith('Схема') else 'Инструкция', result['quote'])

    def test_parts_predicate_is_not_borrowed_across_a_different_clause(self):
        for text in ('Про схему не знаю, все детали и крепёж есть.',
                     'Схема, а все детали и крепёж есть.',
                     'Схема? Все детали и крепёж есть.',
                     'Схема или все детали и крепёж есть?'):
            with self.subTest(text=text):
                self.assertNotEqual(qs.inspect([row(text)])['instructions']['status'], 'answered')

    def test_future_past_conditional_and_foreign_claims_stay_unknown(self):
        for text in ('Схема, все детали и крепёж будут завтра.',
                     'Раньше схема, все детали и крепёж были.',
                     'Если схема, все детали и крепёж есть, получится собрать?',
                     'Сосед сказал: «Схема, все детали и крепёж есть».'):
            with self.subTest(text=text):
                self.assertNotEqual(qs.inspect([row(text)])['instructions']['status'], 'answered')

    def test_operator_and_system_speech_are_not_client_possession(self):
        for sender in ('operator', 'bot', 'assistant', 'system', 'avito'):
            message = row('Схема, все детали и крепёж есть.')
            message['sender_type'] = sender
            with self.subTest(sender=sender):
                self.assertNotEqual(qs.inspect([message])['instructions']['status'], 'answered')

    def test_distinct_scheme_and_materials_answers_remain_separate(self):
        out = qs.inspect([row('Схема есть. Деталей и крепежа нет.')])
        self.assertEqual(out['instructions']['status'], 'answered')
        self.assertIn('есть', out['instructions']['value'])
        self.assertEqual(out['materials']['status'], 'answered')
        self.assertEqual(out['materials']['value'], 'no')
        self.assertIn('нет', out['materials']['quote'])

    def test_new_order_does_not_inherit_the_old_inventory_group(self):
        old = row('Схема, все детали и крепёж есть.')
        new = row('Новая заявка: нужно собрать другой шкаф.')
        new['id'] = 'new'
        self.assertNotEqual(qs.inspect([old, new])['instructions']['status'], 'answered')


if __name__ == '__main__':
    unittest.main()
