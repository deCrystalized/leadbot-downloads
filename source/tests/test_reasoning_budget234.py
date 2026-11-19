"""Bounded reasoning room and honest accounting after incomplete originals."""
import copy
import unittest

import test_research_transport218 as codec_fixture
import test_research_http205 as http_fixture
from research_openai import TransportError, RequestNotStarted


class ReasoningBudgetTests(unittest.TestCase):
    def codec(self):
        fixture = codec_fixture.TransportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_reasoning_and_reply_have_finite_32768_capacity_without_reducing_effort(self):
        fixture = self.codec()
        fixture.call()
        payload = fixture.payloads[0][0]
        self.assertEqual(payload['max_output_tokens'], 32768)
        self.assertEqual(payload['reasoning'], {'effort': 'max'})
        self.assertEqual(len(fixture.payloads), 1)

    def test_http_accepts_new_exact_cap_and_rejects_every_outside_or_untyped_budget(self):
        fixture = http_fixture.HTTPTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        payload = dict(fixture.payload, max_output_tokens=32768)
        fixture.http(payload, 30)
        self.assertEqual(len(fixture.connections), 1)
        for cap in (32769, 0, -1, True, '32768', None):
            with self.subTest(cap=cap), self.assertRaises(RequestNotStarted):
                fixture.http(dict(payload, max_output_tokens=cap), 30)
        self.assertEqual(len(fixture.connections), 1)

    def test_zero_usage_on_output_budget_exhaustion_is_unknown_not_free(self):
        fixture = self.codec()
        fixture.response.update(status='incomplete',
            incomplete_details={'reason': 'max_output_tokens'},
            output=[{'type': 'reasoning', 'encrypted_content': 'opaque-test-data'}],
            usage={'input_tokens': 0, 'output_tokens': 0,
                   'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}})
        original = copy.deepcopy(fixture.response)
        with self.assertRaises(TransportError):
            fixture.call()
        summary = fixture.ledger.summary()
        self.assertEqual(summary['calls'], 1)
        self.assertEqual(summary['unknown_calls'], 1)
        self.assertFalse(summary['complete'])
        self.assertEqual(len(fixture.payloads), 1)
        self.assertEqual(fixture.response, original)

    def test_valid_nonzero_usage_on_incomplete_output_is_still_accounted_once(self):
        fixture = self.codec()
        fixture.response.update(status='incomplete', incomplete_details={'reason': 'max_output_tokens'})
        with self.assertRaises(TransportError):
            fixture.call()
        self.assertEqual(fixture.ledger.summary()['known_usd'], '0.0248')
        self.assertEqual(fixture.ledger.summary()['unknown_calls'], 0)
        self.assertEqual(len(fixture.payloads), 1)

    def test_incomplete_output_with_missing_usage_remains_unknown_and_is_not_repaired(self):
        fixture = self.codec()
        fixture.response.update(status='incomplete', incomplete_details={'reason': 'max_output_tokens'})
        fixture.response.pop('usage')
        with self.assertRaises(TransportError):
            fixture.call()
        self.assertEqual(fixture.ledger.summary()['unknown_calls'], 1)
        self.assertEqual(len(fixture.payloads), 1)

    def test_malformed_incomplete_details_cannot_escape_as_an_attribute_error_or_approval(self):
        fixture = self.codec()
        fixture.response.update(status='incomplete', incomplete_details='invalid details')
        with self.assertRaises(TransportError):
            fixture.call()
        self.assertEqual(fixture.ledger.summary()['calls'], 1)
        self.assertEqual(fixture.ledger.summary()['known_usd'], '0.0248')
