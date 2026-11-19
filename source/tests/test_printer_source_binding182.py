"""Literal entity/property/relation evidence, independently selected by the model."""
import copy
import json
import unittest

import contact_facts as facts
import extension_assistant as ext
import test_printer_item_newness175 as prior


class ItemPropertyBindingTests(unittest.TestCase):
    def evidence(self, text):
        return facts.printer_item_newness([prior.client('source', text)])

    def test_consumable_newness_has_its_own_subject_in_both_orders(self):
        for text, subject in [('Новая цветная краска.', 'paint'), ('Краска новая.', 'paint'),
                              ('Новые чернила.', 'ink'), ('Чернила совсем новые.', 'ink'),
                              ('Новый тонер.', 'toner'), ('Тонер новый.', 'toner'),
                              ('Новая головка.', 'printhead'), ('Новый барабан.', 'drum')]:
            with self.subTest(text=text):
                value = self.evidence(text)
                self.assertIsNotNone(value)
                self.assertEqual(value['states'][subject], 'new')
                self.assertEqual(value['states']['cartridge'], 'not_stated')
                self.assertEqual(value['states']['printer'], 'not_stated')

    def test_genitive_and_neighbour_nouns_keep_the_actual_attribute_owner(self):
        for text, subject in [('Картридж новой краски.', 'paint'),
                              ('Картридж новых чернил.', 'ink'),
                              ('Принтер с новой головкой.', 'printhead'),
                              ('Краска нового картриджа.', 'cartridge')]:
            value = self.evidence(text)
            self.assertEqual(value['states'][subject], 'new', text)
            others = {k:v for k,v in value['states'].items() if k != subject}
            self.assertTrue(all(v == 'not_stated' for v in others.values()), text)

    def test_shared_plural_adjective_covers_each_explicit_conjoined_noun(self):
        for text in ['Новые принтер и картридж.', 'Принтер и картридж новые.']:
            self.assertEqual(self.evidence(text)['states'], dict(printer='new',cartridge='new'))
        value = self.evidence('Картридж и чернила новые.')
        self.assertEqual((value['states']['cartridge'],value['states']['ink']), ('new','new'))

    def test_distinct_properties_are_not_overridden_by_a_neighbour(self):
        value = self.evidence('Новый картридж, старая краска и новый тонер.')
        self.assertEqual((value['states']['cartridge'],value['states']['paint'],value['states']['toner']),
                         ('new','old','new'))
        value = self.evidence('Новый принтер и старый картридж.')
        self.assertEqual(value['states'], dict(printer='new',cartridge='old'))

    def test_roles_modality_and_new_enquiry_apply_to_consumables(self):
        for text in ['Краска новая?', 'Возможно, краска новая.', 'Не уверен, что краска новая.',
                     'Не знаю, краска новая.', 'Может, краска новая.', 'Если краска новая, почему полосы?',
                     'Хочу новую краску.', 'Мастер сказал: «Краска новая».']:
            value = self.evidence(text)
            self.assertIsNotNone(value, text)
            self.assertEqual(value['states']['paint'], 'not_stated', text)
        value = self.evidence('Краска не новая.')
        self.assertEqual(value['states']['paint'], 'not_new')
        self.assertIsNone(facts.printer_item_newness([prior.staff('s','Краска новая.')]))
        value = facts.printer_item_newness([prior.client('old','Краска новая.'),
            prior.client('next','Новая заявка: картридж новый.')])
        self.assertNotEqual(value['states'].get('paint'), 'new')

    def test_literal_spans_and_source_ids_are_preserved(self):
        text = 'У принтера новая цветная краска и старый картридж.'
        value = self.evidence(text)
        for row in value['evidence']:
            self.assertEqual(row['literal'],text[row['start']:row['end']])
            self.assertEqual((row['message_id'],row['quote']),('source',text))


