import copy
import json
import tempfile
import unittest
from pathlib import Path

from api_costs import UsageLedger
from experienced_dialogues import digest
from research_openai import ResponsesTransport, TransportError, RequestNotStarted
from research_pipeline import pack_context
from research_receipts import SSEReceipt, HTTPReceipt, ProviderResult
from research_jobs import Jobs, JobError, JobNotStarted
import research_cache
import research_subscription
import test_research_pipeline218 as fixtures
import test_research_jobs203 as job_fixture
import test_research_http205 as http_fixture
import test_research_native203 as native_fixture


def final_response():
    return dict(id='response-plan', model='gpt-6.1-sol', status='completed', service_tier='default',
                usage=dict(input_tokens=1000, output_tokens=100,
                           input_tokens_details=dict(cached_tokens=400, cache_write_tokens=0)),
                output=[dict(type='message', role='assistant', status='completed', content=[
                    dict(type='output_text', text=json.dumps(dict(kind='draft', reply='Уточню по Вашему вопросу.',
                         evidence_ids=['c2'], basis=['current:c2'], claims=[])))])])


def frame(kind, number, **kwargs):
    return ('event: '+kind+'\ndata: '+json.dumps(dict(type=kind, sequence_number=number, **kwargs))+'\n\n').encode()


def stream():
    r=final_response()
    return (frame('response.created', 0, response=dict(id=r['id'], status='in_progress'))
            +frame('response.output_text.delta', 1, delta='not customer-ready')
            +frame('response.completed', 2, response=r))


class Cache213Tests(unittest.TestCase):
    def payload(self, current=None, role='research', research=None):
        calls=[]
        def request(p,t):
            calls.append(p);r=final_response()
            if role=='review':
                r['output'][0]['content'][0]['text']=json.dumps(dict(kind='review',approved=True,violations=[],checked_claims=[],basis=[]))
            elif current and current.get('candidate_contract'):
                # The cache test still returns a valid original native-stage
                # response; production transport no longer trusts strict mode.
                candidate=native_fixture.native()
                draft=json.loads(r['output'][0]['content'][0]['text'])
                draft.update(candidate=candidate,reply=candidate['reply'])
                r['output'][0]['content'][0]['text']=json.dumps(draft)
            return r
        ResponsesTransport(request,UsageLedger())(role,pack_context(role,current or fixtures.context(),research),())
        return calls[0]

    def test_client_changes_share_only_the_core_not_current_text(self):
        first=self.payload();current=fixtures.context()
        current.update(owner_id='another-owner',dialogue_id='another-client',revision='r2')
        current['messages'][-1]['body']='Секунду, пожалуйста.'
        second=self.payload(current)
        self.assertEqual(first['input'][0],second['input'][0])
        self.assertNotEqual(first['input'][-1],second['input'][-1])
        self.assertEqual(research_cache.diagnostics(first)['partition_hash'],research_cache.diagnostics(second)['partition_hash'])
        self.assertNotIn('another-client',json.dumps(second['input'][0]))

    def test_exact_stage_instructions_are_preserved_without_client_cache_markers(self):
        packet=pack_context('research',fixtures.context());p=self.payload()
        self.assertEqual(p['input'][0]['content'][0]['text'],packet['instructions'])
        self.assertNotIn('stage_contract',p['instructions'])
        self.assertNotIn('prompt_cache_breakpoint',json.dumps(p['input'][1:]))
        self.assertEqual(p['reasoning'],dict(effort='max'));self.assertEqual(p['max_output_tokens'],32768)

    def test_policy_and_stage_change_invalidate_the_partition(self):
        base=research_cache.diagnostics(self.payload())
        current=fixtures.context();current['policy_version']='new-policy'
        self.assertNotEqual(base['partition_hash'],research_cache.diagnostics(self.payload(current))['partition_hash'])
        self.assertNotEqual(base['partition_hash'],research_cache.diagnostics(self.payload(role='review'))['partition_hash'])

    def test_dynamic_native_schema_misses_are_reported_without_removing_constraints(self):
        current=native_fixture.native_context();first=self.payload(current)
        original=copy.deepcopy(current['candidate_contract']['schema'])
        current['candidate_contract']['schema']['description']='changed exact admitted schema'
        second=self.payload(current)
        self.assertEqual(first['text']['format']['schema']['properties']['candidate'],original)
        self.assertNotEqual(research_cache.diagnostics(first)['partition_hash'],research_cache.diagnostics(second)['partition_hash'])
        self.assertFalse(research_cache.diagnostics(second)['measured_hit'])

    def test_full_read_sources_are_outside_shared_core_and_never_discarded(self):
        history=dict(case_id='old',messages=[dict(id='old1',body='Полный оригинал: детали куплю сам.')])
        rule=dict(id='R1',text='Точная норма: исключение и минимум сохраняются.')
        p=self.payload(research=dict(histories=[history],rules=[rule]))
        full=json.loads(p['input'][1]['content'][0]['text'])
        self.assertEqual(full['research']['histories'],[history]);self.assertEqual(full['research']['rules'],[rule])
        self.assertNotIn('Полный оригинал',p['input'][0]['content'][0]['text'])

    def test_extra_dynamic_breakpoint_or_changed_stage_is_rejected(self):
        p=self.payload();p['input'][-1]['content'][0]['prompt_cache_breakpoint']={'mode':'explicit'}
        with self.assertRaises(ValueError):research_cache.validate(p)
        p=self.payload();p['instructions']=json.dumps(dict(role='review',profile='sol_only',cache_contract='explicit_core_v1'))
        with self.assertRaises(ValueError):research_cache.validate(p)

    def test_long_lifetime_is_not_silently_selected(self):
        p=self.payload();p['prompt_cache_options']['ttl']='12h'
        with self.assertRaises(ValueError):research_cache.validate(p)


