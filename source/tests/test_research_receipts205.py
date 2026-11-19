import hashlib
import json
import unittest
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from research_jobs import Jobs, JobError, JobNotStarted
from research_receipts import HTTPReceipt, HTTPFailure, ProviderResult
import test_research_jobs203 as durable_fixture


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        durable_fixture.DurableResearchTests.setUp(self)
        self.metadata=dict(schema=1,http_status=200,content_type='json',request_id='req_local_only')
        self.response=b' {"id":"response","model":"gpt-6.1-sol","status":"completed"} \n'

    def payload(self):return durable_fixture.DurableResearchTests.payload(self)

    def request(self,payload,timeout):
        self.calls.append(payload);return HTTPReceipt(self.response,self.metadata)

    def reader(self,**kwargs):
        return self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=self.request,**kwargs)

    def test_raw_and_http_receipt_are_durable_before_ack_without_rewriting_body(self):
        observed=[]
        def after(path):
            receipt=self.jobs._file(self.job,'0.transport.json')
            self.assertTrue(receipt.exists());self.assertEqual(path.read_bytes(),self.response)
            state=self.jobs.status('owner',self.job)['steps'][0]
            self.assertEqual(state['state'],'raw');self.assertFalse(state['acknowledged'])
            observed.append(json.loads(receipt.read_text()))
        out=self.reader(after_raw=after)(self.payload(),30)
        self.assertIsInstance(out,ProviderResult);self.assertEqual(out.metadata,self.metadata)
        self.assertEqual(observed[0]['body_sha256'],hashlib.sha256(self.response).hexdigest())

    def test_restart_reads_exact_receipt_without_preparing_or_reading_another_key(self):
        def crash(path):raise SystemExit('simulated after raw fsync')
        with self.assertRaises(SystemExit):self.reader(after_raw=crash)(self.payload(),30)
        class MustNotPrepare:
            def prepare(self,payload):raise AssertionError('Never read a credential on completed recovery')
        recovered=Jobs(self.jobs.directory,shared_lock=self.jobs.lock,clock=lambda:self.now)
        out=recovered.requester(self.job,self.binding,fresh=lambda:self.current,request=MustNotPrepare())(self.payload(),30)
        self.assertEqual(out.metadata,self.metadata);self.assertEqual(len(self.calls),1)

    def test_deleted_or_changed_required_metadata_cannot_silently_become_plain_json(self):
        self.reader()(self.payload(),30)
        path=self.jobs._file(self.job,'0.transport.json');original=path.read_bytes()
        path.unlink()
        with self.assertRaises(JobError):self.reader()(self.payload(),30)
        path.write_bytes(original.replace(b'200',b'503'))
        with self.assertRaises(JobError):self.reader()(self.payload(),30)
        self.assertEqual(len(self.calls),1)

    def test_partial_is_evidence_not_a_complete_receipt_and_never_regenerated(self):
        calls=[]
        def request(*args):calls.append(1);raise HTTPFailure('network',b'{"partial":')
        run=lambda:self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=request)
        with self.assertRaises(JobError):run()(self.payload(),30)
        self.assertEqual(self.jobs._file(self.job,'0.partial.raw').read_bytes(),b'{"partial":')
        self.assertFalse(self.jobs._file(self.job,'0.raw').exists())
        with self.assertRaises(JobNotStarted):run()(self.payload(),30)
        self.assertEqual(calls,[1])

    def test_reflected_credential_security_stop_preserves_no_raw_or_exception_text(self):
        def request(*args):raise HTTPFailure('credential_reflected')
        call=self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=request)
        with self.assertRaises(JobError):call(self.payload(),30)
        self.assertFalse(self.jobs._file(self.job,'0.raw').exists())
        self.assertFalse(self.jobs._file(self.job,'0.partial.raw').exists())
        events=self.jobs.audit_read('owner',self.job)['events']
        self.assertTrue(any(e['event']=='provider_security_stop' for e in events))

    def test_prebody_not_started_has_no_received_receipt_or_second_attempt(self):
        from research_openai import RequestNotStarted
        def request(*args):raise RequestNotStarted('Before provider body write')
        call=self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=request)
        with self.assertRaises(JobNotStarted):call(self.payload(),30)
        self.assertEqual(self.jobs.status('owner',self.job)['steps'][0]['state'],'not_started')
        with self.assertRaises(JobNotStarted):self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=request)(self.payload(),30)

    def test_wrong_prepared_body_hash_stops_before_any_reservation_or_request_file(self):
        class Prepared:
            body_sha256='wrong';transport_kind='openai_https_v1'
            def __call__(self,timeout):raise AssertionError('Must not call')
        class Request:
            def prepare(self,payload):return Prepared()
        call=self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=Request())
        with self.assertRaises(JobNotStarted):call(self.payload(),30)
        self.assertEqual(self.jobs.status('owner',self.job)['calls_spent'],0)
        self.assertFalse(self.jobs._file(self.job,'0.request.json').exists())

    def test_unknown_metadata_fields_and_header_values_are_not_admitted(self):
        for meta in [dict(self.metadata,headers={'Authorization':'private'}),dict(self.metadata,http_status=True),
                     dict(self.metadata,content_type='private'),dict(self.metadata,request_id='sk-not-a-request-id')]:
            with self.subTest(meta=list(meta)),self.assertRaises(ValueError):HTTPReceipt(b'{}',meta)

    def test_old_plain_byte_receipt_still_replays_with_additive_database_migration(self):
        plain=lambda *args:b'{"model":"gpt-6.1-sol","status":"completed"}'
        out=self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=plain)(self.payload(),30)
        self.assertIs(type(out),dict)
        recovered=Jobs(self.jobs.directory,shared_lock=self.jobs.lock,clock=lambda:self.now)
        again=recovered.requester(self.job,self.binding,fresh=lambda:self.current,request=lambda *args:self.fail('No replay network'))(self.payload(),30)
        self.assertEqual(out,again)

    def test_crash_after_http_metadata_before_raw_never_recreates_a_response(self):
        save=self.jobs._save
        def crash(path,raw):
            if path.name.endswith('.raw'):raise SystemExit('after metadata, before original body')
            return save(path,raw)
        self.jobs._save=crash
        with self.assertRaises(SystemExit):self.reader()(self.payload(),30)
        self.assertTrue(self.jobs._file(self.job,'0.transport.json').exists())
        self.assertFalse(self.jobs._file(self.job,'0.raw').exists())
        recovered=Jobs(self.jobs.directory,shared_lock=self.jobs.lock,clock=lambda:self.now)
        with self.assertRaises(JobNotStarted):
            recovered.requester(self.job,self.binding,fresh=lambda:self.current,request=self.request)(self.payload(),30)
        self.assertEqual(len(self.calls),1)

    def test_parallel_old_schema_migration_keeps_existing_receipt_rows(self):
        directory=Path(self.tmp.name)/'old-schema';directory.mkdir(mode=0o700)
        with closing(sqlite3.connect(directory/'jobs.sqlite3')) as db,db:
            db.execute('CREATE TABLE steps(job TEXT,step INTEGER,request_hash TEXT,role TEXT,model TEXT,state TEXT,raw_hash TEXT,acknowledged INTEGER,PRIMARY KEY(job,step))')
            db.execute("INSERT INTO steps VALUES('old',0,'request','research','gpt-6.1-sol','acknowledged','raw',1)")
        with ThreadPoolExecutor(max_workers=4) as pool:
            values=list(pool.map(lambda _:Jobs(directory,shared_lock=self.jobs.lock),range(4)))
        with values[0].connect() as db:
            row=dict(db.execute("SELECT * FROM steps WHERE job='old'").fetchone())
        self.assertEqual(row['raw_hash'],'raw');self.assertEqual(row['acknowledged'],1)
        self.assertIsNone(row['transport_kind']);self.assertIsNone(row['transport_hash'])


if __name__=='__main__':unittest.main()