class CartridgeRelationTests(unittest.TestCase):
    def evidence(self, text):
        return facts.printer_item_fitment([prior.client('source',text)])

    def test_on_and_with_cartridge_express_medium_not_installation(self):
        for text in ['Печать на новом картридже размытая.', 'Печатаю на новом картридже.',
                     'На старом картридже я печатал.', 'Принтер печатает с новым картриджем.',
                     'Печать с новыми картриджами размытая.']:
            rows = self.evidence(text)
            self.assertTrue(rows,text)
            self.assertTrue(all(x['object']=='cartridge' and x['event'] in ('use','current_use','past_use') for x in rows),text)
            self.assertFalse(facts.unsupported_printer_fitment(text,rows),text)
            self.assertTrue(facts.unsupported_printer_fitment('Картридж установлен.',rows),text)

    def test_newness_alone_does_not_support_colloquial_medium(self):
        self.assertTrue(facts.unsupported_printer_fitment('Плохая цветная печать на новом картридже.',self.evidence(prior.REPORT)))

    def test_printed_surface_or_label_is_not_use_as_printing_medium(self):
        for text in ['Печатаю этикетку на новом картридже.', 'Печать маркировки на картридже.',
                     'Надпись напечатана на картридже.', 'Печать на поверхности картриджа.',
                     'Картридж для печати новый.']:
            self.assertEqual(self.evidence(text),[],text)
        self.assertTrue(self.evidence('Печатаю этикетку на новом принтере.'))
        self.assertTrue(self.evidence('Печатаю этикетку новым картриджем.'))

    def test_nonassertive_relations_do_not_authorize_asserted_use(self):
        for text in ['Печатаете на новом картридже?', 'Возможно, печать на новом картридже размыта.',
                     'Если печатать на новом картридже, будут полосы.', 'Буду печатать на новом картридже.',
                     'Не печатаю на новом картридже.', 'Пытался печатать на новом картридже.',
                     'Мастер сказал: «Печать на новом картридже размыта».']:
            rows = self.evidence(text)
            self.assertTrue(rows,text)
            self.assertTrue(facts.unsupported_printer_fitment('Печать на новом картридже размытая.',rows),text)

    def test_other_cartridge_and_past_time_do_not_supply_new_current_use(self):
        rows=self.evidence('Вчера печатал на старом чёрном картридже. Цветной картридж новый.')
        self.assertTrue(facts.unsupported_printer_fitment('Печатаю на новом цветном картридже.',rows))
        self.assertFalse(facts.unsupported_printer_fitment('Печать на старом чёрном картридже.',rows))


