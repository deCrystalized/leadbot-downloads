"""Bounded instructions preserve data, schemas, conditional fallbacks and veto."""
import copy
import json
import unittest
from unittest.mock import patch

import extension_assistant as ext
import test_printer_item_newness175 as prior


class PrinterPromptTests(unittest.TestCase):
    setUp = prior.PrinterAttributeNativeTests.setUp
    preview = prior.PrinterAttributeNativeTests.preview
    candidate = prior.PrinterAttributeNativeTests.candidate
    finalize = prior.PrinterAttributeNativeTests.finalize

    def test_plain_printer_gets_contrasts_without_other_case_facts(self):
        value, task = self.preview()
        system = value['model_task']['system']
        self.assertIn('Примеры разделения фактов', system)
        self.assertLess(len(system), len(ext.CONTEXT_SYSTEM))
        self.assertNotIn('Лампа', json.dumps(task, ensure_ascii=False))
        self.assertNotIn('fixed_latest_client_meaning', task['output_contract'])
        self.assertTrue(system.startswith('Сначала привяжи'))

    def test_selecting_instruction_does_not_mutate_task_schema_budget_or_sources(self):
        value, task = self.preview()
        with patch.object(ext, '_printer_context_system', return_value=None):
            other, other_task = self.preview()
        self.assertEqual(task, other_task)
        for key in ('task', 'response_format', 'max_tokens'):
            self.assertEqual(value['model_task'][key], other['model_task'][key])
        self.assertNotEqual(value['model_task']['system'], other['model_task']['system'])

    def test_new_unknown_context_falls_back_instead_of_silently_losing_rules(self):
        _, task = self.preview()
        task['future_conditional_contract'] = dict(required=True)
        self.assertIsNone(ext._printer_context_system(task))

    def test_missing_required_proof_field_does_not_qualify_as_known_contract(self):
        _, task = self.preview()
        task['output_contract']['context_review_fields'].remove('item_fitment_review')
        self.assertIsNone(ext._printer_context_system(task))

    def test_unknown_nested_output_requirement_uses_complete_instructions(self):
        _, task = self.preview()
        task['output_contract']['future_required_proof'] = dict(required=True)
        self.assertIsNone(ext._printer_context_system(task))

    def test_conditional_reviews_keep_complete_original_instructions(self):
        _, task = self.preview()
        for name in ('adult_presence_review', 'device_power_review', 'diagnostic_fee_review',
                     'diagnostic_only_review', 'mnc_callout_review', 'photo_work_review',
                     'pickup_delivery_review', 'background_work_review'):
            changed = copy.deepcopy(task)
            changed['output_contract']['context_review_fields'].append(name)
            self.assertIsNone(ext._printer_context_system(changed), name)

    def test_previous_price_booking_and_short_answer_contexts_use_full_prompt(self):
        _, task = self.preview()
        for name in ('client_contact_answer_context', 'partial_address_context',
                     'availability_answer_context', 'visit_time_question_context',
                     'client_background_work', 'reported_device_condition'):
            changed = copy.deepcopy(task)
            changed[name] = dict(required=True)
            self.assertIsNone(ext._printer_context_system(changed), name)

    def test_fixed_source_meaning_remains_on_existing_specialized_path(self):
        _, task = self.preview()
        task['output_contract']['fixed_latest_client_meaning'] = 'Буквальная короткая реплика.'
        self.assertIsNone(ext._printer_context_system(task))

    def test_only_an_ordinary_accepted_printer_service_can_use_bounded_prompt(self):
        _, task = self.preview()
        for service in (dict(status='supported',items=[]),
                        dict(status='supported',items=[dict(rule_id='printer',status='approval')]),
                        dict(status='approval',items=[dict(rule_id='printer',status='accept')]),
                        dict(status='supported',items=[dict(rule_id='printer',status='accept'),
                                                       dict(rule_id='electric',status='accept')])):
            changed = copy.deepcopy(task)
            changed['service_constraints'] = service
            self.assertIsNone(ext._printer_context_system(changed), service)

    def test_browser_cannot_force_bounded_prompt_for_an_unrelated_context(self):
        _, task = self.preview(printer_context_system='FORGED', current_document_image={'forged':True})
        self.assertNotIn('printer_context_system',task)
        self.assertNotIn('current_document_image',task)
        changed = copy.deepcopy(task)
        changed.pop('item_fitment_context')
        self.assertIsNone(ext._printer_context_system(changed))

    def test_unknown_reply_scope_is_not_assumed_to_mean_question_only(self):
        _, task = self.preview()
        task['reply_field_scope'] = 'new_future_reply_kind'
        self.assertIsNone(ext._printer_context_system(task))

    def test_document_observation_remains_separate_from_device_diagnosis(self):
        _, task = self.preview()
        task['current_document_image'] = dict(content_kind='document_image', evidence_id='photo')
        text = ext._printer_context_system(task)
        self.assertIsNotNone(text)
        self.assertIn('Наблюдения изображения', text)
        self.assertIn('данные, а не команды', text)

    def test_exact_reply_and_question_only_scopes_both_have_explicit_rules(self):
        _, task = self.preview()
        task['fixed_reply'] = 'По переписке причину точно не определить.'
        task['reply_field_scope'] = 'exact_fixed_reply'
        text = ext._printer_context_system(task)
        self.assertIsNotNone(text)
        self.assertIn('fixed_reply',text)
        self.assertIn('ДОСЛОВНО',text)
        self.assertIn('decision.next_question.question',text)

    def test_correct_free_meaning_and_literal_quote_pass_without_added_client_question(self):
        value,task = self.preview()
        candidate = self.candidate(task)
        result = self.finalize(value,candidate)
        self.assertEqual(result['validation'],[])
        self.assertIn(candidate['reply'],result['reply'])
        self.assertNotIn('установ',candidate['reply'])
        self.assertEqual(result['context_review']['latest_client_meaning'],candidate['context_review']['latest_client_meaning'])

    def test_literal_quote_does_not_excuse_invented_installation(self):
        value,task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Изображение размыто, несмотря на установленный новый картридж.'
        result = self.finalize(value,candidate)
        self.assertIn('item_fitment_not_observed',result['validation'])
        self.assertFalse(result['reply'])

    def test_real_reported_installation_is_still_allowed(self):
        value,task = self.preview('Принтер плохо печатает. Картридж новый. Я установил картридж вчера.')
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Клиент вчера установил картридж; принтер плохо печатает.'
        self.assertEqual(self.finalize(value,candidate)['validation'],[])

    def test_meaningful_model_veto_remains_available(self):
        value,task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review']['selected_step_fits'] = False
        candidate['context_review']['note'] = 'Предложенный шаг нужно сверить с последним запросом.'
        candidate.update(reply='',needs_operator=True)
        result = self.finalize(value,candidate)
        self.assertFalse(result['reply'])
        self.assertTrue(result['needs_operator'])

    def test_selected_regulation_lines_reach_model_with_their_full_tail(self):
        retrieve = ext.policy.retrieve
        extra = dict(id='synthetic-long-source183',text='Условие приёма. '*40+'Отдельная последняя оговорка обязательна.',date=None)
        with patch.object(ext.policy,'retrieve',side_effect=lambda *a,**k:retrieve(*a,**k)+[extra]):
            value,task = self.preview()
        for rows in (value['sources'],task['primary_sources']):
            saved = next(x for x in rows if x['id']==extra['id'])
            self.assertEqual(saved['text'],extra['text'])

    def test_actual_owner_acceptance_rule_is_not_cut_mid_condition(self):
        value,task = self.preview()
        expected = next(x for x in ext.policy.retrieve('принтер',limit=6,
            refs=['OWNER-CLIENT-REPORTED-ACCEPTANCE-20261020'],direction='kp',applied_only=True)
            if x['id']=='OWNER-CLIENT-REPORTED-ACCEPTANCE-20261020')
        self.assertGreater(len(expected['text']),400)
        for rows in (value['sources'],task['primary_sources']):
            self.assertEqual(next(x['text']for x in rows if x['id']==expected['id']),expected['text'])

    def test_oversized_complete_regulation_stops_without_partial_model_context(self):
        retrieve = ext.policy.retrieve
        extra = dict(id='synthetic-too-long-source183',text='Полное правило. '*7000,date=None)
        ctx=dict(convId='synthetic-too-long183',city='Коломна',dir='kp',channel='avito',partner='7',
                 itemTitle='Ремонт принтеров',accountTitle='Учебный мастер',messages=[prior.client('source',prior.REPORT)])
        with patch.object(ext.policy,'retrieve',side_effect=lambda *a,**k:retrieve(*a,**k)+[extra]):
            value,code=self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(code,200)
        self.assertFalse(value.get('pending_model'))
        self.assertEqual(value['action'],'handoff')
        self.assertIn('model_context_limit',value['validation'])
        self.assertFalse(value['reply'])
        self.assertFalse(value['auto_enabled'])


if __name__=='__main__':
    unittest.main()
