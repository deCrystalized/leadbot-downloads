"""Client facts and service scope controls frozen before candidate63 outputs."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog as catalog
import assistant_prices as prices
import contact_facts


def history(*rows):
    return [dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)]


class CrmContext63Tests(unittest.TestCase):
    def test_adjustment_of_an_assembled_kitchen_is_furniture_repair(self):
        for text in ('Кухонный гарнитур собран, не получается отрегулировать фасады верхних и нижних шкафов.',
                     'Кухню уже собрали. Нужно отрегулировать фасады.',
                     'Кухня уже собрана, надо отрегулировать дверцы.',
                     'Кухня уже собрана. Собирать не надо, отрегулировать фасады.'):
            service = catalog.choose(text, dict(direction='mnc'))
            self.assertEqual(service['status'], 'supported', text)
            self.assertEqual([r['id'] for r in service['items']], ['furniture'], text)
            self.assertTrue(service['items'][0]['repair_only'])
            self.assertNotIn('instructions', service['items'][0]['questions'])
            self.assertNotIn('countertop_material', service['items'][0]['questions'])

    def test_repair_minimum_is_not_new_kitchen_assembly_minimum(self):
        text = 'Кухонный гарнитур собран, отрегулировать фасады. Сколько стоит?'
        m = history(('in', text), ('out', 'Цена после осмотра.'), ('in', 'Хотя бы примерно?'),
                    ('out', 'Точно скажу на месте после осмотра.'), ('in', 'Ну сколько стоит?'),
                    ('out', 'По объёму работы на месте.'), ('in', 'Цена?'))
        out = prices.answer(m, dict(direction='mnc', partner='7', city='Оренбург'), text)
        self.assertEqual(out['amounts'], [1500])
        self.assertIn(prices.FURNITURE_REPAIR_MIN_RULE, out['rules'])

    def test_new_kitchen_assembly_keeps_its_instructions_and_category(self):
        for text in ('Собрать новую кухню и после сборки отрегулировать фасады.',
                     'Кухня ещё не собрана. Нужно собрать гарнитур.'):
            service = catalog.choose(text, dict(direction='mnc'))
            self.assertIn('kitchen', [r['id'] for r in service['items']])
            self.assertIn('instructions', service['items'][0]['questions'])
            self.assertFalse(service['items'][0].get('repair_only'))

    def test_other_kitchen_room_work_is_not_cabinet_repair(self):
        service = catalog.choose('На кухне починить розетку.', dict(direction='mnc'))
        self.assertFalse(any(r['family'] == 'furniture' for r in service['items']))

    def test_later_time_agreement_does_not_replace_withdrawn_price_acceptance(self):
        m = history(('in', 'Прикрутить излив смесителя, сколько стоит?'), ('out', 'От800рублей.'),
                    ('in', 'Хорошо, подумаю.'), ('out', 'Хорошо, если что — я на связи.'),
                    ('in', 'Сегодня можете посмотреть?'), ('out', 'Через час-полтора удобно вам будет?'),
                    ('in', 'Да, Ленина8 кв20.'))
        self.assertNotEqual(prices.consent(m)['status'], 'accepted')

    def test_explicit_price_acceptance_after_thinking_is_retained(self):
        for quoted, accepted in (('От800рублей.', 'Да, от800рублей меня устраивает.'),
                                 ('От 800 рублей.', 'Да, от 800 рублей меня устраивает.')):
            m = history(('in', 'Повесить картину, сколько стоит?'), ('out', quoted),
                        ('in', 'Подумаю'), ('in', accepted))
            out = prices.consent(m)
            self.assertEqual(out['status'], 'accepted')
            self.assertEqual(out['accepted_message_id'], '3')
            if ' ' in quoted:
                self.assertTrue(prices.prior_quote_verified(m, dict(direction='mnc', city='Оренбург'), out, manual=True))

    def test_named_agreement_cannot_change_amount_or_turn_minimum_into_a_cap(self):
        for answer in ('Да,800рублей меня устраивает.', 'Да, от900рублей меня устраивает.',
                       'Да, максимум800рублей меня устраивает.', 'От800рублей подходит, но без доплат.'):
            m = history(('out', 'От800рублей.'), ('in', 'Подумаю'), ('in', answer))
            self.assertNotEqual(prices.consent(m)['status'], 'accepted', answer)
        m = history(('out', 'От800рублей.'), ('out', 'От1500рублей.'), ('in', 'От800рублей меня устраивает.'))
        self.assertNotEqual(prices.consent(m)['status'], 'accepted')

    def test_explicit_no_intercom_is_not_a_missing_or_positive_client_fact(self):
        facts = contact_facts.collect(history(('in', 'Ленина8, кв20. Домофона нет.')))
        self.assertIs(facts['intercom_present'], False)
        self.assertFalse(facts.get('intercom_working'))
        self.assertRegex('\n'.join(facts['comment_lines']), 'нет.*домофон|[Дд]омофон.*(?:нет|отсутствует)')


if __name__ == '__main__':
    unittest.main()