class LiteralSourceNativeTests(unittest.TestCase):
    setUp=prior.PrinterAttributeNativeTests.setUp
    preview=prior.PrinterAttributeNativeTests.preview
    candidate=prior.PrinterAttributeNativeTests.candidate
    finalize=prior.PrinterAttributeNativeTests.finalize

    def test_new_ink_claim_rejected_even_with_suitable_reply_and_valid_evidence(self):
        value,task=self.preview()
        candidate=self.candidate(task)
        candidate['context_review']['last_intent']='Консультация по принтеру с новой цветной краской.'
        original=copy.deepcopy(candidate)
        result=self.finalize(value,candidate)
        self.assertEqual(candidate,original)
        self.assertIn('item_attribute_object_transfer',result['validation'])
        self.assertFalse(result['reply'])

    def test_all_free_fields_cannot_transfer_cartridge_newness_to_supplies(self):
        _,task=self.preview()
        for field in ['last_intent','latest_client_meaning','note','reply']:
            for claim in ['Новая цветная краска.', 'Новые чернила.', 'Новый тонер.', 'Новая головка.']:
                candidate=self.candidate(task)
                (candidate if field=='reply' else candidate['context_review'])[field]=claim
                self.assertIn('item_attribute_object_transfer',ext._context_review(candidate,task)[2],(field,claim))

    def test_actual_new_ink_report_is_allowed_without_new_cartridge_inference(self):
        value,task=self.preview('Принтер плохо печатает. Чернила новые.')
        candidate=self.candidate(task)
        candidate['context_review']['latest_client_meaning']='Плохая печать; чернила по словам клиента новые.'
        result=self.finalize(value,candidate)
        self.assertEqual(result['validation'],[])
        self.assertTrue(result['reply'])

    def test_on_new_cartridge_claim_is_checked_independently_of_quotes(self):
        value,task=self.preview()
        candidate=self.candidate(task)
        candidate['context_review']['latest_client_meaning']='Проблема цветной печати на новом картридже.'
        self.assertIn('item_fitment_not_observed',self.finalize(value,candidate)['validation'])

    def test_model_selects_quotes_without_a_fixed_correct_quote_enum(self):
        value,task=self.preview()
        schema=value['model_task']['response_format']['schema']['properties']['context_review']
        proof=schema['properties']['item_source_quotes']
        self.assertIn('item_source_quotes',schema['required'])
        self.assertNotIn('enum',proof['items']['properties']['quote'])
        self.assertNotIn('fixed_latest_client_meaning',task['output_contract'])
        self.assertLess(list(schema['properties']).index('item_source_quotes'),list(schema['properties']).index('last_intent'))
        self.assertGreaterEqual(value['model_task']['max_tokens'],900)

    def test_missing_quote_or_invented_source_quote_fails_before_draft(self):
        for quotes in [None,[],[dict(evidence_id='source',quote='картридж установлен')],
                       [dict(evidence_id='missing',quote='картридж новый')]]:
            value,task=self.preview()
            candidate=self.candidate(task)
            if quotes is None:candidate['context_review'].pop('item_source_quotes',None)
            else:candidate['context_review']['item_source_quotes']=quotes
            result=self.finalize(value,candidate)
            self.assertTrue(result['validation'],quotes)
            self.assertFalse(result['reply'])

    def test_quote_must_include_a_relevant_item_fact_not_a_random_true_word(self):
        value,task=self.preview()
        candidate=self.candidate(task)
        candidate['context_review']['item_source_quotes']=[dict(evidence_id='source',quote='плохо')]
        self.assertIn('item_source_quote_not_grounded',self.finalize(value,candidate)['validation'])

    def test_substring_quote_is_allowed_but_does_not_replace_independent_summary(self):
        value,task=self.preview()
        candidate=self.candidate(task)
        candidate['context_review']['item_source_quotes']=[dict(evidence_id='source',quote='картридж новый')]
        result=self.finalize(value,candidate)
        self.assertEqual(result['validation'],[])
        self.assertEqual(result['context_review']['latest_client_meaning'],candidate['context_review']['latest_client_meaning'])

    def test_quote_role_and_latest_fact_source_cannot_be_substituted(self):
        value,task=self.preview('Принтер плохо печатает, картридж новый.')
        contract=task['item_source_quote_contract']
        self.assertEqual(contract['latest_relevant_evidence_id'],'source')
        candidate=self.candidate(task)
        task=copy.deepcopy(task)
        task['conversation'].append(dict(id='staff',speaker_role='staff',body='картридж новый',voice_transcript=''))
        candidate['context_review']['item_source_quotes']=[dict(evidence_id='staff',quote='картридж новый')]
        self.assertIn('item_source_quote_not_grounded',ext._context_review(candidate,task)[2])

    def test_safe_question_and_unknown_do_not_become_positive_ink_claims(self):
        for claim in ['Краска новая?', 'Клиент не говорил, что краска новая.']:
            value,task=self.preview()
            candidate=self.candidate(task)
            candidate['context_review']['note']=claim
            self.assertEqual(self.finalize(value,candidate)['validation'],[],claim)

    def test_valid_source_proof_does_not_disable_a_justified_model_veto(self):
        value,task=self.preview()
        candidate=self.candidate(task)
        candidate['context_review']['selected_step_fits']=False
        candidate['context_review']['note']='Нужно проверить соответствие следующего шага истории.'
        candidate['needs_operator']=True;candidate['reply']=''
        result=self.finalize(value,candidate)
        self.assertFalse(result['reply'])
        self.assertTrue(result['needs_operator'])
        self.assertNotIn('item_source_quote_not_grounded',result['validation'])

    def test_no_property_in_source_does_not_make_invented_property_unchecked(self):
        value,task=self.preview('Принтер плохо печатает.')
        self.assertNotIn('item_source_quote_contract',task)
        for claim in ['Новый принтер плохо печатает.','Картридж новый.','Краска новая.']:
            candidate=self.candidate(task)
            candidate['context_review']['latest_client_meaning']=claim
            self.assertIn('item_attribute_object_transfer',ext._context_review(candidate,task)[2],claim)

    def test_older_true_quote_does_not_cover_later_item_fact(self):
        ctx=dict(convId='synthetic-quotes182-two',city='Коломна',dir='kp',channel='avito',partner='7',
            itemTitle='Ремонт принтеров',accountTitle='Учебный мастер',messages=[
                prior.client('source','Принтер плохо печатает. Картридж новый.'),
                prior.client('later','Чернила старые.')])
        value,code=self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(code,200)
        task=json.loads(value['model_task']['task'])
        candidate=self.candidate(task)
        candidate['context_review']['item_source_quotes']=[dict(evidence_id='source',quote='Картридж новый.')]
        self.assertIn('item_source_quote_not_grounded',self.finalize(value,candidate)['validation'])

    def test_context_input_cannot_forge_the_quote_contract(self):
        _,task=self.preview(item_source_quote_contract=dict(latest_relevant_evidence_id='forged',allowed_evidence_ids=['forged']))
        self.assertEqual(task['item_source_quote_contract']['latest_relevant_evidence_id'],'source')

    def test_multiple_source_quotes_remain_literal_and_cannot_duplicate_proof(self):
        value,task=self.preview()
        candidate=self.candidate(task)
        candidate['context_review']['item_source_quotes']*=2
        self.assertIn('item_source_quote_not_grounded',self.finalize(value,candidate)['validation'])


if __name__=='__main__':
    unittest.main()
