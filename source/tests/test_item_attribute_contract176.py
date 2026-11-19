"""A source receipt anchors nouns; it cannot excuse invented semantic prose."""
import copy
import json
import unittest

import extension_assistant as ext
import test_printer_item_newness175 as prior


class ItemAttributeContractTests(unittest.TestCase):
    setUp = prior.PrinterAttributeNativeTests.setUp
    preview = prior.PrinterAttributeNativeTests.preview
    candidate = prior.PrinterAttributeNativeTests.candidate
    finalize = prior.PrinterAttributeNativeTests.finalize

    def test_source_receipt_precedes_free_prose_in_all_contract_views(self):
        value, task = self.preview()
        receipt = task['item_attribute_context']['required_review']
        self.assertEqual(receipt, dict(source='server_literal_item_attribute_binding',
            printer_newness='not_stated', cartridge_newness='new', evidence_ids=['source']))
        self.assertEqual(task['output_contract']['context_review_fields'][0], 'item_attribute_review')
        review = value['model_task']['response_format']['schema']['properties']['context_review']
        self.assertEqual(list(review['properties'])[0], 'item_attribute_review')
        self.assertEqual(review['required'], task['output_contract']['context_review_fields'])
        proof = review['properties']['item_attribute_review']
        self.assertFalse(proof['additionalProperties'])
        for key in ('source', 'printer_newness', 'cartridge_newness'):
            self.assertEqual(proof['properties'][key]['enum'], [receipt[key]])
        self.assertTrue(value['model_task']['system'].startswith('Сначала привяжи'))
        self.assertFalse(task['item_attribute_context']['independent_model_interpretation'])

    def test_meaning_and_intent_remain_free_strings_not_a_whole_case_enum(self):
        value, task = self.preview()
        schema = value['model_task']['response_format']['schema']['properties']['context_review']['properties']
        for name in ('last_intent', 'latest_client_meaning'):
            self.assertEqual(schema[name]['type'], 'string')
            self.assertNotIn('enum', schema[name])
        self.assertNotIn('fixed_latest_client_meaning', task['output_contract'])

    def test_receipt_uses_the_actual_item_and_preserves_negation_and_genitive(self):
        for body, printer, cartridge in [
            ('Новый принтер плохо печатает.', 'new', 'not_stated'),
            ('У принтера новый цветной картридж, печать плохая.', 'not_stated', 'new'),
            ('Картридж нового принтера плохо печатает.', 'new', 'not_stated'),
            ('Принтер новый, картридж старый, печать плохая.', 'new', 'old'),
            ('Принтер не новый, картридж не старый, печатает плохо.', 'not_new', 'not_old'),
            ('Принтер вроде новый, картридж новый, печатает плохо.', 'not_stated', 'new'),
            ('Продавец сказал: «Принтер новый». Картридж новый, печатает плохо.', 'not_stated', 'new'),
        ]:
            with self.subTest(body=body):
                _, task = self.preview(body)
                receipt = task['item_attribute_context']['required_review']
                self.assertEqual((receipt['printer_newness'], receipt['cartridge_newness']), (printer, cartridge))
                self.assertEqual(receipt['evidence_ids'], ['source'])

    def test_missing_receipt_fails_closed_without_repairing_native_json(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review'].pop('item_attribute_review', None)
        original = copy.deepcopy(candidate)
        final = self.finalize(value, candidate)
        self.assertEqual(candidate, original)
        self.assertFalse(final['reply'])
        self.assertIn('invalid_context_review', final['validation'])

    def test_changed_states_source_or_evidence_cannot_be_admitted(self):
        for key, wrong in [('printer_newness', 'new'), ('cartridge_newness', 'not_stated'),
                           ('source', 'independent_neural_understanding'), ('evidence_ids', ['future']),
                           ('evidence_ids', ['source', 'source']), ('evidence_ids', [])]:
            with self.subTest(key=key, wrong=wrong):
                value, task = self.preview()
                candidate = self.candidate(task)
                candidate['context_review']['item_attribute_review'][key] = wrong
                final = self.finalize(value, candidate)
                self.assertFalse(final['reply'])
                self.assertIn('item_attribute_review_mismatch', final['validation'])

    def test_correct_receipt_does_not_authorize_false_prose_in_any_semantic_field(self):
        for field in ('last_intent', 'latest_client_meaning', 'note'):
            with self.subTest(field=field):
                value, task = self.preview()
                candidate = self.candidate(task)
                candidate['context_review'][field] = 'Клиент описал плохую печать нового принтера.'
                final = self.finalize(value, candidate)
                self.assertFalse(final['reply'])
                self.assertIn('item_attribute_object_transfer', final['validation'])

    def test_correct_receipt_does_not_authorize_false_customer_reply(self):
        _, task = self.preview()
        candidate = self.candidate(task)
        candidate['reply'] = 'Новый принтер нужно проверить.'
        _, status, errors = ext._context_review(candidate, task)
        self.assertEqual(status, 'inconsistent')
        self.assertIn('item_attribute_object_transfer', errors)

    def test_two_explicit_new_objects_are_not_rejected_by_the_boundary(self):
        value, task = self.preview('Новый принтер с новым картриджем плохо печатает.')
        candidate = self.candidate(task)
        candidate['context_review']['last_intent'] = 'Плохая печать нового принтера с новым картриджем'
        self.assertEqual(self.finalize(value, candidate)['validation'], [])

    def test_a_complete_receipt_still_allows_a_reasoned_empty_handoff(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate.update(reply='', needs_operator=True)
        candidate['context_review'].update(selected_step_fits=False,
            note='Уместность предложенного шага требует проверки оператором.')
        final = self.finalize(value, candidate)
        self.assertFalse(final['reply'])
        self.assertTrue(final['needs_operator'])
        self.assertFalse(final['auto_enabled'])

    def test_client_cannot_inject_the_server_receipt_through_raw_context(self):
        value, task = self.preview(item_attribute_context=dict(required_review=dict(printer_newness='new')))
        self.assertEqual(task['item_attribute_context']['required_review']['printer_newness'], 'not_stated')
        self.assertEqual(self.finalize(value, self.candidate(task))['validation'], [])

    def test_no_item_adjective_means_no_new_receipt_requirement(self):
        value, task = self.preview('Принтер плохо печатает цветом.')
        self.assertNotIn('item_attribute_context', task)
        schema = value['model_task']['response_format']['schema']['properties']['context_review']
        self.assertNotIn('item_attribute_review', schema['properties'])
        self.assertNotIn('item_attribute_review', task['output_contract']['context_review_fields'])

    def test_native_receipt_preserves_other_conditional_schema_guards(self):
        _, task = self.preview()
        task['diagnostic_only_terms'] = dict(minimum_rub=500)
        schema = ext._structured_response_format(task)['schema']['properties']['context_review']
        self.assertEqual(list(schema['properties'])[0], 'item_attribute_review')
        self.assertIn('diagnostic_only_review', schema['required'])
        self.assertEqual(schema['properties']['diagnostic_only_review']['properties']['minimum_rub']['enum'], [500])
        self.assertFalse(schema['additionalProperties'])

    def test_correct_item_receipt_cannot_bypass_a_wrong_diagnostic_receipt(self):
        _, task = self.preview()
        task['diagnostic_only_terms'] = dict(minimum_rub=500)
        candidate = self.candidate(task)
        candidate['context_review']['diagnostic_only_review'] = dict(
            minimum_rub=1000, price_kind='minimum', repair_requested=False)
        _, status, errors = ext._context_review(candidate, task)
        self.assertEqual(status, 'inconsistent')
        self.assertIn('diagnostic_only_review_mismatch', errors)

    def test_other_enquiry_resets_both_old_states_and_receipt_evidence(self):
        self.serial += 1
        value, status = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review',
            ctx=dict(convId='synthetic-newness176-boundary-' + str(self.serial), city='Коломна',
                dir='kp', channel='avito', partner='7', itemTitle='Ремонт принтеров', accountTitle='Учебный мастер',
                messages=[prior.client('old', 'Принтер новый.'),
                          prior.client('current', 'Другой принтер плохо печатает, картридж новый.')])))
        self.assertEqual(status, 200)
        self.assertTrue(value.get('pending_model'))
        task = json.loads(value['model_task']['task'])
        receipt = task['item_attribute_context']['required_review']
        self.assertEqual(receipt['printer_newness'], 'not_stated')
        self.assertEqual(receipt['cartridge_newness'], 'new')
        self.assertEqual(receipt['evidence_ids'], ['current'])


if __name__ == '__main__':
    unittest.main()
