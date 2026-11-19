"""A literal event receipt precedes prose without replacing model interpretation."""
import copy
import json
import unittest

import extension_assistant as ext
import test_printer_item_newness175 as prior


class ItemFitmentContractTests(unittest.TestCase):
    setUp = prior.PrinterAttributeNativeTests.setUp
    preview = prior.PrinterAttributeNativeTests.preview
    candidate = prior.PrinterAttributeNativeTests.candidate
    finalize = prior.PrinterAttributeNativeTests.finalize

    def test_empty_events_are_explicit_not_an_installation_inference(self):
        value, task = self.preview()
        proof = task['item_fitment_context']['required_review']
        self.assertEqual(proof, dict(source='server_literal_client_item_events', events=[],
            performed_event_reported=False, work_execution_verified=False))
        self.assertFalse(task['item_fitment_context']['independent_model_interpretation'])
        self.assertEqual(self.finalize(value, self.candidate(task))['validation'], [])

    def test_receipts_precede_free_fields_with_existing_attribute_receipt_first(self):
        value, task = self.preview()
        fields = task['output_contract']['context_review_fields']
        self.assertEqual(fields[:2], ['item_attribute_review', 'item_fitment_review'])
        wire = value['model_task']['response_format']['schema']['properties']['context_review']
        self.assertEqual(list(wire['properties']), fields)
        self.assertEqual(wire['required'], fields)
        system = value['model_task']['system']
        self.assertIn('"item_fitment_review":', system)
        self.assertIn('не самостоятельное понимание', system)
        self.assertNotIn('enum', wire['properties']['last_intent'])
        self.assertNotIn('enum', wire['properties']['latest_client_meaning'])

    def test_native_schema_has_closed_event_shape_and_no_empty_enum(self):
        value, _ = self.preview()
        schema = value['model_task']['response_format']['schema']['properties']['context_review']
        receipt = schema['properties']['item_fitment_review']
        self.assertFalse(receipt['additionalProperties'])
        events = receipt['properties']['events']
        self.assertEqual((events['minItems'], events['maxItems']), (0, 0))
        self.assertEqual(events['items']['required'], ['object', 'event', 'mode', 'actor', 'timing', 'evidence_id'])
        self.assertFalse(events['items']['additionalProperties'])
        def walk(node):
            if isinstance(node, dict):
                if 'enum' in node:
                    self.assertTrue(node['enum'])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(receipt)

    def test_no_age_report_keeps_event_receipt_first_without_fabricating_an_age_receipt(self):
        value, task = self.preview('Принтер плохо печатает цветом.')
        self.assertNotIn('item_attribute_context', task)
        self.assertEqual(task['output_contract']['context_review_fields'][0], 'item_fitment_review')
        self.assertNotIn('item_attribute_review', task['output_contract']['context_review_fields'])
        candidate = self.candidate(task)
        # This positive contract case has no cartridge-age statement. The
        # general175 factory's new-cartridge phrase belongs to its other cases.
        candidate['context_review']['latest_client_meaning'] = 'Клиент описал плохую цветную печать.'
        self.assertEqual(self.finalize(value, candidate)['validation'], [])

    def test_missing_receipt_is_rejected_without_native_json_repair(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review'].pop('item_fitment_review')
        original = copy.deepcopy(candidate)
        final = self.finalize(value, candidate)
        self.assertFalse(final['reply'])
        self.assertIn('invalid_context_review', final['validation'])
        self.assertEqual(candidate, original)

    def test_false_receipt_cannot_authorize_events_or_execution(self):
        for key, wrong in [('source', 'independent_model_understanding'),
                           ('performed_event_reported', True), ('work_execution_verified', True),
                           ('events', [dict(object='cartridge', event='fitment')]),
                           ('work_execution_verified', 0)]:
            with self.subTest(key=key, wrong=wrong):
                value, task = self.preview()
                candidate = self.candidate(task)
                candidate['context_review']['item_fitment_review'][key] = wrong
                final = self.finalize(value, candidate)
                self.assertFalse(final['reply'])
                self.assertIn('item_fitment_review_mismatch', final['validation'])

    def test_correct_receipt_does_not_excuse_false_free_fields_or_reply(self):
        for field in ['last_intent', 'latest_client_meaning', 'note', 'reply']:
            with self.subTest(field=field):
                _, task = self.preview()
                candidate = self.candidate(task)
                target = candidate if field == 'reply' else candidate['context_review']
                target[field] = 'Несмотря на установленный новый картридж, принтер плохо печатает.'
                self.assertIn('item_fitment_not_observed', ext._context_review(candidate, task)[2])

    def test_reported_replacement_keeps_unspecified_actor_time_and_id(self):
        _, task = self.preview('Принтер плохо печатает. Картриджи поменяли совсем недавно.')
        proof = task['item_fitment_context']['required_review']
        self.assertTrue(proof['performed_event_reported'])
        self.assertFalse(proof['work_execution_verified'])
        self.assertEqual(proof['events'], [dict(object='cartridge', event='replacement', mode='asserted',
            actor='unspecified', timing='недавно', evidence_id='source')])
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Картриджи недавно заменили.'
        self.assertEqual(ext._context_review(candidate, task)[2], [])

    def test_event_source_actor_mode_and_time_cannot_be_changed(self):
        for key, wrong in [('object', 'printer'), ('actor', 'service'), ('mode', 'asserted'),
                           ('timing', 'вчера'), ('evidence_id', 'future')]:
            with self.subTest(key=key):
                _, task = self.preview('Принтер плохо печатает. Если картридж установлен, что проверить?')
                candidate = self.candidate(task)
                candidate['context_review']['item_fitment_review']['events'][0][key] = wrong
                self.assertIn('item_fitment_review_mismatch', ext._context_review(candidate, task)[2])

    def test_nonassertive_events_never_acknowledge_positive_performed_report(self):
        for text in ['Нужно установить картридж.', 'Пробовал установить картридж.',
                     'Картридж не установлен.', 'Картридж установлен?',
                     'Возможно, картридж установлен.', 'Продавец сказал: «Картридж установлен».']:
            with self.subTest(text=text):
                _, task = self.preview('Принтер плохо печатает. ' + text)
                proof = task['item_fitment_context']['required_review']
                self.assertTrue(proof['events'])
                self.assertFalse(proof['performed_event_reported'])
                self.assertFalse(proof['work_execution_verified'])

    def test_two_objects_keep_two_separate_source_events(self):
        _, task = self.preview('Принтер плохо печатает цветом. Принтер установлен. Картриджи поменяли совсем недавно.')
        proof = task['item_fitment_context']['required_review']
        self.assertEqual([(r['object'], r['event']) for r in proof['events']],
                         [('printer', 'fitment'), ('cartridge', 'replacement')])

    def test_raw_context_cannot_inject_a_performed_event(self):
        value, task = self.preview(item_fitment_context=dict(required_review=dict(performed_event_reported=True)))
        self.assertEqual(task['item_fitment_context']['required_review']['events'], [])
        self.assertEqual(self.finalize(value, self.candidate(task))['validation'], [])

    def test_other_conditional_review_is_still_required(self):
        _, task = self.preview()
        task['diagnostic_only_terms'] = dict(minimum_rub=500)
        schema = ext._structured_response_format(task)['schema']['properties']['context_review']
        self.assertEqual(list(schema['properties'])[:2], ['item_attribute_review', 'item_fitment_review'])
        self.assertIn('diagnostic_only_review', schema['required'])
        candidate = self.candidate(task)
        candidate['context_review']['diagnostic_only_review'] = dict(
            minimum_rub=1000, price_kind='minimum', repair_requested=False)
        self.assertIn('diagnostic_only_review_mismatch', ext._context_review(candidate, task)[2])

    def test_no_extra_required_client_question_or_whole_case_literal(self):
        _, task = self.preview()
        self.assertEqual(task['decision']['next_question']['kind'], 'model')
        self.assertNotIn('fixed_latest_client_meaning', task['output_contract'])
        self.assertNotIn('установ', task['proposed_reply'].lower())

    def test_reasoned_veto_keeps_receipt_and_empty_reply(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate.update(reply='', needs_operator=True)
        candidate['context_review'].update(selected_step_fits=False, note='Нужна проверка уместности шага.')
        result = self.finalize(value, candidate)
        self.assertFalse(result['reply'])
        self.assertTrue(result['needs_operator'])

    def test_future_staff_and_old_enquiry_events_do_not_enter_receipt(self):
        self.serial += 1
        value, status = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review',
            ctx=dict(convId='synthetic-fitment178-boundary-' + str(self.serial), city='Коломна', dir='kp',
                channel='avito', partner='7', itemTitle='Ремонт принтеров', accountTitle='Учебный мастер',
                messages=[prior.client('old', 'Картридж установлен.'),
                    prior.staff('staff', 'Мы заменили картридж.'),
                    dict(id='system', direction='in', sender_type='avito', body='Картридж установлен.'),
                    prior.client('current', 'Другой принтер плохо печатает цветом, картридж новый.')])) )
        self.assertEqual(status, 200)
        self.assertTrue(value.get('pending_model'))
        task = json.loads(value['model_task']['task'])
        self.assertEqual(task['item_fitment_context']['required_review']['events'], [])
        self.assertEqual(task['item_attribute_context']['required_review']['evidence_ids'], ['current'])


if __name__ == '__main__':
    unittest.main()
