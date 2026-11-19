"""Keep a separate callout exchange outside the work-price stages."""
import unittest

import assistant_prices as prices
from test_interleaved_intake274 import CURTAIN, KNOWN, WARDROBE, row, staff


class MncSecondPrice275Tests(unittest.TestCase):
    def test_second_work_question_explains_free_visit_without_a_price(self):
        for work, amount, rule, price_phrase in (
                (CURTAIN, 800, 'DOC-L0525', 'за штуку'),
                (WARDROBE, 1500, 'DOC-L0326', 'от 1500 рублей')):
            with self.subTest(work=work):
                rows = [row('job', work + ' Сколько стоит работа?')]
                first = prices.answer(rows, KNOWN, work)
                self.assertEqual(first['amounts'], [])
                rows += [staff('first', first['reply']),
                         row('fee', 'Выезд отдельно оплачивается?'),
                         staff('fee-reply', 'Выезд в черте города бесплатный.'),
                         row('second', 'Назовите минимальную стоимость самой работы.')]
                self.assertEqual(prices.price_turns(rows), 2)
                second = prices.answer(rows, KNOWN, work)
                self.assertEqual(second['amounts'], [])
                self.assertNotEqual(second['reply'], first['reply'])
                self.assertIn('выезд в черте города бесплатный', second['reply'].lower())
                self.assertIn('после осмотра', second['reply'])
                self.assertIn('DOC-L0722', second['rules'])
                next_question = row('third', 'По работе всё-таки нужен ориентир. Сколько она стоит?')
                undelivered = rows + [staff('second-reply', second['reply'], 'failed'), next_question]
                self.assertEqual(prices.price_turns(undelivered), 2)
                self.assertEqual(prices.answer(undelivered, KNOWN, work)['amounts'], [])
                rows += [staff('second-reply', second['reply']), next_question]
                self.assertEqual(prices.price_turns(rows), 3)
                quote = prices.answer(rows, KNOWN, work)
                self.assertEqual(quote['amounts'], [amount])
                self.assertIn(price_phrase, quote['reply'])
                self.assertIn(rule, quote['rules'])

    def test_missing_city_does_not_offer_a_visit(self):
        rows = [row('job', CURTAIN + ' Сколько стоит?'),
                staff('first', 'Точную стоимость скажу после осмотра.'),
                row('repeat', 'Какая минимальная стоимость?')]
        self.assertEqual(prices.price_turns(rows), 2)
        response = prices.answer(rows, dict(KNOWN, city=''), CURTAIN)
        self.assertEqual(response['amounts'], [])
        self.assertNotIn('выезд', response['reply'].lower())

    def test_new_order_starts_a_separate_price_stage(self):
        rows = [row('job', CURTAIN + ' Сколько стоит?'),
                staff('first', 'Точную стоимость скажу после осмотра.'),
                row('repeat', 'Какая минимальная стоимость?'),
                staff('second', 'Выезд в черте города бесплатный, а стоимость работы смогу назвать после осмотра.'),
                row('new', 'Новый заказ: ' + WARDROBE + ' Сколько стоит сборка?')]
        self.assertEqual(prices.price_turns(rows), 1)
        response = prices.answer(rows, KNOWN, WARDROBE)
        self.assertEqual(response['amounts'], [])
        self.assertNotIn('DOC-L0722', response['rules'])

    def test_quoted_or_undelivered_new_order_cannot_reset_price_stage(self):
        prior = [row('job', CURTAIN + ' Сколько стоит?'),
                 staff('first', 'Точную стоимость скажу после осмотра.')]
        for notice in (row('notice', '«Новый заказ» — так называется кнопка.'),
                       row('notice', 'Новый заказ: нужен шкаф.', direction='system', sender_type='system'),
                       row('notice', 'Новый заказ: нужен шкаф.', sender_type='operator'),
                       row('notice', 'Новый заказ: нужен шкаф.', delivery_status='failed'),
                       row('notice', 'Новый заказ: нужен шкаф.', voice_transcript_status='processing')):
            with self.subTest(notice=notice):
                rows = prior + [notice, row('ask', 'А какая минимальная цена работы?')]
                self.assertEqual(prices.price_turns(rows), 2)
