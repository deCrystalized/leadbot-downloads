import copy
import hashlib
import json
import os
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_http import HTTPTransport, HTTPFailure, HTTPReceipt, ProviderResult
from research_openai import ResponsesTransport, RequestNotStarted, TransportError
from research_jobs import Jobs, JobError, JobNotStarted
from api_costs import UsageLedger
from research_pipeline import pack_context
from test_research_pipeline218 import context


FAKE = 'sk-only-local-transport-test-not-a-real-key'


class Socket:
    def __init__(self):self.timeouts=[]
    def settimeout(self, value):self.timeouts.append(value)


class Response:
    def __init__(self, raw, status=200, headers=None):
        self.raw=raw;self.status=status;self.headers=headers or {};self.offset=0
    def getheader(self, name, default=None):return self.headers.get(name, default)
    def read1(self, amount):
        result=self.raw[self.offset:self.offset+amount];self.offset+=len(result);return result


class Connection:
    def __init__(self, host, **kwargs):
        self.host=host;self.kwargs=kwargs;self.sock=Socket();self.requests=[];self.closed=False
        self.response=Response(b'{"model":"gpt-6.1-sol","status":"completed"}')
    def set_debuglevel(self, level):self.debug=level
    def connect(self):pass
    def request(self, *args, **kwargs):self.requests.append((args, kwargs))
    def getresponse(self):return self.response
    def close(self):self.closed=True


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.root.chmod(0o700)
        self.key=self.root/'key';self.key.write_text(FAKE);self.key.chmod(0o600)
        self.connections=[];self.next_response=None;self.now=100.
        def factory(host, **kwargs):
            conn=Connection(host, **kwargs)
            if self.next_response is not None:conn.response=self.next_response
            self.connections.append(conn);return conn
        self.factory=factory
        self.http=HTTPTransport(self.key, enabled=True, connection_factory=factory, clock=lambda:self.now)
        self.packet=pack_context('research',context())
        # Capture the real codec body without network or a real credential.
        captured=[]
        def codec(payload, timeout):
            captured.append(payload)
            return dict(id='r',model='gpt-6.1-sol',status='completed',usage=None,service_tier='default',
                output=[dict(type='function_call',name='search_rules',arguments='{"query":"крепёж"}',call_id='http205-source-call')])
        ResponsesTransport(codec,UsageLedger())('research',self.packet,('search_rules',))
        self.payload=captured[0]

    def test_default_disabled_is_preflight_and_construction_reads_no_key_or_network(self):
        missing=self.root/'absent'
        disabled=HTTPTransport(missing,connection_factory=self.factory)
        with self.assertRaises(RequestNotStarted):disabled(self.payload,30)
        self.assertEqual(self.connections,[])

    def test_fixed_verified_https_one_request_and_canonical_body_only(self):
        raw=self.http(self.payload,30);conn=self.connections[0]
        self.assertIsInstance(raw,HTTPReceipt);self.assertEqual(conn.host,'api.openai.com')
        self.assertEqual(conn.kwargs['port'],443)
        ctx=conn.kwargs['context'];self.assertTrue(ctx.check_hostname);self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
        self.assertEqual(conn.debug,0);self.assertTrue(conn.closed);self.assertEqual(len(conn.requests),1)
        args,kwargs=conn.requests[0];self.assertEqual(args,('POST','/v1/responses'))
        self.assertEqual(kwargs['headers']['Authorization'],'Bearer '+FAKE)
        self.assertNotIn(FAKE,kwargs['body'].decode())
        self.assertEqual(json.loads(kwargs['body']),self.payload)

    def test_redirect_rate_limit_and_server_error_are_not_followed_or_retried(self):
        for status in (302,401,429,503):
            self.next_response=Response(b'{"error":{"message":"stopped"}}',status,{'Location':'https://evil.invalid','Content-Type':'application/json'})
            before=len(self.connections);raw=self.http(self.payload,30)
            self.assertEqual(len(self.connections),before+1);self.assertEqual(raw.metadata['http_status'],status)
            self.assertEqual(bytes(raw),b'{"error":{"message":"stopped"}}')

    def test_missing_permissive_symlink_and_wrong_format_key_never_connect(self):
        for change in ('missing','permissive','symlink','wrong_format'):
            with self.subTest(change=change):
                target=self.root/(change+'-key');target.write_text(FAKE);target.chmod(0o600)
                if change=='missing':target.unlink()
                if change=='permissive':target.chmod(0o644)
                if change=='symlink':target.unlink();target.symlink_to(self.key)
                if change=='wrong_format':target.write_text('invalid')
                h=HTTPTransport(target,enabled=True,connection_factory=self.factory)
                with self.assertRaises(RequestNotStarted):h(self.payload,30)
        self.assertEqual(self.connections,[])

    def test_extra_fields_wrong_model_store_or_parallel_call_flags_fail_before_key(self):
        for update in (dict(model='gpt-6-luna'),dict(store=True),dict(parallel_tool_calls=True),dict(api_key=FAKE),dict(base_url='https://evil.invalid')):
            p=dict(self.payload,**update)
            with self.subTest(update=list(update)),self.assertRaises(RequestNotStarted):self.http(p,30)
        self.assertEqual(self.connections,[])

    def test_credential_in_outgoing_payload_is_rejected_before_durable_journal(self):
        jobs=Jobs(self.root/'jobs',shared_lock=self.root/'lock')
        binding=dict(owner='o',request='r',chat='c',revision='v',principal='p',operator='a',policy='p1',
            memory='m1',map='g1',task='t',profile='sol_only')
        grant=jobs.admit(binding,max_calls=2,seconds=60);job=jobs.submit(binding,grant)['job_id']
        p=copy.deepcopy(self.payload);p['input'][0]['content'][0]['text']+=FAKE
        call=jobs.requester(job,binding,fresh=lambda:binding,request=self.http)
        with self.assertRaises(JobNotStarted):call(p,30)
        self.assertEqual(jobs.status('o',job)['calls_spent'],0)
        self.assertEqual(list((self.root/'jobs').glob('*.request.json')),[])
        self.assertEqual(self.connections,[])

    def test_credential_reflection_is_not_returned_stored_or_in_exception(self):
        self.next_response=Response(('invalid key '+FAKE).encode(),401)
        with self.assertRaises(HTTPFailure) as caught:self.http(self.payload,30)
        self.assertEqual(caught.exception.category,'credential_reflected')
        self.assertEqual(caught.exception.partial,b'')
        self.assertNotIn(FAKE,str(caught.exception));self.assertNotIn(FAKE,repr(caught.exception))
        self.assertTrue(self.connections[0].closed)

    def test_secret_header_is_not_metadata_and_request_id_is_bounded(self):
        self.next_response=Response(b'{}',200,{'Authorization':FAKE,'X-Request-ID':FAKE,'Content-Type':'text/html; key='+FAKE})
        raw=self.http(self.payload,30)
        self.assertEqual(raw.metadata,dict(schema=1,http_status=200,content_type='other'))
        self.assertNotIn(FAKE,json.dumps(raw.metadata))

    def test_partial_timeout_preserves_only_bounded_nonsecret_evidence_and_no_retry(self):
        response=Response(b'{"partial":',200)
        original=response.read1
        def read(size):
            if response.offset:raise TimeoutError(FAKE)
            return original(size)
        response.read1=read;self.next_response=response
        with self.assertRaises(HTTPFailure) as caught:self.http(self.payload,30)
        self.assertEqual(caught.exception.partial,b'{"partial":')
        self.assertNotIn(FAKE,str(caught.exception));self.assertEqual(len(self.connections),1)

    def test_total_read_deadline_is_not_reset_by_chunks(self):
        response=Response(b'abcdef',200)
        def read(size):self.now+=31;return b'a'
        response.read1=read;self.next_response=response
        with self.assertRaises(HTTPFailure) as caught:self.http(self.payload,30)
        self.assertEqual(caught.exception.category,'deadline')
        self.assertTrue(self.connections[0].closed)

    def test_bounded_response_does_not_return_truncated_json_as_success(self):
        self.next_response=Response(b'x'*65,200)
        with patch('research_http.MAX_RESPONSE_BYTES',64),self.assertRaises(HTTPFailure) as caught:self.http(self.payload,30)
        self.assertEqual(caught.exception.category,'response_too_large')
        self.assertLessEqual(len(caught.exception.partial),64)

    def test_non_2xx_success_shaped_body_is_rejected_by_codec(self):
        response=ProviderResult(dict(id='r-http',model='gpt-6.1-sol',status='completed',usage=None),
                                dict(schema=1,http_status=503,content_type='json'))
        ledger=UsageLedger();transport=ResponsesTransport(lambda *args:response,ledger)
        with self.assertRaises(TransportError):transport('research',self.packet,())
        self.assertEqual(ledger.summary()['unknown_calls'],1)

    def test_secret_split_across_network_chunks_is_not_a_safe_partial(self):
        response=Response(b'',401)
        parts=[FAKE[:15].encode(),FAKE[15:].encode(),b'']
        response.read1=lambda amount:parts.pop(0);self.next_response=response
        with self.assertRaises(HTTPFailure) as caught:self.http(self.payload,30)
        self.assertEqual(caught.exception.category,'credential_reflected');self.assertEqual(caught.exception.partial,b'')

    def test_prepared_body_is_single_use_and_write_timeout_does_not_leak_exception(self):
        prepared=self.http.prepare(self.payload);prepared(30)
        with self.assertRaises(RequestNotStarted):prepared(30)
        def factory(host,**kwargs):
            conn=self.factory(host,**kwargs)
            def write(*args,**kw):raise TimeoutError('Bearer '+FAKE)
            conn.request=write;return conn
        h=HTTPTransport(self.key,enabled=True,connection_factory=factory)
        with self.assertRaises(HTTPFailure) as caught:h(self.payload,30)
        self.assertNotIn(FAKE,str(caught.exception));self.assertTrue(self.connections[-1].closed)

    def test_role_profile_or_effort_cannot_silently_change(self):
        for update in [dict(reasoning={'effort':'low'}),dict(instructions=json.dumps(dict(role='review',profile='sol_astra')))]:
            with self.assertRaises(RequestNotStarted):self.http(dict(self.payload,**update),30)
        self.assertEqual(self.connections,[])


if __name__=='__main__':unittest.main()
