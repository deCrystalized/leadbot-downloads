"""Durable usage survives a context stop without acknowledging its answer."""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import unittest

from api_costs import UsageLedger
from research_jobs import JobError, JobNotStarted, SavedReceiptStopped
from research_openai import ResponsesTransport, TransportError
from research_pipeline import pack_context
from research_receipts import HTTPReceipt, StoppedProviderReceipt
import test_research_jobs203 as fixtures
import test_research_pipeline218 as contexts


class DurableBilling276Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DurableResearchTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.response=dict(id='resp-durable-billing',model='gpt-6.1-sol',status='completed',service_tier='default',
            usage=dict(input_tokens=16996,output_tokens=1749,total_tokens=18745,
                input_tokens_details=dict(cached_tokens=0,cache_write_tokens=5019,
                    cache_write_tokens_details=dict(ttl_12h_tokens=0,ttl_30m_tokens=5019)),
                output_tokens_details=dict(reasoning_tokens=1376)),
            output=[dict(type='message',role='assistant',content=[dict(type='output_text',text='not an accepted reply')])])
        self.metadata=dict(schema=1,http_status=200,content_type='json',request_id='req_durable_test')
        self.mutate=lambda:self.f.current.update(revision='changed')
        self.ledger=UsageLedger(Path(self.f.tmp.name)/'usage.sqlite3')
        self.raw=None

    def request(self,payload,timeout):
        self.f.calls.append(payload)
        self.raw=self.raw or json.dumps(self.response).encode()
        self.mutate()
        return HTTPReceipt(self.raw,self.metadata)

    def call(self):
        reader=self.f.jobs.requester(self.f.job,self.f.binding,fresh=lambda:self.f.current,request=self.request)
        context=contexts.context();context.update(owner_id=self.f.binding['owner'],dialogue_id=self.f.binding['chat'])
        return ResponsesTransport(reader,self.ledger)('research',pack_context('research',context,profile='sol_only'),())

    def stopped(self):
        with self.assertRaises(TransportError):self.call()
        status=self.f.jobs.status('owner',self.f.job)
        self.assertEqual(status['calls_spent'],1)
        self.assertEqual(status['steps'][0]['state'],'raw')
        self.assertFalse(status['steps'][0]['acknowledged'])
        self.assertEqual(status['steps'][0]['raw_hash'],hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(self.f.jobs.raw(self.f.job,0),self.raw)
        self.assertFalse(self.f.jobs._file(self.f.job,'result.json').exists())
        self.assertEqual(len(self.f.calls),1)
        return self.ledger.summary(owner='owner',dialogue='chat')

    def test_revision_stop_keeps_exact_usage_without_ack_review_or_candidate(self):
        value=self.stopped()
        self.assertEqual(value['calls'],1);self.assertEqual(value['known_usd'],'0.0539915')
        self.assertEqual(value['unknown_calls'],0)
        self.assertEqual(value['by_role'],[dict(role='research',calls=1,unknown_calls=0,known_usd='0.0539915')])

    def test_explicit_cancel_still_blocks_answer_but_not_original_billing(self):
        self.mutate=lambda:self.f.jobs.cancel('owner',self.f.job)
        self.assertEqual(self.stopped()['known_usd'],'0.0539915')

    def test_original_deadline_expiry_never_becomes_a_free_attempt(self):
        def expire():self.f.now+=301
        self.mutate=expire
        self.assertEqual(self.stopped()['known_usd'],'0.0539915')

    def test_fresh_source_exception_keeps_its_stop_fields_and_cost_only_fields(self):
        def fresh():
            if self.f.calls:raise JobError('private context failed',check='native_source_changed',changed_fields=('revision',))
            return self.f.current
        self.mutate=lambda:None
        reader=self.f.jobs.requester(self.f.job,self.f.binding,fresh=fresh,request=self.request)
        with self.assertRaises(SavedReceiptStopped) as caught:reader(self.f.payload(),120)
        value=caught.exception
        self.assertIsInstance(value,JobError);self.assertIsInstance(value,StoppedProviderReceipt)
        self.assertNotIsInstance(value,JobNotStarted)
        self.assertEqual(value.check,'native_source_changed');self.assertEqual(value.changed_fields,('revision',))
        self.assertNotIn('output',value.billing_response)
        self.assertNotIn('private context failed',str(value))

    def test_ledger_restart_and_failed_reobservation_do_not_bill_twice_or_regenerate(self):
        self.stopped();self.ledger=UsageLedger(self.ledger.path)
        with self.assertRaises(TransportError):self.call()
        self.assertEqual(len(self.f.calls),1)
        self.assertEqual(self.ledger.summary()['calls'],1)
        self.assertEqual(self.ledger.summary()['known_usd'],'0.0539915')

    def test_missing_usage_or_wrong_model_remains_one_unknown_call(self):
        for key,value in (('usage',None),('model','gpt-6-astra')):
            with self.subTest(key=key):
                self.setUp();self.response[key]=value
                report=self.stopped();self.assertEqual(report['calls'],1)
                self.assertEqual(report['unknown_calls'],1);self.assertFalse(report['complete'])

    def test_unconfirmed_tier_is_not_assumed_standard(self):
        for tier in (None,'priority'):
            with self.subTest(tier=tier):
                self.setUp();self.response['service_tier']=tier
                report=self.stopped();self.assertEqual(report['calls'],1)
                self.assertEqual(report['unknown_calls'],1)

    def test_invalid_counts_keep_one_unknown_receipt(self):
        self.response['usage']['output_tokens']=-1
        report=self.stopped()
        self.assertEqual(report['calls'],1);self.assertEqual(report['unknown_calls'],1)

    def test_duplicate_or_malformed_json_is_preserved_without_cost_guess_or_repair(self):
        for raw in (b'{"model":"gpt-6.1-sol","model":"gpt-6-astra"}',b'{broken'):
            with self.subTest(raw=raw):
                self.setUp();self.raw=raw
                report=self.stopped();self.assertEqual(report['calls'],1)
                self.assertEqual(report['unknown_calls'],1)

    def test_non_success_http_does_not_accept_a_success_shaped_response(self):
        self.metadata['http_status']=503
        report=self.stopped()
        self.assertEqual(report['calls'],1)
        with closing(sqlite3.connect(self.ledger.path)) as db:
            record=json.loads(db.execute('SELECT receipt FROM api_usage_receipts').fetchone()[0])
        self.assertEqual(record['status'],'failed')
        self.assertEqual(record['known_usd'],'0.0539915')

    def test_conflicting_response_identity_keeps_the_old_scope_and_new_unknown_attempt(self):
        self.ledger.add(self.response['id'],'gpt-6.1-sol',self.response['usage'],service_tier='default',
                        scope=dict(owner='another',dialogue='other',role='research'))
        report=self.stopped()
        self.assertEqual(report['calls'],1);self.assertEqual(report['unknown_calls'],1)
        self.assertEqual(self.ledger.summary()['calls'],2)
        self.assertEqual(self.ledger.summary(owner='another')['known_usd'],'0.0539915')


if __name__=='__main__':unittest.main()
