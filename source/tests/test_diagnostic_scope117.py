"""Owner clarification: partner callout/diagnosis fee is exclusive to KP."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'leadbot/brain'))
import assistant_prices as prices
from assistant_store import Store
from extension_assistant import Assistant


def rows(*turns):
    return [dict(id=str(i), direction=d, body=b, sender_type='client' if d == 'in' else 'operator')
            for i, (d, b) in enumerate(turns)]


class DiagnosticScope117Tests(unittest.TestCase):
    def call(self, history, direction, partner, action='checklist'):
        titles = dict(kp='Ремонт принтеров', bt='Ремонт холодильников', mnc='Услуги электрика')
        ctx = dict(convId='synthetic-diagnostic-scope117', messages=history, city='Оренбург',
                   dir=direction, partner=partner, channel='avito', origin='С1',
                   accountTitle='Учебный мастер', itemTitle=titles[direction])
        with tempfile.TemporaryDirectory() as tmp:
            out, code = Assistant(Store(tmp + '/db')).handle(dict(owner='offline-test', action=action,
                                                               wording_mode='reviewed', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(out['auto_enabled'])
        return out

    def test_same_question_changes_only_by_direction_not_partner_number(self):
        history = rows(('in', 'Сколько стоит выезд и диагностика?'))
        for partner in ('7', '723', '748', '340'):
            for direction in ('kp', 'bt', 'mnc'):
                with self.subTest(direction=direction, partner=partner):
                    out = prices.answer(history, dict(direction=direction, partner=partner, city='Оренбург'), '')
                    # Owner27Oct changes only the appliance amounts/categories.
                    self.assertEqual(out['amounts'], {'kp': [1000], 'bt': [800], 'mnc': []}[direction])
                    self.assertIn({'mnc':prices.MNC_FREE_CALLOUT_RULE,'bt':prices.BT_800_RULE,
                                   'kp':prices.KP_PARTNER_DIAGNOSTIC_RULE}[direction],out['rules'])
                    if direction != 'kp':
                        self.assertNotIn('1000', out['reply'])

    def test_standalone_printer_diagnostic_uses_latest_owner_minimum(self):
        history = rows(('in', 'Нужна только диагностика принтера, без ремонта. Сколько стоит диагностика?'))
        out = prices.answer(history, dict(direction='kp', partner='7', city='Оренбург'), history[0]['body'])
        self.assertEqual(out['amounts'], [500])
        self.assertIn('от 500', out['reply'])
        self.assertNotIn('1000', out['reply'])

    def test_wrong_thousand_quote_never_becomes_valid_bt_or_mnc_price(self):
        history = rows(('in', 'Сколько стоит диагностика?'),
                       ('out', 'Выезд и диагностика — 1000 рублей. При выполнении работ они бесплатны.'),
                       ('in', 'Да, устраивает'))
        for direction in ('bt', 'mnc'):
            known = dict(direction=direction, partner='723')
            self.assertFalse(prices.prior_quote_verified(history, known, prices.consent(history)))
            self.assertFalse(prices.prior_quote_verified(history, known, prices.consent(history), manual=True))
            self.assertIsNone(prices.partner_visit_terms(history, known))
            partial = history[:1] + rows(('out', 'Выезд и диагностика бесплатные, но при отказе1000р'),
                                        ('in', 'Холодильник не включается'))
            self.assertIsNone(prices._partner_diagnostic_clarification(partial, known))

    def test_normal_form_does_not_require_kp_terms_for_bt_or_mnc(self):
        for direction, job in [('bt', 'Холодильник не морозит'), ('mnc', 'Нужно заменить розетку')]:
            history = rows(('in', job + '. Сколько стоит выезд?'),
                           ('out', 'Выезд в черте города бесплатный.'), ('in', 'Хорошо'))
            for partner in ('7', '723', '748', '340'):
                with self.subTest(direction=direction, partner=partner):
                    out = self.call(history, direction, partner)
                    self.assertNotIn('partner_visit_terms', [r['key'] for r in out['results']])
                    self.assertNotIn('1000 рублей при отказе', out.get('operator_review', ''))

    def test_preview_and_normal_form_share_scope_and_verify_bt_diagnosis(self):
        history = rows(('in', 'Холодильник не морозит. Сколько стоит диагностика?'))
        out = self.call(history, 'bt', '7', 'preview')
        self.assertIn('800 рублей', out['reply'])
        self.assertNotIn('1000', out['reply'])
        history += rows(('out', 'Первичная диагностика без разбора техники — 800 рублей. '
                         'При продолжении работ диагностика бесплатная.'), ('in', 'Да, устраивает'))
        out = self.call(history, 'bt', '723')
        self.assertTrue(next(r for r in out['results'] if r['key'] == 'price_consent')['done'])

    def test_price_scope_does_not_bypass_white_bt_direction_restriction(self):
        history = rows(('in', 'Холодильник не морозит. Сколько стоит диагностика?'))
        out = self.call(history, 'bt', '723', 'preview')
        self.assertEqual(out['action'], 'handoff')
        self.assertFalse(out['reply'])
        self.assertIn('TGAVITO-16610', out['rule_ids'])

    def test_nonpartner_kp_and_unrelated_work_tariff_remain_separate(self):
        history = rows(('in', 'Сколько стоит диагностика?'))
        self.assertEqual(prices.answer(history, dict(direction='kp', partner=''), '')['amounts'], [500])
        self.assertEqual(prices.select_tariff('Подключение принтера')[1], 1000)
        for path, field in [('policy_registry.json', 'sources'), ('reviewed_catalog.json', 'owner_amendments')]:
            data = json.loads((Path(prices.__file__).parent / path).read_text())
            rule = next(x for x in data[field] if x['id'] == prices.KP_PARTNER_DIAGNOSTIC_RULE)
            self.assertTrue(rule['active_primary'])
            self.assertIn('только к КП', rule['text'])


if __name__ == '__main__':
    unittest.main()
