"""Printing by a particular physical item needs its own source, not newness."""
import copy
import unittest

import contact_facts as facts
import extension_assistant as ext
import test_printer_item_newness175 as prior


class PrintingMediumEvidenceTests(unittest.TestCase):
    def evidence(self, text):
        return facts.printer_item_fitment([prior.client('source', text)])

    def test_nominal_original180_claim_is_not_supported_by_newness(self):
        rows = self.evidence(prior.REPORT)
        self.assertEqual(rows, [])
        self.assertTrue(facts.unsupported_printer_fitment(
            'Клиент сообщил о проблеме с печатью цветным картриджем (новым), изображение размытое.', rows))

    def test_finite_printing_instrument_and_reverse_order_are_source_linked(self):
        for text in ['Печатаю новым картриджем.', 'Новым картриджем я печатаю.',
                     'Принтер печатает цветным картриджем.', 'Печатаем новыми картриджами.']:
            with self.subTest(text=text):
                rows = self.evidence(text)
                self.assertEqual([(x['object'], x['event'], x['mode']) for x in rows],
                                 [('cartridge', 'current_use', 'asserted')])
                self.assertEqual((rows[0]['message_id'], rows[0]['quote']), ('source', text))
                self.assertFalse(facts.unsupported_printer_fitment(text, rows))

    def test_nominal_and_instrumental_forms_do_not_invent_time(self):
        for text in ['Печать новым картриджем размытая.', 'Проблема с печатью цветным картриджем.',
                     'При печати с помощью нового картриджа видны полосы.',
                     'Проблема печати этим картриджем.']:
            rows = self.evidence(text)
            self.assertEqual([(x['object'], x['event']) for x in rows], [('cartridge', 'use')], text)
            self.assertEqual(rows[0]['timing'], '')
            self.assertFalse(facts.unsupported_printer_fitment(text, rows))

    def test_completed_print_and_participle_support_past_not_current_use(self):
        for text in ['Отпечатано новым картриджем.', 'Напечатанный новым картриджем лист размыт.',
                     'Я печатал новым картриджем вчера.']:
            rows = self.evidence(text)
            self.assertEqual(rows[0]['event'], 'past_use')
            self.assertFalse(facts.unsupported_printer_fitment('Использование картриджа.', rows))
            self.assertTrue(facts.unsupported_printer_fitment('Картридж используется.', rows))

    def test_named_printer_medium_is_not_cartridge_usage(self):
        for text in ['Печатаю на новом принтере.', 'На новом принтере я печатаю.',
                     'Печать на принтере плохая.', 'Отпечатано на МФУ.']:
            rows = self.evidence(text)
            self.assertTrue(rows, text)
            self.assertTrue(all(x['object'] == 'printer' for x in rows), text)
            self.assertTrue(facts.unsupported_printer_fitment('Картридж используется.', rows))

    def test_purpose_genitive_and_plain_symptom_do_not_name_a_used_cartridge(self):
        for text in ['Картридж для печати новый.', 'Для печати нужен новый картридж.',
                     'Принтер плохо печатает, картридж новый.', 'Плохая печать принтера.',
                     'Принтер для печати документов новый.', 'Картридж печатающего принтера новый.']:
            self.assertEqual(self.evidence(text), [], text)

    def test_software_and_other_parts_do_not_supply_physical_item_use(self):
        for text in ['Печать с помощью драйвера принтера.', 'Печать новой головкой принтера.',
                     'Печать новым барабаном принтера.', 'Программа печатает на принтере.']:
            rows = self.evidence(text)
            self.assertFalse(any(x['object'] == 'cartridge' for x in rows), text)

    def test_questions_uncertainty_and_hypotheses_are_not_assertions(self):
        for text, mode in [('Печатаете новым картриджем?', 'question'),
                           ('Не знаю, печатают ли новым картриджем.', 'question'),
                           ('Возможно, печать новым картриджем размытая.', 'uncertain'),
                           ('Если печатать новым картриджем, будут полосы.', 'hypothetical')]:
            rows = self.evidence(text)
            self.assertTrue(rows, text)
            self.assertEqual(rows[0]['mode'], mode)
            self.assertTrue(facts.unsupported_printer_fitment('Печать новым картриджем размытая.', rows))
            self.assertFalse(facts.unsupported_printer_fitment(text, []))

    def test_plans_requests_attempts_do_not_become_performed_use(self):
        for text, mode in [('Буду печатать новым картриджем.', 'future'),
                           ('Планирую печать новым картриджем.', 'future'),
                           ('Нужна печать новым картриджем.', 'requested'),
                           ('Хочу печатать новым картриджем.', 'requested'),
                           ('Пробовал печатать новым картриджем.', 'attempted')]:
            rows = self.evidence(text)
            self.assertTrue(rows, text)
            self.assertEqual(rows[0]['mode'], mode)
            self.assertTrue(facts.unsupported_printer_fitment('Печать новым картриджем размытая.', rows))

    def test_negation_and_denied_report_remain_nonpositive(self):
        for text, mode in [('Не печатаю новым картриджем.', 'negated'),
                           ('Печати новым картриджем не было.', 'negated'),
                           ('Не сообщал о печати новым картриджем.', 'not_asserted')]:
            rows = self.evidence(text)
            self.assertTrue(rows, text)
            self.assertEqual(rows[0]['mode'], mode)
            self.assertTrue(facts.unsupported_printer_fitment('Печать новым картриджем размытая.', rows))

    def test_quotes_and_other_reporters_do_not_establish_client_assertion(self):
        for text, mode in [('Продавец сказал: «Печать новым картриджем размытая».', 'quoted'),
                           ('Мастер сказал, печатает новым картриджем.', 'attributed')]:
            rows = self.evidence(text)
            self.assertEqual(rows[0]['mode'], mode)
            self.assertTrue(facts.unsupported_printer_fitment('Печать новым картриджем размытая.', rows))

    def test_staff_system_and_other_enquiry_cannot_supply_use(self):
        messages = [prior.staff('s', 'Печать новым картриджем размытая.'),
                    dict(id='a', direction='in', sender_type='system', body='Печатаю новым картриджем.')]
        self.assertEqual(facts.printer_item_fitment(messages), [])
        messages = [prior.client('old', 'Печатаю новым картриджем.'),
                    prior.client('new', 'Другой принтер плохо печатает, картридж новый.')]
        self.assertEqual(facts.printer_item_fitment(messages), [])

    def test_cartridge_colours_and_age_do_not_transfer_between_items(self):
        rows = self.evidence('Я печатаю старым чёрным картриджем. Цветной картридж новый.')
        self.assertFalse(facts.unsupported_printer_fitment('Печать старым чёрным картриджем.', rows))
        for text in ['Печать новым картриджем.', 'Печать цветным картриджем.',
                     'Печать картриджем (новым).']:
            self.assertTrue(facts.unsupported_printer_fitment(text, rows), text)

    def test_unspecified_cartridge_use_does_not_resolve_specific_one(self):
        rows = self.evidence('Использую картридж. Новый картридж пока в коробке.')
        self.assertTrue(facts.unsupported_printer_fitment('Печать новым картриджем.', rows))
        self.assertFalse(facts.unsupported_printer_fitment('Использование картриджа.', rows))

    def test_ordinals_and_two_printers_remain_separate(self):
        rows = self.evidence('Печатаю первым картриджем. Второй картридж новый.')
        self.assertTrue(facts.unsupported_printer_fitment('Печать вторым картриджем.', rows))
        self.assertFalse(facts.unsupported_printer_fitment('Печать первым картриджем.', rows))
        rows = self.evidence('Печатаю на старом принтере. Новый принтер выключен.')
        self.assertTrue(facts.unsupported_printer_fitment('Печать на новом принтере.', rows))

    def test_two_explicit_printing_media_each_keep_their_proof(self):
        rows = self.evidence('Печатаю старым картриджем. Печатаю новым картриджем.')
        self.assertEqual(len(rows), 2)
        self.assertFalse(facts.unsupported_printer_fitment('Печать старым картриджем. Печать новым картриджем.', rows))

    def test_other_item_genitive_does_not_supply_cartridge_qualifier(self):
        rows = self.evidence('Использую картридж нового принтера.')
        self.assertFalse(facts.unsupported_printer_fitment('Использование картриджа.', rows))
        self.assertTrue(facts.unsupported_printer_fitment('Печать новым картриджем.', rows))

    def test_intervening_descriptive_adjective_keeps_age_and_colour_binding(self):
        rows = self.evidence('Печатаю старым оригинальным чёрным картриджем.')
        self.assertFalse(facts.unsupported_printer_fitment('Печать старым чёрным картриджем.', rows))
        self.assertTrue(facts.unsupported_printer_fitment('Печать новым картриджем.', rows))

    def test_usage_adds_no_fitment_actor_date_or_repair(self):
        rows = self.evidence('Печать новым картриджем размытая.')
        for text in ['Картридж установлен.', 'Картридж заменили.',
                     'Наш мастер использует картридж.', 'Картридж использовали вчера.']:
            self.assertTrue(facts.unsupported_printer_fitment(text, rows), text)
        self.assertEqual({x['event'] for x in rows}, {'use'})

    def test_participial_presupposition_not_excused_by_question(self):
        self.assertTrue(facts.unsupported_printer_fitment('Почему напечатанный новым картриджем лист размыт?', []))
        self.assertFalse(facts.unsupported_printer_fitment('Напечатано новым картриджем?', []))

    def test_later_denial_is_scoped_to_same_specific_item(self):
        rows = facts.printer_item_fitment([prior.client('a', 'Печатаю старым картриджем.'),
            prior.client('b', 'Не печатаю новым картриджем.')])
        self.assertFalse(facts.unsupported_printer_fitment('Печать старым картриджем.', rows))
        self.assertTrue(facts.unsupported_printer_fitment('Печать новым картриджем.', rows))


