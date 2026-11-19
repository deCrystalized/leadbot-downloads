"""Newness is not performed work: literal, causal, item-bound fitment evidence."""
import copy
import unittest

import contact_facts as facts
import extension_assistant as ext
import test_printer_item_newness175 as prior


class PrinterFitmentEvidenceTests(unittest.TestCase):
    def evidence(self, text):
        return facts.printer_item_fitment([prior.client('source', text)])

    def test_newness_does_not_establish_either_performed_action(self):
        self.assertEqual(self.evidence('Принтер плохо печатает, картридж новый.'), [])
        for claim in ['Установленный новый картридж', 'Новый картридж установлен',
                      'После установки картриджа печать плохая', 'Картридж заменили']:
            with self.subTest(claim=claim):
                self.assertTrue(facts.unsupported_printer_fitment(claim, []))

    def test_literal_order_plural_and_genitive_bind_correct_item(self):
        for text, event in [('Картридж установлен.', 'fitment'),
                            ('Установленный новый картридж плохо печатает.', 'fitment'),
                            ('Картриджи поменяли совсем недавно.', 'replacement'),
                            ('После замены картриджа появилась проблема.', 'replacement'),
                            ('В принтере стоит картридж.', 'fitment')]:
            with self.subTest(text=text):
                rows = self.evidence(text)
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]['object'], rows[0]['event'], rows[0]['mode']),
                                 ('cartridge', event, 'asserted'))
                self.assertEqual(rows[0]['message_id'], 'source')
                self.assertEqual(rows[0]['quote'], text)
                self.assertFalse(facts.unsupported_printer_fitment(text, rows))

    def test_printer_software_and_neighbouring_item_do_not_supply_cartridge_fitment(self):
        for text in ['Принтер установлен, картридж новый.', 'Установили драйвер принтера.',
                     'Картридж установленного принтера новый.', 'Заменили головку принтера.',
                     'Драйвер установлен на принтере. Картридж новый.']:
            with self.subTest(text=text):
                rows = self.evidence(text)
                self.assertFalse(any(r['object'] == 'cartridge' for r in rows))
                self.assertTrue(facts.unsupported_printer_fitment('Картридж установлен.', rows))

    def test_modes_do_not_become_completed_installation(self):
        for text, mode in [('Картридж установлен?', 'question'),
                           ('Если картридж установлен, что делать?', 'hypothetical'),
                           ('Возможно, картридж установлен.', 'uncertain'),
                           ('Нужно установить картридж.', 'requested'),
                           ('Буду ставить картридж, установлен он будет завтра.', 'future'),
                           ('Пробовал установить картридж.', 'attempted'),
                           ('Картридж не установлен.', 'negated'),
                           ('В инструкции: «Картридж установлен».', 'quoted'),
                           ('Продавец сказал, картридж установлен.', 'attributed')]:
            with self.subTest(text=text):
                rows = self.evidence(text)
                self.assertTrue(rows)
                self.assertEqual(rows[0]['mode'], mode)
                self.assertTrue(facts.unsupported_printer_fitment('Картридж установлен.', rows))

    def test_negation_does_not_prove_opposite_or_erase_its_literal(self):
        rows = self.evidence('Картридж новый, картридж ещё не установлен.')
        self.assertEqual(rows[0]['mode'], 'negated')
        self.assertFalse(facts.unsupported_printer_fitment('Картридж не установлен.', rows))
        self.assertTrue(facts.unsupported_printer_fitment('Картридж не установлен.', []))
        self.assertFalse(facts.unsupported_printer_fitment('Не утверждаю, что картридж установлен.', []))

    def test_third_party_quotation_may_be_retained_but_not_promoted(self):
        text = 'Продавец сказал, картридж установлен.'
        self.assertFalse(facts.unsupported_printer_fitment(text, self.evidence(text)))
        self.assertTrue(facts.unsupported_printer_fitment('Картридж установлен.', self.evidence(text)))

    def test_staff_system_and_future_messages_cannot_supply_event(self):
        before = [prior.client('source', prior.REPORT)]
        foreign = [prior.staff('staff', 'Картридж установлен.'),
                   dict(id='system', direction='in', sender_type='avito', body='Картридж установлен.')]
        self.assertEqual(facts.printer_item_fitment(before + foreign), [])
        after = facts.printer_item_fitment(before + [prior.client('later', 'Картриджи поменяли совсем недавно.')])
        self.assertEqual(after[0]['message_id'], 'later')
        self.assertEqual(after[0]['actor'], 'unspecified')
        self.assertEqual(after[0]['timing'], 'недавно')

    def test_actor_and_time_cannot_be_added_to_an_unspecified_replacement(self):
        rows = self.evidence('Картриджи поменяли совсем недавно.')
        self.assertFalse(facts.unsupported_printer_fitment('Картриджи недавно заменили.', rows))
        for text in ['Клиент сам заменил картриджи недавно.', 'Наш мастер заменил картридж.',
                     'Мы заменили картридж.', 'Картридж заменён клиентом.', 'Картридж заменили вчера.']:
            with self.subTest(text=text):
                self.assertTrue(facts.unsupported_printer_fitment(text, rows))
        self.assertFalse(facts.unsupported_printer_fitment('Клиент сам заменил картридж вчера.',
                         self.evidence('Я сам заменил картридж вчера.')))

    def test_new_enquiry_does_not_borrow_old_performed_work(self):
        for boundary in ['Другой принтер плохо печатает.', 'Новая заявка: картридж новый.']:
            rows = facts.printer_item_fitment([prior.client('old', 'Картридж установлен.'),
                                               prior.client('current', boundary)])
            self.assertEqual(rows, [])

    def test_later_denial_does_not_leave_earlier_fitment_as_current_fact(self):
        rows = facts.printer_item_fitment([prior.client('old', 'Картридж установлен.'),
                                           prior.client('current', 'Картридж не установлен.')])
        self.assertTrue(facts.unsupported_printer_fitment('Картридж установлен.', rows))
        self.assertFalse(facts.unsupported_printer_fitment('Картридж не установлен.', rows))

    def test_unrelated_time_and_actor_on_another_action_do_not_transfer(self):
        rows = self.evidence('Вчера я заменил принтер, картридж установлен.')
        cartridge = next(r for r in rows if r['object'] == 'cartridge')
        self.assertEqual((cartridge['actor'], cartridge['timing']), ('unspecified', ''))
        self.assertTrue(facts.unsupported_printer_fitment('Клиент установил картридж вчера.', rows))

    def test_software_installation_cannot_establish_device_installation(self):
        for text in ['Драйвер установлен на принтере.', 'Программа установлена для принтера.',
                     'После замены головки принтер не печатает.']:
            with self.subTest(text=text):
                self.assertEqual(self.evidence(text), [])

    def test_both_explicit_objects_keep_their_own_events(self):
        rows = self.evidence('Принтер установлен. Картриджи заменили.')
        self.assertEqual([(r['object'], r['event']) for r in rows],
                         [('printer', 'fitment'), ('cartridge', 'replacement')])
        self.assertFalse(facts.unsupported_printer_fitment('Принтер установлен. Картриджи заменили.', rows))
        self.assertTrue(facts.unsupported_printer_fitment('Картридж установлен. Принтер заменили.', rows))

    def test_nonclaims_and_normal_help_do_not_require_installation_answer(self):
        for text in ['Марку и модель подскажите?', 'Нужно проверить работу принтера.',
                     'Картридж установлен?', 'Клиент спрашивает, установлен ли картридж.',
                     'Если картридж установлен, проверим печать.',
                     'Клиент хочет заменить картридж.', 'Помощь с плохой цветной печатью.']:
            with self.subTest(text=text):
                self.assertFalse(facts.unsupported_printer_fitment(text, []))

    def test_modality_of_checking_does_not_justify_presupposed_installation(self):
        for text in ['Нужно проверить установленный картридж.',
                     'Хочу понять, почему установленный картридж плохо печатает.',
                     'Будем проверять установленный картридж.',
                     'Пробовал проверить установленный картридж.',
                     'Установленный картридж будет печатать нормально.']:
            with self.subTest(text=text):
                self.assertTrue(facts.unsupported_printer_fitment(text, []))


