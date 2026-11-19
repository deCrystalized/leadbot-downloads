import copy
import json
import unittest

from api_costs import UsageLedger
from research_openai import ResponsesTransport, TransportError
from research_pipeline import pack_context, Pipeline
import test_research_pipeline218 as fixtures
import test_research_native203 as native_fixture


class Continuation209Tests(unittest.TestCase):
    def setUp(self):
        self.sent=[];self.responses=[];self.ledger=UsageLedger()
        def request(payload,timeout):
            self.sent.append(copy.deepcopy(payload));return self.responses.pop(0)
        self.transport=ResponsesTransport(request,self.ledger)
        self.current=fixtures.context()

    def response(self,number,output):
        return dict(id='response-'+str(number),model='gpt-6.1-sol',status='completed',service_tier='default',
                    usage=dict(input_tokens=100,output_tokens=20,input_tokens_details=dict(cached_tokens=0,cache_write_tokens=0)),
                    output=output)

    def call(self,number=1,call_id='source-call-1',name='read_rule',args=None):
        return self.response(number,[dict(type='reasoning',id='opaque-'+str(number),encrypted_content='opaque-test-data'),
            dict(type='function_call',id='fc-'+str(number),call_id=call_id,name=name,
                 arguments=json.dumps(args or dict(rule_id='R1')),status='completed')])

    def conclusion(self,number=2,role='research'):
        value=(dict(kind='draft',reply='По крепежу скажу после осмотра.',evidence_ids=['c2'],basis=['current:c2'],claims=[])
               if role=='research' else dict(kind='review',approved=True,violations=[],checked_claims=[],basis=['current:c2']))
        return self.response(number,[dict(type='message',role='assistant',status='completed',
                                        content=[dict(type='output_text',text=json.dumps(value))])])

    def step(self,role='research',evidence=None,current=None):
        return self.transport(role,pack_context(role,current or self.current,evidence,profile='sol_only'),('read_rule','search_rules'))

    def result(self,**change):
        value=dict(last_tool_request=dict(name='read_rule',arguments=dict(rule_id='R1')),
                   last_tool_result=dict(rule_id='R1',primary_text_read=True,primary=dict(id='R1',text='Проверенное правило')),
                   rules=[dict(id='R1',text='Проверенное правило')])
        value.update(change);return value

    def test_exact_call_identity_result_and_opaque_items_reach_next_request(self):
        first=self.call();self.responses=[first,self.conclusion()]
        self.step();self.step(evidence=self.result())
        actual=self.sent[1]['input'];base=len(self.sent[0]['input']);self.assertEqual(actual[:base],self.sent[0]['input'])
        self.assertEqual(actual[base:base+2],first['output'])
        self.assertEqual(actual[base+2]['type'],'function_call_output');self.assertEqual(actual[base+2]['call_id'],'source-call-1')
        result=json.loads(actual[base+2]['output'])
        self.assertTrue(result['result']['primary_text_read']);self.assertIn('rule:R1',result['source_references'])

    def test_multiple_function_steps_preserve_the_entire_phase_in_order(self):
        first=self.call();second=self.call(2,'source-call-2','search_rules',dict(query='материалы'))
        self.responses=[first,second,self.conclusion(3)]
        self.step();self.step(evidence=self.result())
        evidence=self.result(last_tool_request=dict(name='search_rules',arguments=dict(query='материалы')),
                             last_tool_result=dict(hits=[dict(rule_id='R2')]))
        self.step(evidence=evidence)
        chain=self.sent[2]['input']
        base=len(self.sent[1]['input']);self.assertEqual(chain[:base],self.sent[1]['input'])
        self.assertEqual(chain[base:base+2],second['output']);self.assertEqual(chain[-1]['call_id'],'source-call-2')
        self.assertEqual(sum(x.get('role')=='user' for x in chain),2)

    def test_missing_result_cannot_trigger_a_new_provider_call(self):
        self.responses=[self.call()];self.step()
        with self.assertRaises(TransportError):self.step()
        self.assertEqual(len(self.sent),1);self.assertEqual(self.ledger.summary()['calls'],1)

    def test_swapped_tool_or_arguments_cannot_answer_a_pending_call(self):
        self.responses=[self.call()];self.step()
        for request in [dict(name='search_rules',arguments=dict(query='R1')),
                        dict(name='read_rule',arguments=dict(rule_id='OTHER'))]:
            with self.subTest(request=request),self.assertRaises(TransportError):
                self.step(evidence=self.result(last_tool_request=request))
        self.assertEqual(len(self.sent),1)

    def test_changed_client_context_cannot_reuse_source_continuation(self):
        self.responses=[self.call()];self.step()
        for key,value in [('dialogue_id','another'),('revision','new'),('owner_id','other')]:
            current=copy.deepcopy(self.current);current[key]=value
            with self.subTest(key=key),self.assertRaises(TransportError):self.step(evidence=self.result(),current=current)
        self.assertEqual(len(self.sent),1)

    def test_pending_research_call_cannot_be_rebound_to_reviewer(self):
        self.responses=[self.call()];self.step()
        with self.assertRaises(TransportError):self.step('review',self.result())
        self.assertEqual(len(self.sent),1)

    def test_missing_function_call_id_is_rejected_with_usage_retained(self):
        first=self.call();first['output'][1].pop('call_id');self.responses=[first]
        with self.assertRaises(TransportError):self.step()
        self.assertEqual(self.ledger.summary()['calls'],1);self.assertEqual(len(self.sent),1)

    def test_repeated_call_id_is_not_used_for_a_second_source_result(self):
        self.responses=[self.call(),self.call(2)]
        self.step()
        with self.assertRaises(TransportError):self.step(evidence=self.result())
        self.assertEqual(len(self.sent),2);self.assertEqual(self.ledger.summary()['calls'],2)

    def test_reviewer_after_draft_has_separate_context_without_research_opaque_items(self):
        self.responses=[self.call(),self.conclusion(),self.conclusion(3,'review')]
        self.step();draft=self.step(evidence=self.result());self.step('review',dict(self.result(),draft=draft))
        items=self.sent[2]['input'];self.assertEqual(len(items),3);self.assertEqual(items[0]['role'],'developer')
        self.assertFalse(any(x.get('type')in ('reasoning','function_call','function_call_output')for x in items))
        self.assertIn('draft',json.loads(items[-1]['content'][0]['text']))

    def test_reconstruction_from_same_raw_results_builds_byte_equivalent_requests(self):
        first=self.call();last=self.conclusion();self.responses=[first,last]
        self.step();self.step(evidence=self.result());original=copy.deepcopy(self.sent)
        self.setUp();self.responses=[first,last]
        self.step();self.step(evidence=self.result())
        self.assertEqual(self.sent,original)  # Mock reconstruction; no network retry.

    def test_review_instructions_do_not_order_a_new_native_candidate(self):
        current=native_fixture.native_context()
        review=json.loads(pack_context('review',current,profile='sol_only')['instructions'])
        self.assertIn('отдельный проверяющий',review['stage_contract'])
        self.assertIn('сохрани',review['native_contract'].lower())
        self.assertNotIn('Заполни candidate',review['native_contract'])

    def test_pipeline_binds_executed_tool_name_arguments_and_actual_result(self):
        f=fixtures.ResearchTests();f.setUp();self.addCleanup(f.tmp.cleanup);seq=f.sequence();seen=[]
        def model(role,packet,tools):seen.append(packet);return seq.pop(0)
        out=Pipeline(f.corpus,model,profile='sol_only').run(self.current)
        self.assertTrue(out['approved'])
        step=seen[1]['input']['research']
        self.assertEqual(step['last_tool_request'],dict(name='search_history',arguments=dict(query='шкаф крепёж купить',direction='mnc')))
        self.assertIn('hits',step['last_tool_result'])


if __name__=='__main__':unittest.main()