class PrintingMediumNativeTests(unittest.TestCase):
    setUp = prior.PrinterAttributeNativeTests.setUp
    preview = prior.PrinterAttributeNativeTests.preview
    candidate = prior.PrinterAttributeNativeTests.candidate
    finalize = prior.PrinterAttributeNativeTests.finalize

    def test_native180_wording_rejected_with_correct_receipts_and_no_json_repair(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = (
            'Клиент сообщил о проблеме с печатью цветным картриджем (новым), изображение получается размытым.')
        original = copy.deepcopy(candidate)
        final = self.finalize(value, candidate)
        self.assertEqual(candidate, original)
        self.assertIn('item_fitment_not_observed', final['validation'])
        self.assertFalse(final['reply'])
        self.assertFalse(final['auto_enabled'])

    def test_all_free_fields_checked_without_trusting_receipt(self):
        _, task = self.preview()
        for field in ['last_intent', 'latest_client_meaning', 'note', 'reply']:
            candidate = self.candidate(task)
            (candidate if field == 'reply' else candidate['context_review'])[field] = 'Печать новым картриджем размытая.'
            self.assertIn('item_fitment_not_observed', ext._context_review(candidate, task)[2], field)

    def test_positive_nominal_source_remains_usable_without_new_question(self):
        value, task = self.preview('Принтер плохо печатает. Печать новым картриджем размытая.')
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Печать новым картриджем размытая.'
        final = self.finalize(value, candidate)
        self.assertEqual(final['validation'], [])
        self.assertEqual(task['decision']['next_question']['kind'], 'model')
        self.assertTrue(final['reply'])

    def test_event_qualifiers_survive_server_context_and_remain_source_bound(self):
        _, task = self.preview('Принтер плохо печатает. Печатаю старым чёрным картриджем. Картридж новый.')
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Печать новым картриджем размытая.'
        self.assertIn('item_fitment_not_observed', ext._context_review(candidate, task)[2])
        context = task['item_fitment_context']
        self.assertFalse(context['independent_model_interpretation'])
        self.assertFalse(context['work_execution_verified'])
        self.assertEqual(context['evidence'][0]['evidence_id'], 'source')

    def test_ordinary_help_and_suitable_brand_question_remain_allowed(self):
        value, task = self.preview()
        final = self.finalize(value, self.candidate(task))
        self.assertEqual(final['validation'], [])
        self.assertIn('Здравствуйте', final['reply'])
        self.assertEqual(task['item_fitment_context']['evidence'], [])

    def test_reasoned_veto_remains_available(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate.update(reply='', needs_operator=True)
        candidate['context_review'].update(selected_step_fits=False, note='Нужно вручную проверить следующий шаг.')
        final = self.finalize(value, candidate)
        self.assertTrue(final['needs_operator'])
        self.assertFalse(final['reply'])


if __name__ == '__main__':
    unittest.main()
