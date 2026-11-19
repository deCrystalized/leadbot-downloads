import copy
import json
import unittest

from api_costs import UsageLedger
from research_openai import ResponsesTransport, _schema
from research_pipeline import pack_context, Pipeline
import test_research_pipeline218 as fixtures


class SourceReferences209Tests(unittest.TestCase):
    def test_catalog_distinguishes_current_client_from_staff_and_service(self):
        current = fixtures.context()
        current['messages'].append(dict(id='sys',direction='system',sender_type='system',body='Назначен'))
        value = pack_context('research',current,profile='sol_only')
        self.assertEqual(value['input']['source_references'],['current:c1','current:c2'])
        instruction = json.loads(value['instructions'])['source_reference_contract']
        self.assertIn('current:',instruction);self.assertIn('rule:',instruction);self.assertIn('history:',instruction)
        self.assertIn('БЕЗ префикса current:',instruction)

    def test_catalog_includes_read_sources_but_never_search_hits(self):
        evidence=dict(rules=[dict(id='R1')],histories=[dict(case_id='read-case')],
                      last_tool_result=dict(hits=[dict(case_id='unread-case')]))
        saved=copy.deepcopy(evidence)
        value=pack_context('review',fixtures.context(),evidence,profile='sol_only')
        self.assertEqual(value['input']['source_references'],['current:c1','current:c2','history:read-case','rule:R1'])
        self.assertEqual(evidence,saved)

    def test_both_schemas_explain_references_without_forcing_meaning_or_enum(self):
        for role in ('research','review'):
            schema=_schema(role)
            basis=schema['properties']['basis']
            self.assertIn('current:',basis['description']);self.assertNotIn('enum',basis['items'])
        schema=_schema('research')
        self.assertIn('Bare',schema['properties']['evidence_ids']['description'])
        self.assertIn('rule:',schema['properties']['claims']['items']['properties']['basis']['description'])

    def test_actual_wire_contains_reference_catalog_without_duplicating_timeline(self):
        captured=[]
        def request(payload,timeout):captured.append(payload);raise TimeoutError()
        current=fixtures.context();packet=pack_context('research',current,profile='sol_only')
        with self.assertRaises(ValueError):ResponsesTransport(request,UsageLedger())('research',packet,())
        dynamic=json.loads(captured[0]['input'][-1]['content'][0]['text'])
        self.assertEqual(dynamic['source_references'],['current:c1','current:c2'])
        self.assertEqual(dynamic['current']['messages'],current['messages'])

    def test_original_actual_failure_shape_is_not_normalized_into_accepted_refs(self):
        f=fixtures.ResearchTests();f.setUp();self.addCleanup(f.tmp.cleanup)
        seq=f.sequence();draft=seq[-2]
        draft['basis']=['Клиент спрашивает о покупке крепежа (c2), ответ в R1.']
        draft['claims'][0]['basis']=['c2','R1']
        out=Pipeline(f.corpus,lambda *args:seq.pop(0),profile='sol_only').run(fixtures.context())
        self.assertFalse(out['approved']);self.assertEqual(len(out['trace']),5)
        self.assertEqual(out['trace'][-1]['response']['claims'][0]['basis'],['c2','R1'])

    def test_correct_outer_refs_do_not_allow_bare_claim_refs_or_unread_rules(self):
        for bad in (['c2'],['rule:UNREAD']):
            f=fixtures.ResearchTests();f.setUp();self.addCleanup(f.tmp.cleanup)
            seq=f.sequence();seq[-2]['claims'][0]['basis']=bad
            out=Pipeline(f.corpus,lambda *args:seq.pop(0),profile='sol_only').run(fixtures.context())
            self.assertFalse(out['approved'])


if __name__=='__main__':unittest.main()
