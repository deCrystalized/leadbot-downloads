import copy
import json
import unittest

from research_openai import ResponsesTransport
from research_pipeline import Pipeline, pack_context, ResearchError
from api_costs import UsageLedger
from test_research_pipeline218 import context
import test_research_pipeline218 as fixtures


def native_context():
    c=context()
    review=dict(type='object',properties=dict(last_intent=dict(type='string'),latest_client_meaning=dict(type='string'),
        selected_step_fits=dict(type='boolean'),evidence_ids=dict(type='array',items=dict(type='string')),note=dict(type='string')),
        required=['last_intent','latest_client_meaning','selected_step_fits','evidence_ids','note'],additionalProperties=False)
    schema=dict(type='object',properties=dict(reply=dict(type='string'),needs_operator=dict(type='boolean'),context_review=review),
        required=['reply','needs_operator','context_review'],additionalProperties=False)
    c['candidate_contract']=dict(system='Прочитайте историю, заполните свободный смысл и оцените шаг.',
        task=dict(decision=dict(next_question='Схема есть?')),schema=schema)
    return c


def native(fits=True):
    return dict(reply='По крепежу смогу сказать после осмотра.' if fits else '',needs_operator=not fits,
        context_review=dict(last_intent='Клиент спрашивает о покупке крепежа.',latest_client_meaning='Просит купить отсутствующий крепёж.',
            selected_step_fits=fits,evidence_ids=['c2'],note='Наличие не подтверждено.' if fits else 'Следует ответить на вопрос, а не спрашивать схему.'))


class NativeResearchContractTests(unittest.TestCase):
    def setUp(self):
        self.r=fixtures.ResearchTests();self.r.setUp();self.addCleanup(self.r.tmp.cleanup)

    def run_native(self,candidate,**patch):
        draft=self.r.draft();draft.update(reply=candidate['reply'],candidate=candidate);draft.update(patch)
        seq=self.r.sequence();seq[-2]=draft
        def model(role,packet,tools):return seq.pop(0)
        return Pipeline(self.r.corpus,model).run(native_context())

    def test_independent_original_native_fields_are_preserved_not_server_composed(self):
        value=native();saved=copy.deepcopy(value);out=self.run_native(value)
        self.assertTrue(out['approved']);self.assertEqual(out['candidate'],saved)
        self.assertEqual(out['candidate']['context_review']['last_intent'],'Клиент спрашивает о покупке крепежа.')
        self.assertFalse(out['can_send_or_create'])

    def test_safe_native_veto_can_be_reviewed_without_forcing_true_or_nonempty_reply(self):
        out=self.run_native(native(False));self.assertTrue(out['approved']);self.assertEqual(out['reply'],'')
        self.assertFalse(out['candidate']['context_review']['selected_step_fits'])

    def test_root_reply_cannot_disagree_with_original_native_candidate(self):
        out=self.run_native(native(),reply='Другой текст');self.assertFalse(out['approved'])

    def test_missing_or_inconsistent_native_meaning_never_passes(self):
        for change in ['missing','contradict','unknown']:
            value=native()
            if change=='missing':value.pop('context_review')
            if change=='contradict':value['context_review']['selected_step_fits']=False
            if change=='unknown':value['context_review']['server_repaired']=True
            with self.subTest(change=change):self.assertFalse(self.run_native(value)['approved'])

    def test_outer_schema_contains_exact_original_conditional_contract(self):
        c=native_context();payloads=[]
        def request(payload,timeout):payloads.append(payload);raise TimeoutError()
        t=ResponsesTransport(request,UsageLedger())
        with self.assertRaises(ValueError):t('research',pack_context('research',c),())
        props=payloads[0]['text']['format']['schema']['properties']
        self.assertEqual(props['candidate'],c['candidate_contract']['schema'])
        self.assertIn('candidate',payloads[0]['text']['format']['schema']['required'])

    def test_original_conversation_only_once_in_transport_context(self):
        c=native_context();c['candidate_contract']['task']['conversation']=copy.deepcopy(c['messages'])
        with self.assertRaises(ResearchError):pack_context('research',c)

    def test_audit_records_observation_search_full_reads_basis_and_review(self):
        events=[];seq=self.r.sequence()
        def model(role,packet,tools):return seq.pop(0)
        out=Pipeline(self.r.corpus,model,audit=lambda event,detail:events.append((event,detail))).run(context())
        self.assertTrue(out['approved'])
        names=[event for event,detail in events]
        for name in ('context_observed','source_tool_requested','source_tool_result','decision_basis','review_result','research_complete'):
            self.assertIn(name,names)
        read=[detail for event,detail in events if event=='source_tool_result' and detail['tool']=='read_history']
        self.assertEqual(len(read),2);self.assertTrue(all(row['result']['full_case_read']for row in read))
        basis=next(detail for event,detail in events if event=='decision_basis')
        self.assertEqual(basis['source'],'model_assertion_unverified')

    def test_audit_failure_stops_before_any_provider_and_does_not_leak_error_text(self):
        calls=[]
        def audit(event,detail):raise OSError('credential in failing sink')
        out=Pipeline(self.r.corpus,lambda *args:calls.append(args),audit=audit).run(context())
        self.assertEqual(calls,[]);self.assertFalse(out['approved']);self.assertNotIn('credential',str(out))

    def test_unsupported_native_schema_stops_before_model_admission(self):
        c=native_context();c['candidate_contract']['schema']['properties']['reply']['unknownConstraint']='must not be ignored'
        with self.assertRaises(ResearchError):pack_context('research',c)

    def test_duplicate_keys_and_nonfinite_json_are_not_silently_normalized(self):
        from research_openai import strict_loads
        for text in ['{"reply":"bad","reply":"good"}','{"price":NaN}','{"a":{"x":1,"x":2}}']:
            with self.subTest(text=text),self.assertRaises(ValueError):strict_loads(text)

    def test_private_usage_view_is_scoped_to_owner_and_dialogue(self):
        ledger=UsageLedger();usage=dict(input_tokens=10,output_tokens=2,input_tokens_details=dict(cached_tokens=0,cache_write_tokens=0))
        for owner in ['one','another']:
            ledger.add(owner,'gpt-6.1-sol',usage,scope=dict(owner=owner,dialogue='same-id',role='research'))
        view=ledger.summary(owner='one',dialogue='same-id')
        self.assertEqual(view['calls'],1);self.assertNotIn('another',str(view));self.assertEqual(ledger.summary()['calls'],2)


if __name__=='__main__':unittest.main()
