"""Reviewer coverage indexes must be integers, not Python-equal bools/floats."""
import json
import unittest
import test_research_pipeline218 as pipelines
import test_research_transport218 as transports
from research_openai import TransportError


class ReviewTypes252Tests(unittest.TestCase):
    def pipeline(self,index):
        f=pipelines.ResearchTests();f.setUp();self.addCleanup(f.doCleanups)
        seq=f.sequence();seq[-1]['checked_claims']=[index]
        result,calls=f.run_sequence(seq)
        self.assertFalse(result['approved'],result)
        self.assertEqual(len(calls),6)
        self.assertEqual(result['failure_kind'],'technical')

    def test_boolean_false_is_not_claim_index_zero(self):self.pipeline(False)

    def test_float_zero_is_not_claim_index_zero(self):self.pipeline(0.0)

    def test_contradictory_approval_and_violation_fields_are_a_contract_error(self):
        for changes in ({'approved':False,'violations':[]},{'approved':True,'violations':['Не подтверждено']}):
            f=pipelines.ResearchTests();f.setUp();self.addCleanup(f.doCleanups)
            seq=f.sequence();seq[-1].update(changes)
            result,calls=f.run_sequence(seq)
            self.assertFalse(result['approved'])
            self.assertEqual(result['failure_kind'],'technical')
            self.assertEqual(len(calls),6)

    def transport(self,changes):
        f=transports.TransportTests();f.setUp()
        value=dict(kind='review',approved=True,violations=[],checked_claims=[0],basis=['rule:R1'])
        value.update(changes)
        f.response.update(model='gpt-6-astra',output=[dict(type='message',role='assistant',status='completed',
            content=[dict(type='output_text',text=json.dumps(value))])])
        with self.assertRaises(TransportError):f.call('review')
        self.assertEqual(len(f.payloads),1)
        self.assertEqual(f.ledger.summary()['calls'],1)

    def test_transport_does_not_trust_provider_strict_mode_for_invalid_index_type(self):
        self.transport({'checked_claims':[False]})

    def test_unadvertised_review_fields_are_not_accepted_as_a_strict_stage_conclusion(self):
        self.transport({'self_approved':True})
