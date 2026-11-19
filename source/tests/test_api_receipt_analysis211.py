"""Accounting evidence, not output quality or a provider-cache simulation."""
import copy
import unittest

from analyze_api_receipts import analyze
from api_costs import cost


def receipt(**changes):
    row = dict(response_id='response1', series='s', role='research', model='gpt-6.1-sol',
        tier='default', usage=dict(input_tokens=2000, output_tokens=100,
            input_tokens_details=dict(cached_tokens=500, cache_write_tokens=1000,
                cache_write_tokens_details=dict(ttl_30m_tokens=600, ttl_12h_tokens=400)),
            output_tokens_details=dict(reasoning_tokens=80)))
    row.update(changes)
    row['usd'] = str(cost(row['model'], row['usage'])) if row['usage'] is not None else None
    return row


class ReceiptAnalysisTests(unittest.TestCase):
    def test_cost_components_sum_and_reasoning_is_not_charged_twice(self):
        result = analyze([receipt()])
        group = result['groups'][0]
        self.assertEqual(group['known_usd'], group['input_usd']+group['output_usd'])
        self.assertEqual(str(group['known_usd']), '0.00555')
        self.assertEqual(str(group['output_usd']), '0.001')
        self.assertEqual(group['reasoning_tokens_known'], 80)
        self.assertEqual(str(group['no_write_same_usage_usd']), '0.00405')

    def test_identical_response_recovery_does_not_charge_twice(self):
        row = receipt()
        self.assertEqual(analyze([row, copy.deepcopy(row)])['calls'], 1)

    def test_same_response_in_different_role_or_with_changed_usage_is_rejected(self):
        row = receipt()
        for field, value in (('role', 'review'), ('series', 'other'), ('usd', '0')):
            second = copy.deepcopy(row);second[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                analyze([row, second])

    def test_unknown_usage_is_not_zero_or_complete(self):
        result = analyze([receipt(usage=None)])
        self.assertEqual(result['unknown_calls'], 1)
        self.assertFalse(result['complete'])
        self.assertEqual(result['groups'][0]['calls'], 1)

    def test_unconfirmed_tier_is_not_costed_as_standard(self):
        result = analyze([receipt(tier='flex')])
        self.assertFalse(result['complete'])
        self.assertEqual(result['unknown_calls'], 1)

    def test_forged_amount_or_overlapping_cache_counts_are_rejected(self):
        row = receipt();row['usd'] = '0.001'
        with self.assertRaises(ValueError):analyze([row])
        row = receipt();row['usage']['input_tokens_details']['cached_tokens'] = 1800
        with self.assertRaises(ValueError):analyze([row])

    def test_long_context_and_12h_write_premium_are_preserved(self):
        usage = receipt()['usage'];usage['input_tokens'] = 300000
        row = receipt(usage=usage)
        result = analyze([row]);group = result['groups'][0]
        self.assertEqual(group['known_usd'], cost(row['model'], usage))
        self.assertEqual(str(group['output_usd']), '0.0015')
        self.assertEqual(str(group['no_write_same_usage_usd']), '1.1996')

    def test_research_review_and_series_costs_stay_separate(self):
        rows = [receipt(), receipt(response_id='response2', role='review'),
                receipt(response_id='response3', series='other')]
        result = analyze(rows)
        self.assertEqual(len(result['groups']), 3)
        self.assertEqual(result['known_usd'], sum((r['known_usd'] for r in result['groups'])))


if __name__ == '__main__':
    unittest.main()
