"""A consultation about a possible driver change is not a selected operation."""
import unittest

import qualification_state as qs
import test_printer_colour_consult174 as prior


class SoftwareChoiceEvidenceTests(unittest.TestCase):
    def state(self, text):
        return qs.inspect([prior.client('source', text)])['software_use']

    def test_possible_driver_consultation_does_not_answer_work_choice(self):
        for text in ['Может стоит просто драйвера переустановить?',
                     'Если переустановить программу, это поможет?',
                     'Не знаю, нужно ли настроить программу.',
                     'Хочу проконсультироваться, стоит ли переустановить драйвер?']:
            self.assertEqual(self.state(text)['status'], 'missing', text)

    def test_explicit_operation_and_price_scope_keep_whole_word_and_source(self):
        for text, word in [('Нужно установить AutoCAD.', 'установить'),
                           ('Настройте программу.', 'Настройте'),
                           ('Переустановите драйвер?', 'Переустановите'),
                           ('Сколько стоит установить AutoCAD?', 'установить'),
                           ('Нужно обучение Photoshop.', 'обучение')]:
            row = self.state(text)
            self.assertEqual(row['status'], 'answered', text)
            self.assertEqual(row['value'], word)
            self.assertEqual(row['message_id'], 'source')
            self.assertEqual(row['quote'], text)

    def test_terse_choices_remain_usable(self):
        for text in ['Установить', 'Настройка', 'Установку, пожалуйста.']:
            self.assertEqual(self.state(text)['status'], 'answered', text)

    def test_past_and_negated_software_actions_do_not_choose_new_work(self):
        for text in ['Программу установили вчера.', 'Драйвер установлен.',
                     'Не нужно устанавливать программу.', 'Установка программы не нужна.',
                     'Я пробовал переустановить драйвер.']:
            self.assertEqual(self.state(text)['status'], 'missing', text)

    def test_quotes_reports_and_nonclient_roles_do_not_supply_choice(self):
        for text in ['Мастер сказал установить AutoCAD.',
                     'В инструкции: «Установить программу».']:
            self.assertEqual(self.state(text)['status'], 'missing', text)
        for role in ['system', 'operator', 'bot']:
            row = prior.client('foreign', 'Нужно установить AutoCAD.'); row['sender_type'] = role
            self.assertEqual(qs.inspect([row])['software_use']['status'], 'missing')

    def test_other_physical_jobs_do_not_answer_program_choice(self):
        for text in ['Установить унитаз.', 'Настроить замок.', 'Установить новый картридж.']:
            self.assertEqual(self.state(text)['status'], 'missing', text)

    def test_direct_request_in_later_clause_is_not_lost_after_question(self):
        row = self.state('Может стоит переустановить драйвер? Установите AutoCAD.')
        self.assertEqual(row['value'], 'Установите')

    def test_actual_staff_choice_question_and_short_answer_stay_available(self):
        rows = [prior.staff('q', 'Программу нужно установить или настроить?'),
                prior.client('a', 'Установить, пожалуйста.')]
        value = qs.inspect(rows)['software_use']
        self.assertEqual((value['status'], value['message_id']), ('answered', 'a'))


class SoftwareChoicePreviewTests(unittest.TestCase):
    setUp = prior.PrinterConsultationNativeTests.setUp
    preview = prior.PrinterConsultationNativeTests.preview
    trace = prior.PrinterConsultationNativeTests.trace

    def test_driver_question_does_not_leak_an_answered_choice_in_preview(self):
        rows = self.trace() + [prior.client('q',
            'Помощь нужна в ближайшие дни, может стоит драйвера переустановить?')]
        value, task = self.preview(rows)
        self.assertNotEqual(value.get('qualification', {}).get('software_use', {}).get('status'), 'answered')
        self.assertEqual(task['decision']['action'], 'question')
        self.assertNotIn('номер', task['proposed_reply'].lower())
        self.assertFalse(value['auto_enabled'])


if __name__ == '__main__':
    unittest.main()
