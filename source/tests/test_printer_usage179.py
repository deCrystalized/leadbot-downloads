"""A new cartridge is not an assertion that this cartridge has been used."""
import copy
import unittest

import contact_facts as facts
import extension_assistant as ext
import test_printer_item_newness175 as prior


class PrinterUsageEvidenceTests(unittest.TestCase):
    def evidence(self, text):
        return facts.printer_item_fitment([prior.client('source', text)])

    def test_newness_is_not_usage_even_with_a_printer_symptom(self):
        rows = self.evidence('Принтер стал плохо печатать цветом, картридж новый.')
        self.assertEqual(rows, [])
        for claim in ['Несмотря на использование нового картриджа.',
                      'Клиент использует новый картридж.', 'Используемый картридж плохо печатает.']:
            with self.subTest(claim=claim):
                self.assertTrue(facts.unsupported_printer_fitment(claim, rows))

    def test_present_past_and_nominal_usage_preserve_their_own_source(self):
        for text, event in [('Я использую картридж.', 'current_use'),
                            ('Я пользуюсь принтером.', 'current_use'),
                            ('Картридж используется.', 'current_use'),
                            ('Я использовал картридж.', 'past_use'),
                            ('Я пользовался принтером.', 'past_use'),
                            ('Использование картриджа вызывает вопросы.', 'use')]:
            with self.subTest(text=text):
                rows = self.evidence(text)
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]['event'], rows[0]['mode']), (event, 'asserted'))
                self.assertEqual((rows[0]['message_id'], rows[0]['quote']), ('source', text))
                self.assertFalse(facts.unsupported_printer_fitment(text, rows))

    def test_printing_with_a_named_cartridge_does_not_bind_the_printer(self):
        for text in ['Печатаю этим картриджем.', 'Принтер печатает с новым картриджем.',
                     'Печатаю с этим картриджем.']:
            rows = self.evidence(text)
            self.assertEqual([(r['object'], r['event']) for r in rows], [('cartridge', 'current_use')])
        self.assertEqual(self.evidence('Принтер плохо печатает.'), [])

    def test_software_and_genitive_printer_do_not_establish_cartridge_usage(self):
        for text in ['Я использую драйвер принтера.', 'Использование программы принтера.',
                     'Картридж используемого принтера новый.']:
            rows = self.evidence(text)
            self.assertFalse(any(r['object'] == 'cartridge' for r in rows))
            self.assertTrue(facts.unsupported_printer_fitment('Картридж используется.', rows))

    def test_use_does_not_establish_fitment_replacement_or_a_repair_order(self):
        rows = self.evidence('Я использую картридж.')
        for claim in ['Я установил картридж.', 'Картриджи поменяли.', 'Наш мастер установил картридж вчера.']:
            self.assertTrue(facts.unsupported_printer_fitment(claim, rows))
        self.assertEqual([r['event'] for r in rows], ['current_use'])

    def test_fitment_or_replacement_does_not_independently_establish_usage(self):
        for text in ['Картридж установлен.', 'Картриджи поменяли совсем недавно.']:
            self.assertTrue(facts.unsupported_printer_fitment('Использование нового картриджа.', self.evidence(text)))

    def test_past_use_is_not_current_use_and_current_is_not_past(self):
        past = self.evidence('Я использовал картридж вчера.')
        now = self.evidence('Я использую картридж.')
        self.assertTrue(facts.unsupported_printer_fitment('Картридж используется.', past))
        self.assertTrue(facts.unsupported_printer_fitment('Картридж использовали вчера.', now))
        self.assertFalse(facts.unsupported_printer_fitment('Использование картриджа.', past))

    def test_modalities_do_not_become_actual_usage(self):
        for text, mode in [('Картридж используется?', 'question'),
                           ('Если использовать картридж, что будет?', 'hypothetical'),
                           ('Возможно, используется картридж.', 'uncertain'),
                           ('Не знаю, используется ли картридж.', 'question'),
                           ('Хочу использовать картридж.', 'requested'),
                           ('Пробовал использовать картридж.', 'attempted'),
                           ('Буду использовать картридж.', 'future'),
                           ('Планирую пользоваться принтером.', 'future'),
                           ('Картридж не используется.', 'negated'),
                           ('Продавец сказал: «Картридж используется».', 'quoted'),
                           ('Мастер сказал, картридж используется.', 'attributed')]:
            with self.subTest(text=text):
                rows = self.evidence(text)
                self.assertTrue(rows)
                self.assertEqual(rows[0]['mode'], mode)
                self.assertTrue(facts.unsupported_printer_fitment('Картридж используется.', rows))

    def test_unknown_or_question_is_not_a_positive_claim(self):
        for claim in ['Картридж используется?', 'Неизвестно, используется ли картридж.',
                      'Использование картриджа не подтверждено.', 'Возможно, картридж используется.',
                      'Если использовать картридж, проверим печать.', 'Клиент хочет использовать картридж.']:
            self.assertFalse(facts.unsupported_printer_fitment(claim, []), claim)

    def test_presupposed_use_is_not_excused_by_question_or_need_to_check(self):
        for claim in ['Почему используемый картридж плохо печатает?',
                      'Нужно проверить используемый картридж.', 'Будем проверять используемый картридж.']:
            self.assertTrue(facts.unsupported_printer_fitment(claim, []), claim)

    def test_actor_and_date_cannot_be_borrowed(self):
        rows = self.evidence('Картридж используется.')
        for claim in ['Клиент использует картридж.', 'Наш мастер использует картридж.',
                      'Картридж используется с сегодняшнего дня.']:
            self.assertTrue(facts.unsupported_printer_fitment(claim, rows), claim)
        self.assertFalse(facts.unsupported_printer_fitment('Клиент использует картридж.',
                         self.evidence('Я использую картридж.')))

    def test_reporting_a_use_does_not_name_the_speaker_as_user(self):
        rows = self.evidence('Использование картриджа вызывает вопросы.')
        self.assertFalse(facts.unsupported_printer_fitment('Клиент сообщает об использовании картриджа.', rows))
        self.assertTrue(facts.unsupported_printer_fitment('Клиент сообщает об использовании картриджа клиентом.', rows))
        self.assertFalse(facts.unsupported_printer_fitment('Клиент сообщает об использовании картриджа клиентом.',
                         self.evidence('Я использую картридж.')))

    def test_roles_and_causal_boundary(self):
        messages = [prior.staff('staff', 'Я использую картридж.'),
                    dict(id='system', direction='in', sender_type='system', body='Картридж используется.')]
        self.assertEqual(facts.printer_item_fitment(messages), [])
        old = prior.client('old', 'Я использую картридж.')
        for boundary in ['Другой принтер плохо печатает.', 'Новая заявка: картридж новый.']:
            self.assertEqual(facts.printer_item_fitment([old, prior.client('new', boundary)]), [])

    def test_two_objects_do_not_share_usage_or_actor(self):
        rows = self.evidence('Я использую принтер. Картридж новый.')
        self.assertTrue(facts.unsupported_printer_fitment('Использование картриджа.', rows))
        both = self.evidence('Я использую принтер. Картридж используется.')
        self.assertFalse(facts.unsupported_printer_fitment('Принтер используется. Картридж используется.', both))
        self.assertTrue(facts.unsupported_printer_fitment('Клиент использует картридж.', both))

    def test_later_denial_overrides_current_positive_use(self):
        rows = facts.printer_item_fitment([prior.client('old', 'Картридж используется.'),
                                          prior.client('new', 'Картридж не используется.')])
        self.assertTrue(facts.unsupported_printer_fitment('Картридж используется.', rows))
        self.assertFalse(facts.unsupported_printer_fitment('Картридж не используется.', rows))