class Subscription213Tests(unittest.TestCase):
    def test_wire_omits_unsupported_output_cap_and_groups_readonly_tools(self):
        captured=[]
        t=ResponsesTransport(lambda p,s:(captured.append(p) or final_response()),UsageLedger(),funding='chatgpt_plan')
        t('research',pack_context('research',fixtures.context()),('search_rules','read_history'))
        p=captured[0]
        self.assertIs(p['stream'],True);self.assertIs(p['store'],False)
        self.assertNotIn('max_output_tokens',p);self.assertNotIn('previous_response_id',p)
        self.assertEqual(p['tools'][0]['type'],'namespace')
        self.assertEqual([x['name'] for x in p['tools'][0]['tools']],['search_rules','read_history'])
        self.assertEqual(p['reasoning'],{'effort':'max'})

    def test_subscription_usage_is_not_standard_api_price_or_zero_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'usage.sqlite3';ledger=UsageLedger(path)
            r=final_response()
            ledger.add(r['id'],r['model'],r['usage'],service_tier='default',funding='chatgpt_plan')
            summary=UsageLedger(path).summary()
            self.assertEqual(summary['by_funding'],dict(api=0,chatgpt_plan=1))
            self.assertEqual(summary['unknown_calls'],1);self.assertFalse(summary['complete'])
            self.assertTrue(summary['api_cost_complete']);self.assertFalse(summary['subscription_cost_allocated'])
            with ledger.path.open('rb') as f:self.assertTrue(f.read(16).startswith(b'SQLite'))

    def test_funding_cannot_be_changed_for_a_saved_response(self):
        ledger=UsageLedger();r=final_response()
        ledger.add('same',r['model'],r['usage'],service_tier='default')
        with self.assertRaises(ValueError):ledger.add('same',r['model'],r['usage'],service_tier='default',funding='chatgpt_plan')
        self.assertEqual(ledger.summary()['by_funding'],dict(api=1,chatgpt_plan=0))

    def test_plan_limit_does_not_call_paid_transport_or_choose_another_model(self):
        calls=[];ledger=UsageLedger()
        def request(p,t):
            calls.append(p)
            return dict(final_response(),status='failed',error=dict(code='subscription_sharing_usage_limit_exceeded'))
        transport=ResponsesTransport(request,ledger,funding='chatgpt_plan')
        with self.assertRaises(TransportError):transport('research',pack_context('research',fixtures.context()),())
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['model'],'gpt-6.1-sol')
        self.assertEqual(ledger.summary()['by_funding'],dict(api=0,chatgpt_plan=1))

    def test_api_key_transport_cannot_accept_subscription_wire_before_key_read(self):
        fixture=http_fixture.HTTPTests();fixture.setUp();self.addCleanup(fixture.tmp.cleanup)
        payload=research_subscription.project(fixture.payload)
        fixture.http._key=lambda:self.fail('Must not read a key for subscription mode')
        with self.assertRaises(RequestNotStarted):fixture.http(payload,30)
        self.assertEqual(fixture.connections,[])

    def test_only_named_source_namespace_can_request_a_history(self):
        response=final_response();response['output']=[dict(type='function_call',namespace='sources',name='read_history',
            arguments='{"case_id":"old"}',call_id='c-1')]
        t=ResponsesTransport(lambda *a:response,UsageLedger(),funding='chatgpt_plan')
        self.assertEqual(t('research',pack_context('research',fixtures.context()),('read_history',))['name'],'read_history')
        response['output'][0]['namespace']='crm'
        with self.assertRaises(TransportError):ResponsesTransport(lambda *a:response,UsageLedger(),funding='chatgpt_plan')(
            'research',pack_context('research',fixtures.context()),('read_history',))

    def test_unknown_funding_rejected_without_a_request(self):
        with self.assertRaises(TransportError):ResponsesTransport(lambda *a:self.fail('No call'),UsageLedger(),funding='automatic')

    def test_unsupported_options_cannot_be_silently_sent_or_dropped(self):
        payload=Cache213Tests().payload()
        for key in ('background','metadata','previous_response_id','max_tool_calls','safety_identifier'):
            with self.subTest(key=key),self.assertRaises(ValueError):research_subscription.project(dict(payload,**{key:'extra'}))


