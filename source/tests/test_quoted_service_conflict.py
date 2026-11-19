"""A numerically valid price cannot certify a quote for another service."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_prices as prices
from assistant_store import Store
from extension_assistant import Assistant


def history(quote='Замена подшипников от 500 рублей, по запчастям на месте сориентирую'):
    rows = [('in', 'Сколько стоит заменить подсветку телевизора DEXP?'),
            ('out', 'Точную стоимость смогу назвать после осмотра техники.'),
            ('in', 'А хоть примерно сколько стоит замена подсветки?'),
            ('out', quote), ('in', 'Да')]
    return [dict(id=str(i), direction=d, body=t, sender_type='client' if d == 'in' else 'operator')
            for i, (d, t) in enumerate(rows)]


class QuotedServiceConflictTests(unittest.TestCase):
    def form(self, rows, action='checklist'):
        ctx = dict(convId='synthetic-service-conflict', city='Воткинск', dir='kp',
                   channel='avito', partner='7', accountTitle='Пётр КП',
                   itemTitle='Ремонт телевизоров', origin='В89', messages=rows)
        with tempfile.TemporaryDirectory() as p:
            out, code = Assistant(Store(p + '/db')).handle(dict(owner='offline-form', action=action, ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(out['auto_enabled'])
        return out

    def test_second_stage_amount_does_not_certify_bearing_quote_for_tv(self):
        rows = history()
        self.assertFalse(prices.prior_quote_verified(rows, dict(direction='kp'), prices.consent(rows)))
        self.assertFalse(prices.prior_quote_verified(rows, dict(direction='kp'), prices.consent(rows), manual=True))

    def test_normal_form_names_both_services_and_retains_quote_evidence(self):
        out = self.form(history())
        self.assertTrue(out['hard_block'])
        self.assertRegex(out['operator_review'], 'подшипник')
        self.assertRegex(out['operator_review'], 'телевизор')
        self.assertEqual(out['price_service_conflict']['message_id'], '3')
        self.assertEqual(out['price_service_conflict']['quote'], history()[3]['body'])
        self.assertEqual(out['geography']['crm_city'], 'Ижевск')
        self.assertEqual(out['geography']['settlement'], 'Воткинск')
        self.assertTrue(out['geography']['far_trip'])
        self.assertFalse(next(r for r in out['results'] if r['key'] == 'price_consent')['done'])

    def test_assistant_hands_conflicting_commitment_to_operator_without_reply(self):
        out = self.form(history(), action='preview')
        self.assertEqual(out['action'], 'handoff')
        self.assertRegex(out['reason'], 'подшипник')
        self.assertEqual(out['reply'], '')

    def test_relevant_general_minimum_is_still_valid_at_second_stage(self):
        rows = history('Такая услуга от 500 рублей, без учёта запчастей')
        self.assertTrue(prices.prior_quote_verified(rows, dict(direction='kp'), prices.consent(rows)))
        self.assertFalse(self.form(rows)['hard_block'])

    def test_explicit_relevant_replacement_quote_supersedes_old_wrong_quote(self):
        rows = history() + [dict(id='5', direction='out', body='Такая услуга от 500 рублей, без учёта запчастей'),
                            dict(id='6', direction='in', body='Да')]
        self.assertEqual(prices.prior_quote_verified(rows, dict(direction='kp'), prices.consent(rows)), True)
        self.assertFalse(self.form(rows)['hard_block'])

    def test_comparison_and_mixed_client_scope_are_not_claimed_as_proven_conflicts(self):
        for rows in [history('Это не замена подшипников. Такая услуга от 500 рублей, без учёта запчастей'),
                     history('Такая услуга от 500 рублей, без учёта запчастей')]:
            self.assertFalse(self.form(rows).get('price_service_conflict'))
        rows = history()
        rows[0]['body'] += ' Ещё нужна замена подшипников стиральной машины.'
        self.assertFalse(self.form(rows).get('price_service_conflict'))


if __name__ == '__main__':
    unittest.main()
