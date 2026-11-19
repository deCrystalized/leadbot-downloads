"""Wire constraints complement rather than replace local semantic validation."""
import unittest
import json
import test_grounded_price111 as fixtures
from test_adult_presence102 import history


class ResponseSchema112Tests(unittest.TestCase):
    setUp = fixtures.GroundedPrice111Tests.setUp
    prepare = fixtures.GroundedPrice111Tests.prepare
    finish = fixtures.GroundedPrice111Tests.finish
    furniture = fixtures.GroundedPrice111Tests.furniture
    gas = fixtures.GroundedPrice111Tests.gas

    def test_neural_task_has_native_strict_schema_with_no_unknown_fields(self):
        out, task = self.prepare(self.furniture())
        wire=out['model_task']['response_format']
        self.assertEqual(wire['type'],'json_schema');self.assertTrue(wire['strict'])
        schema=wire['schema'];self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['required']),{'context_review','reply','needs_operator'})
        review=schema['properties']['context_review'];self.assertFalse(review['additionalProperties'])
        self.assertEqual(review['required'],task['output_contract']['context_review_fields'])
        self.assertNotIn('output_contract',review['properties']);self.assertNotIn('note_scope',review['properties'])

    def test_lengths_evidence_and_boolean_types_keep_existing_contract(self):
        out,_=self.prepare(self.furniture());s=out['model_task']['response_format']['schema']
        r=s['properties']['context_review']['properties']
        self.assertEqual(r['note']['maxLength'],200);self.assertEqual(r['last_intent']['maxLength'],200)
        self.assertEqual(r['evidence_ids']['maxItems'],8);self.assertEqual(r['evidence_ids']['minItems'],1)
        self.assertEqual(r['selected_step_fits']['type'],'boolean');self.assertEqual(s['properties']['reply']['maxLength'],280)
        self.assertEqual(s['properties']['needs_operator']['type'],'boolean')

    def test_literal_report_and_fixed_reply_are_bound_but_handoff_is_still_possible(self):
        out,task=self.prepare(self.gas(),'bt','Ремонт духовок','Саранск');s=out['model_task']['response_format']['schema']
        self.assertEqual(s['properties']['context_review']['properties']['latest_client_meaning']['enum'],[task['output_contract']['fixed_latest_client_meaning']])
        self.assertEqual(s['properties']['reply']['enum'],['',task['fixed_reply']])
        self.assertNotIn('enum',s['properties']['needs_operator'])
        self.assertNotIn('enum',s['properties']['context_review']['properties']['selected_step_fits'])

    def test_even_a_structurally_valid_claimed_search_still_fails_semantic_validation(self):
        out,task=self.prepare(self.gas(),'bt','Ремонт духовок','Саранск')
        final=self.finish(out,task,'Клиент ищет другого мастера с запчастями.','Нужно назвать специалиста.',intent='Газовая плита')
        self.assertFalse(final['reply']);self.assertIn('unconfirmed_third_party_request',final['validation'])

    def test_minor_condition_keeps_current_source_status_and_no_appointment_permission(self):
        out,task=self.prepare(history()[:4],'kp','Ремонт компьютеров','Тула')
        review=out['model_task']['response_format']['schema']['properties']['context_review']
        proof=review['properties']['adult_presence_review']
        self.assertIn('adult_presence_review',review['required']);self.assertFalse(proof['additionalProperties'])
        self.assertEqual(set(proof['required']),{'client_is_minor','status','evidence_id','appointment_confirmed'})
        self.assertEqual(proof['properties']['status']['enum'],[task['adult_presence_condition']['status']])
        self.assertEqual(proof['properties']['evidence_id']['enum'],[task['adult_presence_condition']['evidence_id']])
        self.assertEqual(proof['properties']['client_is_minor']['enum'],[True])
        self.assertEqual(proof['properties']['appointment_confirmed']['enum'],[False])

    def test_schema_size_is_bounded_without_copying_the_whole_history_into_enums(self):
        out,_=self.prepare(self.furniture());wire=out['model_task']['response_format']
        self.assertLess(len(json.dumps(wire,ensure_ascii=False)),24000)
        item=wire['schema']['properties']['context_review']['properties']['evidence_ids']['items']
        # A native Giga output cited ordinal "10" instead of a message ID.
        # Bound recent identities prevent it without copying a full-history enum.
        self.assertLessEqual(len(item['enum']),8)


if __name__=='__main__':unittest.main()