class SSE213Tests(unittest.TestCase):
    def test_terminal_object_is_used_without_reconstructing_delta_text(self):
        self.assertEqual(research_subscription.decode(stream()),final_response())

    def test_delta_followed_by_plan_limit_is_never_an_answer(self):
        raw=frame('response.output_text.delta',0,delta='Пишите адрес')+frame('error',1,code='subscription_sharing_usage_limit_exceeded')
        with self.assertRaises(ValueError):research_subscription.decode(raw)

    def test_no_terminal_and_interrupted_terminal_are_rejected(self):
        for raw in (frame('response.output_text.delta',0,delta='Ответ'),stream()[:-1],b'',b'not SSE\n\n'):
            with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):research_subscription.decode(raw)

    def test_incomplete_failed_or_success_shaped_error_are_rejected(self):
        for kind in ('response.incomplete','response.failed','error'):
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                research_subscription.decode(frame(kind,0,response=final_response()))

    def test_final_identity_cannot_change_or_complete_twice(self):
        first=frame('response.created',0,response=dict(id='other',status='in_progress'))
        for raw in (first+frame('response.completed',1,response=final_response()),
                    stream()+frame('response.completed',3,response=final_response())):
            with self.assertRaises(ValueError):research_subscription.decode(raw)

    def test_delta_from_another_response_cannot_enter_this_stream(self):
        raw=frame('response.created',0,response=dict(id='response-plan'))+frame(
            'response.output_text.delta',1,response_id='another-response',delta='foreign')+frame(
            'response.completed',2,response=final_response())
        with self.assertRaises(ValueError):research_subscription.decode(raw)

    def test_event_order_duplicate_json_and_nonfinite_are_rejected(self):
        for raw in (stream()+frame('response.output_text.delta',1,delta='late'),
                    b'data: {"type":"response.completed","type":"response.completed","sequence_number":0}\n\n',
                    b'data: {"type":"response.completed","sequence_number":NaN}\n\n',
                    b'event: response.failed\ndata: {"type":"response.completed","sequence_number":0}\n\n'):
            with self.assertRaises(ValueError):research_subscription.decode(raw)

    def test_comments_crlf_and_multiline_json_preserve_terminal_object(self):
        raw=b': keepalive\r\n\r\n'+stream().replace(b'\n',b'\r\n')
        self.assertEqual(research_subscription.decode(raw),final_response())
        payload=json.dumps(dict(type='response.completed',sequence_number=0,response=final_response()),indent=2)
        raw=('\n'.join('data: '+line for line in payload.splitlines())+'\n\n').encode()
        self.assertEqual(research_subscription.decode(raw),final_response())


