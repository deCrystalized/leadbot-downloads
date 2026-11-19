"""Documented multi-part replacement price, preserving objection stages."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_prices as prices
from assistant_store import Store
from extension_assistant import Assistant


def rows(*turns):
    return [dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(turns)]


class PcReplacementScopeTests(unittest.TestCase):
    job = 'Сколько стоит поменять в ПК блок питания, процессор, мат плату, оперативную память на новое?'

    def test_several_different_parts_share_assembly_tariff(self):
        for text in (self.job, self.job.replace('поменять', 'заменить'),
                     'Замена в компьютере материнской платы и процессора. Цена?'):
            self.assertEqual(prices.select_tariff(text), ('pc_assembly', 3000, 'KP-L0543'))

    def test_one_part_stays_one_part(self):
        self.assertEqual(prices.select_tariff('Замена SSD в ПК'), ('pc_part', 1000, 'KP-L0544'))

    def test_inventory_and_self_repair_are_not_replacement_requests(self):
        for text in ('В ПК блок питания, процессор и мат плата',
                     'Я поменял в ПК процессор и материнскую плату, теперь нет изображения'):
            self.assertIsNone(prices.select_tariff(text))

    def test_independent_inventory_does_not_enlarge_one_replacement(self):
        self.assertEqual(prices.select_tariff('Замена SSD в ПК. Процессор, мат плата и ОЗУ есть.'),
                         ('pc_part', 1000, 'KP-L0544'))
        self.assertEqual(prices.select_tariff('Замена SSD в ПК, мат плата исправна'),
                         ('pc_part', 1000, 'KP-L0544'))

    def test_alternatives_and_negation_do_not_gain_assembly_price(self):
        for text in ('Поменять в ПК процессор или мат плату',
                     'Поменять в ПК процессор, мат плату не менять',
                     'Поменять в ПК только процессор, мат плата уже новая'):
            self.assertIsNone(prices.select_tariff(text))

    def test_independent_windows_service_prevents_one_bundle_price(self):
        self.assertIsNone(prices.select_tariff(self.job + ' И переустановить Windows.'))

    def test_first_objection_stage_keeps_general_answer(self):
        out = prices.answer(rows(('in', self.job)), dict(direction='kp', partner='723'), self.job)
        self.assertEqual(out['amounts'], [])
        self.assertIn('KP-L0474', out['rules'])

    def test_third_stage_names_one_documented_price(self):
        history = rows(('in', self.job), ('out', 'Точную стоимость смогу назвать после осмотра техники.'),
                       ('in', 'А примерно?'), ('out', 'Такая услуга от 500 рублей, без запчастей.'),
                       ('in', 'Назовите точную стоимость работы'))
        self.assertEqual(prices.price_turns(history), 3)
        out = prices.answer(history, dict(direction='kp', partner='723'), self.job)
        self.assertEqual(out['amounts'], [3000])
        self.assertIn('KP-L0543', out['rules'])
        self.assertNotIn('4000', out['reply'])

    def test_actual_preview_preserves_first_stage_without_write(self):
        history = rows(('in', self.job), ('out', 'Комплектующие уже есть?'), ('in', 'Да есть'))
        ctx = dict(convId='synthetic-replacement73', city='Сыктывкар', dir='kp', partner='723',
                   channel='avito', accountTitle='Иван КП', itemTitle='Ремонт ПК', messages=history)
        with tempfile.TemporaryDirectory() as tmp:
            out, code = Assistant(Store(tmp+'/db')).handle(dict(owner='offline', action='preview', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(out['auto_enabled'])
        self.assertEqual(out['action'], 'question')
        self.assertNotIn('3000', out['reply'])

    def test_actual_preview_uses_assembly_price_at_third_stage(self):
        history = rows(('in', self.job), ('out', 'Точную стоимость смогу назвать после осмотра техники.'),
                       ('in', 'А примерно?'), ('out', 'Такая услуга от 500 рублей, без запчастей.'),
                       ('in', 'Назовите точную стоимость работы'))
        ctx = dict(convId='synthetic-replacement73-third', city='Сыктывкар', dir='kp', partner='723',
                   channel='avito', accountTitle='Иван КП', itemTitle='Ремонт ПК', messages=history)
        with tempfile.TemporaryDirectory() as tmp:
            out, code = Assistant(Store(tmp+'/db')).handle(dict(owner='offline', action='preview', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(out['auto_enabled'])
        self.assertEqual(out['action'], 'question')
        self.assertIn('3000', out['reply'])
        self.assertIn('KP-L0543', out['rule_ids'])


if __name__ == '__main__':
    unittest.main()
