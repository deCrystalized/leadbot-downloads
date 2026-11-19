import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from api_costs import UsageLedger, cost
from research_openai import ResponsesTransport, TransportError
from research_pipeline import pack_context
import test_research_transport218 as transport_fixture
import test_research_pipeline218 as pipeline_fixture
import test_research_http205 as http_fixture


def usage():
    return dict(input_tokens=12000,output_tokens=400,
        input_tokens_details=dict(cached_tokens=4000,cache_write_tokens=7000,
            cache_write_tokens_details=dict(ttl_30m_tokens=3000,ttl_12h_tokens=4000)),
        output_tokens_details=dict(reasoning_tokens=300))


class Billing208Tests(unittest.TestCase):
    def test_mixed_write_lifetimes_count_each_token_once(self):
        self.assertEqual(cost('gpt-6.1-sol',usage()),Decimal('0.0339'))

    def test_actual_write_details_override_request_ttl_without_double_charge(self):
        self.assertEqual(cost('gpt-6.1-sol',usage(),cache_ttl='12h'),Decimal('0.0339'))

    def test_invalid_overlapping_or_boolean_lifetime_counts_are_rejected(self):
        for details in [dict(ttl_30m_tokens=3000,ttl_12h_tokens=5000),
                        dict(ttl_30m_tokens=True,ttl_12h_tokens=6999),
                        dict(ttl_30m_tokens=-1,ttl_12h_tokens=7001)]:
            u=usage();u['input_tokens_details']['cache_write_tokens_details']=details
            with self.subTest(details=details),self.assertRaises(ValueError):
                cost('gpt-6.1-sol',u)

    def test_partial_lifetime_details_are_unknown_not_zero_or_guessed(self):
        u=usage();u['input_tokens_details']['cache_write_tokens_details'].pop('ttl_12h_tokens')
        self.assertIsNone(cost('gpt-6.1-sol',u))

    def test_long_context_multiplies_input_categories_and_output_separately(self):
        u=usage();u['input_tokens']=300000
        # Ordinary289000*2 + cached4000*.1 + writes3000*2.5+4000*5,
        # doubled, then400output*10*1.5. Reasoning is already part of400.
        self.assertEqual(cost('gpt-6.1-sol',u),Decimal('1.2178'))

    def test_reported_nonstandard_or_missing_tier_has_unknown_cost(self):
        for tier in (None,'priority','flex','scale','auto'):
            ledger=UsageLedger();ledger.add('r','gpt-6.1-sol',usage(),service_tier=tier)
            s=ledger.summary()
            self.assertEqual(s['unknown_calls'],1)
            self.assertFalse(s['complete'])
            self.assertNotEqual(s['tier'],'standard')

    def test_role_dialogue_error_totals_and_restart_do_not_duplicate_receipts(self):
        with tempfile.TemporaryDirectory()as tmp:
            path=Path(tmp)/'usage.sqlite3';ledger=UsageLedger(path)
            for rid,role,status,u in [('draft','research','completed',usage()),
                                       ('check','review','completed',usage()),
                                       ('failure','research','failed',None)]:
                ledger.add(rid,'gpt-6.1-sol',u,status=status,service_tier='default',
                    scope=dict(owner='owner',dialogue='one',role=role))
            ledger=UsageLedger(path)
            ledger.add('draft','gpt-6.1-sol',usage(),service_tier='default',
                scope=dict(owner='owner',dialogue='one',role='research'))
            s=ledger.summary(owner='owner',dialogue='one')
            self.assertEqual(s['calls'],3);self.assertEqual(s['known_usd'],'0.0678')
            self.assertEqual(s['unknown_calls'],1)
            roles={r['role']:r for r in s['by_role']}
            self.assertEqual(roles['review']['known_usd'],'0.0339')
            self.assertEqual(roles['research']['unknown_calls'],1)
            self.assertEqual(ledger.summary(owner='another')['calls'],0)

    def test_actual_tier_is_part_of_immutable_receipt_identity(self):
        ledger=UsageLedger();ledger.add('r','gpt-6.1-sol',usage(),service_tier='default')
        with self.assertRaises(ValueError):ledger.add('r','gpt-6.1-sol',usage(),service_tier='priority')