class DurableSSE213Tests(unittest.TestCase):
    def setUp(self):
        job_fixture.DurableResearchTests.setUp(self)
        self.raw=stream();self.meta=dict(schema=1,http_status=200,content_type='event_stream')

    def payload(self):return job_fixture.DurableResearchTests.payload(self)
    def reader(self,**kwargs):
        def request(*args):self.calls.append(1);return SSEReceipt(self.raw,self.meta)
        return self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=request,**kwargs)

    def test_original_stream_fsynced_before_ack_and_decode(self):
        seen=[]
        def inspect(path):
            self.assertEqual(path.read_bytes(),self.raw)
            self.assertFalse(self.jobs.status('owner',self.job)['steps'][0]['acknowledged'])
            seen.append(self.jobs._file(self.job,'0.transport.json').read_bytes())
        result=self.reader(after_raw=inspect)(self.payload(),30)
        self.assertIsInstance(result,ProviderResult);self.assertEqual(dict(result),final_response());self.assertEqual(len(seen),1)

    def test_crash_after_stream_fsync_recovers_without_token_or_second_request(self):
        def crash(*a):raise SystemExit('after original fsync')
        with self.assertRaises(SystemExit):self.reader(after_raw=crash)(self.payload(),30)
        restarted=Jobs(self.jobs.directory,shared_lock=self.jobs.lock,clock=lambda:self.now)
        def forbidden(*args):self.fail('No OAuth/token/network during recovery')
        result=restarted.requester(self.job,self.binding,fresh=lambda:self.current,request=forbidden)(self.payload(),30)
        self.assertEqual(dict(result),final_response());self.assertEqual(self.calls,[1])

    def test_late_error_is_saved_as_original_failure_and_never_regenerated(self):
        self.raw=frame('response.output_text.delta',0,delta='not ready')+frame('error',1,code='subscription_sharing_usage_unavailable')
        with self.assertRaises(JobError):self.reader()(self.payload(),30)
        self.assertEqual(self.jobs._file(self.job,'0.raw').read_bytes(),self.raw)
        with self.assertRaises(JobNotStarted):self.reader()(self.payload(),30)
        self.assertEqual(self.calls,[1])

    def test_kind_cannot_be_downgraded_to_json_on_restart(self):
        self.reader()(self.payload(),30)
        with self.jobs.connect() as db:
            db.execute("UPDATE steps SET transport_kind='openai_https_v1' WHERE job=?",(self.job,))
        with self.assertRaises(JobError):self.reader()(self.payload(),30)
        self.assertEqual(self.calls,[1])

    def test_http_json_receipt_cannot_masquerade_as_a_subscription_stream(self):
        def request(*args):return HTTPReceipt(self.raw,self.meta)
        with self.assertRaises(JobError):self.jobs.requester(self.job,self.binding,fresh=lambda:self.current,request=request)(self.payload(),30)
        self.assertFalse(self.jobs._file(self.job,'0.raw').exists())
