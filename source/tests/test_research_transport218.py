import json
import unittest

from research_openai import ResponsesTransport, TransportError, tool_definitions
from research_pipeline import pack_context, ResearchError, Pipeline
from api_costs import UsageLedger
from test_research_pipeline218 import context


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.payloads=[];self.response=dict(id='resp-1',model='gpt-6.1-sol',status='completed',service_tier='default',
            usage=dict(input_tokens=10000,output_tokens=2000,input_tokens_details=dict(cached_tokens=8000,cache_write_tokens=0)),
            output=[dict(type='function_call',name='search_history',arguments=json.dumps(dict(query='крепёж',direction='mnc')),call_id='call-1')])
        def request(payload,timeout):self.payloads.append((payload,timeout));return self.response
        self.ledger=UsageLedger();self.transport=ResponsesTransport(request,self.ledger)

    def call(self,role='research'):
        return self.transport(role,pack_context(role,context(),profile='sol_astra'),('search_history','read_history','search_rules','read_rule'))

    def test_sol_function_call_schema_and_no_action_tool_or_user_model_override(self):
        out=self.call();p,_=self.payloads[0]
        self.assertEqual(p['model'],'gpt-6.1-sol');self.assertEqual(out['name'],'search_history')
        self.assertFalse(p['store']);self.assertFalse(p['parallel_tool_calls']);self.assertEqual(p['max_output_tokens'],32768)
        self.assertEqual({t['name']for t in p['tools']},{'search_history','read_history','search_rules','read_rule'})
        self.assertTrue(all(t['strict']and not t['parameters']['additionalProperties']for t in p['tools']))
        self.assertEqual(self.ledger.summary()['known_usd'],'0.0248')
        self.assertEqual(self.ledger.summary()['by_dialogue'][0]['dialogue'],'current')

    def test_review_is_astra_and_uses_same_sources_not_a_cheaper_fallback(self):
        self.response['model']='gpt-6-astra';self.response['output']=[dict(type='message',role='assistant',status='completed',content=[dict(type='output_text',text=json.dumps(dict(kind='review',approved=True,violations=[],checked_claims=[0],basis=['rule:R1'])))])]
        out=self.call('review');self.assertTrue(out['approved']);self.assertEqual(self.payloads[0][0]['model'],'gpt-6-astra')

    def test_no_json_repair_no_codefence_and_no_two_tool_calls(self):
        for args in ["{'query':'крепёж','direction':'mnc'}",'```json\n{}\n```']:
            self.response['output'][0]['arguments']=args
            with self.subTest(args=args),self.assertRaises(TransportError):self.call()
        self.response['output']*=2
        with self.assertRaises(TransportError):self.call()

    def test_incomplete_refusal_and_usage_all_remain_billable(self):
        self.response['status']='incomplete'
        with self.assertRaises(TransportError):self.call()
        self.assertEqual(self.ledger.summary()['calls'],1);self.assertTrue(self.ledger.summary()['complete'])
        self.assertEqual(self.ledger.summary()['known_usd'],'0.0248')

    def test_timeout_has_unknown_receipt_without_retry(self):
        calls=[]
        def request(payload,timeout):calls.append(payload);raise TimeoutError('secret')
        l=UsageLedger();t=ResponsesTransport(request,l)
        with self.assertRaises(TransportError):t('research',pack_context('research',context()),())
        self.assertEqual(len(calls),1);self.assertEqual(l.summary()['unknown_calls'],1)

    def test_empty_usage_not_zero_and_unexpected_model_or_tool_rejected(self):
        self.response.pop('usage');self.call();self.assertFalse(self.ledger.summary()['complete'])
        self.response['model']='gpt-6-luna'
        with self.assertRaises(TransportError):self.call()

    def test_only_source_tools_and_role_packet_must_match(self):
        for patch in [dict(model='gpt-6-luna'),dict(model='gpt-6-astra')]:
            p=pack_context('research',context());p.update(patch)
            with self.subTest(patch=patch),self.assertRaises(TransportError):self.transport('research',p,())
        with self.assertRaises(TransportError):tool_definitions(('send_message',))

    def test_context_budget_is_propagated_and_no_network_constructor_side_effect(self):
        self.assertEqual(self.payloads,[])
        p=pack_context('research',context());p['remaining_seconds']=12
        self.transport('research',p,('search_history',));self.assertLessEqual(self.payloads[0][1],12)

    def test_malformed_or_multi_message_response_cannot_hide_another_answer(self):
        for output in [[],[dict(type='message',role='assistant',status='completed',content=[dict(type='refusal',refusal='no')])],[dict(type='function_call',name='send_message',arguments='{}')]]:
            self.response['output']=output
            with self.subTest(output=output),self.assertRaises(TransportError):self.call()


if __name__=='__main__':unittest.main()

class EconomicTransportTests(unittest.TestCase):
    def test_sol_only_reviewer_request_and_ledger_rate_are_sol(self):
        l=UsageLedger();calls=[]
        def request(payload,timeout):
            calls.append(payload);return dict(id='only-sol',model='gpt-6.1-sol',status='completed',service_tier='default',
              usage=dict(input_tokens=12000,output_tokens=1000,input_tokens_details=dict(cached_tokens=8000,cache_write_tokens=0)),
              output=[dict(type='message',role='assistant',status='completed',content=[dict(type='output_text',text=json.dumps(dict(kind='review',approved=False,violations=['Нужны данные'],checked_claims=[0],basis=['current:c2'])))])])
        t=ResponsesTransport(request,l);p=pack_context('review',context(),profile='sol_only');out=t('review',p,())
        self.assertFalse(out['approved']);self.assertEqual(calls[0]['model'],'gpt-6.1-sol');self.assertEqual(l.summary()['known_usd'],'0.0188')

    def test_reusable_sources_precede_changing_current_dialogue_without_cross_customer_cache(self):
        l=UsageLedger();calls=[]
        def request(payload,timeout):calls.append(payload);raise TimeoutError()
        t=ResponsesTransport(request,l);p=pack_context('research',context(),dict(histories=[dict(case_id='old',messages=[])],rules=[dict(id='R1')],draft=None),profile='sol_only')
        with self.assertRaises(TransportError):t('research',p,())
        items=calls[0]['input'];self.assertEqual(items[0]['role'],'developer');self.assertIn('histories',items[1]['content'][0]['text']);self.assertNotIn('Купить сможете',items[0]['content'][0]['text'])
        self.assertIn('Купить сможете',items[-1]['content'][0]['text'])