class TransportBilling208Tests(unittest.TestCase):
    def setUp(self):
        self.f=transport_fixture.TransportTests();self.f.setUp()
        self.f.response['service_tier']='default'

    def test_request_pins_standard_tier_cache_lifetime_and_retains_max_effort(self):
        self.f.call();p=self.f.payloads[0][0]
        self.assertEqual(p['service_tier'],'default')
        self.assertEqual(p['prompt_cache_options'],dict(mode='explicit',ttl='30m'))
        self.assertEqual(p['reasoning'],dict(effort='max'))
        self.assertEqual(self.f.ledger.summary()['verified_tier_calls'],1)

    def test_long_request_uses_remaining_original_deadline_not120second_cap(self):
        p=pack_context('research',pipeline_fixture.context());p['remaining_seconds']=245
        self.f.transport('research',p,('search_history',))
        self.assertEqual(self.f.payloads[0][1],245)

    def test_missing_or_changed_returned_tier_stops_without_retry_and_keeps_usage(self):
        for tier in (None,'priority','scale'):
            with self.subTest(tier=tier):
                self.f.setUp()
                if tier is not None:self.f.response['service_tier']=tier
                else:self.f.response.pop('service_tier',None)
                with self.assertRaises(TransportError):self.f.call()
                self.assertEqual(len(self.f.payloads),1)
                self.assertEqual(self.f.ledger.summary()['unknown_calls'],1)
                self.assertEqual(self.f.ledger.summary()['calls'],1)

    def test_http_preflight_rejects_other_tier_before_connection(self):
        f=http_fixture.HTTPTests();f.setUp();self.addCleanup(f.doCleanups)
        body=copy.deepcopy(f.payload);body['service_tier']='priority'
        from research_openai import RequestNotStarted
        with self.assertRaises(RequestNotStarted):f.http(body,30)
        self.assertEqual(f.connections,[])

    def test_invalid_usage_still_records_one_unknown_billable_attempt(self):
        self.f.response['usage']['input_tokens']=True
        with self.assertRaises(TransportError):self.f.call()
        self.assertEqual(len(self.f.payloads),1)
        self.assertEqual(self.f.ledger.summary()['calls'],1)
        self.assertEqual(self.f.ledger.summary()['unknown_calls'],1)

    def test_http_error_with_invalid_usage_does_not_drop_failed_attempt(self):
        from research_receipts import ProviderResult
        self.f.response=ProviderResult(dict(self.f.response),dict(schema=1,http_status=503,content_type='json'))
        self.f.response['usage']['output_tokens']=-1
        with self.assertRaises(TransportError):self.f.call()
        self.assertEqual(self.f.ledger.summary()['unknown_calls'],1)

    def test_conflicting_response_id_preserves_first_receipt_and_marks_new_outcome_unknown(self):
        self.f.call()
        self.f.response['usage']['output_tokens']+=1
        # Two independently attempted responses share the billing ledger. The
        # first codec is still waiting for its function result and must not
        # issue another request without that result merely to test billing.
        from research_openai import ResponsesTransport
        self.f.transport=ResponsesTransport(self.f.transport.request,self.f.ledger)
        with self.assertRaises(TransportError):self.f.call()
        self.assertEqual(len(self.f.payloads),2)
        s=self.f.ledger.summary()
        self.assertEqual(s['calls'],2);self.assertEqual(s['unknown_calls'],1)
        self.assertEqual(s['known_usd'],'0.0248')

    def test_http_error_cannot_price_a_different_model_at_requested_sol_rate(self):
        from research_receipts import ProviderResult
        self.f.response=ProviderResult(dict(self.f.response,model='gpt-6-astra'),
            dict(schema=1,http_status=503,content_type='json'))
        with self.assertRaises(TransportError):self.f.call()
        self.assertEqual(self.f.ledger.summary()['unknown_calls'],1)
        self.assertFalse(self.f.ledger.summary()['complete'])


if __name__=='__main__':unittest.main()