class PrinterUsageNativeTests(unittest.TestCase):
    setUp = prior.PrinterAttributeNativeTests.setUp
    preview = prior.PrinterAttributeNativeTests.preview
    candidate = prior.PrinterAttributeNativeTests.candidate
    finalize = prior.PrinterAttributeNativeTests.finalize

    def test_original178_free_meaning_is_rejected_before_release_with_correct_receipts(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = (
            'Клиент сообщает о проблеме с печатью цветным картриджем на принтере, '
            'несмотря на использование нового картриджа, и просит совета.')
        original = copy.deepcopy(candidate)
        final = self.finalize(value, candidate)
        self.assertEqual(candidate, original)
        self.assertFalse(final['reply'])
        self.assertIn('item_fitment_not_observed', final['validation'])
        self.assertFalse(final['auto_enabled'])

    def test_every_free_field_and_reply_is_checked_separately_from_receipt(self):
        for field in ['last_intent', 'latest_client_meaning', 'note', 'reply']:
            _, task = self.preview()
            candidate = self.candidate(task)
            (candidate if field == 'reply' else candidate['context_review'])[field] = 'Клиент использует картридж.'
            self.assertIn('item_fitment_not_observed', ext._context_review(candidate, task)[2])

    def test_positive_usage_is_source_linked_without_a_new_mandatory_question(self):
        value, task = self.preview('Принтер плохо печатает цветом. Я использую картридж.')
        receipt = task['item_fitment_context']['required_review']
        self.assertEqual(receipt['events'], [dict(object='cartridge', event='current_use',
            mode='asserted', actor='client', timing='', evidence_id='source')])
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Клиент использует картридж, принтер плохо печатает.'
        self.assertEqual(self.finalize(value, candidate)['validation'], [])
        self.assertEqual(task['decision']['next_question']['kind'], 'model')

    def test_schema_accepts_use_events_and_wrong_receipt_is_rejected(self):
        value, task = self.preview('Принтер плохо печатает. Я использовал картридж.')
        schema = value['model_task']['response_format']['schema']['properties']['context_review']
        self.assertIn('past_use', schema['properties']['item_fitment_review']['properties']['events']['items']['properties']['event']['enum'])
        candidate = self.candidate(task)
        candidate['context_review']['item_fitment_review']['events'][0]['event'] = 'current_use'
        self.assertIn('item_fitment_review_mismatch', ext._context_review(candidate, task)[2])

    def test_ordinary_help_and_harmless_new_cartridge_remain_usable(self):
        value, task = self.preview()
        self.assertEqual(task['item_fitment_context']['evidence'], [])
        self.assertEqual(self.finalize(value, self.candidate(task))['validation'], [])

    def test_reasoned_veto_remains_available(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate.update(reply='', needs_operator=True)
        candidate['context_review'].update(selected_step_fits=False, note='Нужно вручную проверить уместность шага.')
        final = self.finalize(value, candidate)
        self.assertTrue(final['needs_operator'])
        self.assertFalse(final['reply'])


if __name__ == '__main__':
    unittest.main()