class PrinterFitmentNativeTests(unittest.TestCase):
    setUp = prior.PrinterAttributeNativeTests.setUp
    preview = prior.PrinterAttributeNativeTests.preview
    candidate = prior.PrinterAttributeNativeTests.candidate
    finalize = prior.PrinterAttributeNativeTests.finalize

    def test_original176_false_meaning_is_rejected_with_correct_receipt(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = (
            'принтер плохо печатает цветной краской, изображение размытое, несмотря на установленный новый картридж')
        original = copy.deepcopy(candidate)
        final = self.finalize(value, candidate)
        self.assertFalse(final['reply'])
        self.assertIn('item_fitment_not_observed', final['validation'])
        self.assertEqual(candidate, original)
        self.assertFalse(final['auto_enabled'])

    def test_every_free_semantic_field_and_reply_has_the_same_guard(self):
        for field in ('last_intent', 'latest_client_meaning', 'note', 'reply'):
            with self.subTest(field=field):
                _, task = self.preview()
                candidate = self.candidate(task)
                target = candidate if field == 'reply' else candidate['context_review']
                target[field] = 'Установленный картридж плохо печатает.'
                _, status, errors = ext._context_review(candidate, task)
                self.assertEqual(status, 'inconsistent')
                self.assertIn('item_fitment_not_observed', errors)

    def test_explicit_current_fitment_and_reported_replacement_remain_usable(self):
        for source, meaning in [('Принтер плохо печатает. Картридж установлен.', 'Установленный картридж плохо печатает.'),
                                ('Принтер плохо печатает. Картриджи поменяли совсем недавно.', 'Картриджи недавно заменили.')]:
            with self.subTest(source=source):
                _, task = self.preview(source)
                candidate = self.candidate(task)
                candidate['context_review']['latest_client_meaning'] = meaning
                _, status, errors = ext._context_review(candidate, task)
                self.assertEqual(errors, [])
                self.assertEqual(status, 'provided')

    def test_no_age_adjective_still_checks_performed_claim(self):
        _, task = self.preview('Принтер плохо печатает цветом.')
        self.assertNotIn('item_attribute_context', task)
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'После установки картриджа печать плохая.'
        self.assertIn('item_fitment_not_observed', ext._context_review(candidate, task)[2])

    def test_source_context_is_server_derived_and_not_new_mandatory_question(self):
        value, task = self.preview(item_fitment_context=dict(evidence=[dict(event='fitment')]))
        proof = task['item_fitment_context']
        self.assertEqual(proof['evidence'], [])
        self.assertFalse(proof['independent_model_interpretation'])
        self.assertFalse(proof['work_execution_verified'])
        self.assertEqual(task['decision']['next_question']['kind'], 'model')
        self.assertNotIn('установ', task['proposed_reply'].lower())
        self.assertEqual(self.finalize(value, self.candidate(task))['validation'], [])

    def test_reasoned_empty_handoff_remains_possible(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate.update(reply='', needs_operator=True)
        candidate['context_review'].update(selected_step_fits=False, note='Нужно проверить уместность следующего шага.')
        final = self.finalize(value, candidate)
        self.assertTrue(final['needs_operator'])
        self.assertFalse(final['reply'])


if __name__ == '__main__':
    unittest.main()
