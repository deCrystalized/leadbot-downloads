"""Print-quality reports and consultation questions retain the client's scope."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_catalog as catalog
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant


REPORT = 'Здравствуйте, не подскажите, что может быть с принтером, стал плохо печатать цветной краской, все размыто, картридж новый'
KNOWN = dict(direction='kp', city='Коломна', channel='avito', partner='7',
             title='Ремонт принтеров', account_name='Учебный мастер')


def client(mid, text):
    return dict(id=mid, direction='in', sender_type='client', body=text)


def staff(mid, text):
    return dict(id=mid, direction='out', sender_type='operator', body=text,
                delivery_status='delivered')


class ColourEvidenceTests(unittest.TestCase):
    def test_original_quality_is_already_a_problem_without_a_component_diagnosis(self):
        value = qs.printer_quality_evidence([client('problem', REPORT)])
        self.assertIsNotNone(value)
        self.assertEqual(value['value'], 'плохо печатать')
        self.assertEqual(value['message_id'], 'problem')
        self.assertEqual(value['quote'], REPORT)
        self.assertEqual(qs.inspect([client('problem', REPORT)])['problem']['status'], 'answered')

    def test_print_quality_variants_with_printer_context(self):
        for text in ['Принтер плохо печатает цветом.', 'МФУ печатает размыто.',
                     'Принтер стал нечётко печатать.', 'У принтера смазанная печать.',
                     'Принтер печатает бледно.']:
            with self.subTest(text=text):
                value = qs.printer_quality_evidence([client('quality', text)])
                self.assertIsNotNone(value)
                self.assertIn(value['value'], text)

    def test_quality_in_following_client_message_retains_exact_source(self):
        value = qs.printer_quality_evidence([client('printer', 'Есть принтер Canon.'),
                                            client('quality', 'Цветная печать размытая.')])
        self.assertEqual(value['message_id'], 'quality')
        self.assertEqual(value['value'], 'печать размытая')

    def test_other_roles_quotes_hypothesis_old_and_negated_symptoms_are_not_new_evidence(self):
        for text in ['Если принтер плохо печатает, что делать?',
                     'Сосед говорит, принтер плохо печатает.',
                     'Другой мастер написал: «Принтер плохо печатает».',
                     'Принтер не плохо печатает, всё нормально.',
                     'Принтер раньше плохо печатал, теперь исправен.',
                     'На футболке размытая печать.', 'Документ с размытым текстом.']:
            with self.subTest(text=text):
                self.assertIsNone(qs.printer_quality_evidence([client('negative', text)]))
        self.assertIsNone(qs.printer_quality_evidence([staff('staff', 'Принтер плохо печатает.')]))

    def test_new_enquiry_clears_the_old_printer_context(self):
        self.assertIsNone(qs.printer_quality_evidence([
            client('old', 'Принтер плохо печатает.'),
            client('new', 'Теперь нужен ремонт телевизора, размытая печать на майке.')]))


class ConsultationEvidenceTests(unittest.TestCase):
    def history(self, question):
        return [client('problem', REPORT), staff('modelq', 'Марку и модель?'),
                client('model', 'Canon i-SENSYS LBP7010C'),
                staff('dateq', 'На когда нужна помощь?'), client('question', question)]

    def test_current_cause_question_and_following_clarification_share_the_burst(self):
        rows = self.history('Может ли быть проблема с драйверами?')
        rows.append(client('black', 'Хотя чёрным нормально печатает.'))
        evidence = qs.printer_consultation_question(rows)
        self.assertEqual(evidence['message_id'], 'question')
        self.assertEqual(evidence['quote'], rows[-2]['body'])
        self.assertIn('black', evidence['current_client_message_ids'])

    def test_question_about_trying_drivers_is_not_a_requested_installation(self):
        evidence = qs.printer_consultation_question(self.history(
            'Просто хотел проконсультироваться, может стоит драйвера переустановить?'))
        self.assertIsNotNone(evidence)
        self.assertFalse(evidence['diagnosis_established'])

    def test_possible_or_negated_setup_is_not_a_positive_setup_order(self):
        for text in ['Может надо установить драйвер принтера?',
                     'Может ли быть проблема с драйверами? Не нужно переустановить, просто спрашиваю.']:
            with self.subTest(text=text):
                self.assertIsNotNone(qs.printer_consultation_question(self.history(text)))

    def test_old_staff_quoted_or_other_device_question_does_not_supply_current_advice(self):
        rows = self.history('Может ли быть проблема с драйверами?')
        self.assertIsNone(qs.printer_consultation_question(rows + [staff('answer', 'Нужно проверить.'), client('ack', 'Хорошо.')]))
        self.assertIsNone(qs.printer_consultation_question([staff('q', 'Может ли быть проблема с драйвером принтера?')]))
        self.assertIsNone(qs.printer_consultation_question(self.history('В инструкции написано: «Может ли быть проблема с драйвером?»')))
        self.assertIsNone(qs.printer_consultation_question(rows + [client('new', 'Новая заявка: компьютер не включается, может драйвер?')]))

    def test_new_positive_setup_instruction_replaces_consultation(self):
        rows = self.history('Может ли быть проблема с драйверами?')
        self.assertIsNone(qs.printer_consultation_question(rows + [client('order', 'Переустановите драйвер принтера и настройте подключение.')]))


class PrinterConsultationNativeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner', LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))
        self.serial = 0

    def preview(self, messages, **extra):
        self.serial += 1
        context = dict(convId='synthetic-printer-consult174-' + str(self.serial),
                       city='Коломна', dir='kp', channel='avito', partner='7',
                       accountTitle='Учебный мастер', itemTitle='Ремонт принтеров',
                       messages=messages, **extra)
        value, code = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review', ctx=context))
        self.assertEqual(code, 200)
        self.assertFalse(value['auto_enabled'])
        self.assertFalse(value['lead']['can_create_automatically'])
        task = json.loads(value['model_task']['task']) if value.get('model_task') else None
        return value, task

    def trace(self):
        return [client('problem', REPORT), staff('greeting', 'Здравствуйте!'),
                staff('response', 'Смотреть нужно.'),
                staff('modelq', 'Марку и модель подскажите?'),
                client('model', 'Canon i-SENSYS LBP7010C'),
                staff('dateq', 'На когда нужна помощь?')]

    def test_first_response_qualifies_known_problem_instead_of_reasking_it(self):
        out, task = self.preview([client('problem', REPORT)])
        self.assertEqual(task['decision']['next_question']['kind'], 'model')
        self.assertNotIn('Что у вас случилось', task['proposed_reply'])
        self.assertIn('причину', task['proposed_reply'])
        self.assertEqual(out['service']['status'], 'supported')

    def test_driver_question_is_answered_before_harvesting_contacts(self):
        out, task = self.preview(self.trace() + [client('cause', 'Может ли быть проблема с драйверами?')])
        self.assertIsNotNone(task)
        self.assertIn('причину', task['fixed_reply'])
        self.assertNotRegex(task['fixed_reply'].lower(), r'номер|телефон|модель|точно\s+драйвер|картридж\w*\s+(?:замен|слом)')
        self.assertEqual(out['crm_flags']['price_consent'], 'not_quoted')

    def test_consultation_and_black_normal_do_not_become_diagnostic_only_or_repaired(self):
        rows = self.trace() + [client('cause', 'Может ли быть проблема с драйверами?'),
                client('consult', 'Помощь нужна в ближайшие дни, просто хотел проконсультироваться, может стоит драйвера переустановить?'),
                client('black', 'Хотя черной краской нормально печатает')]
        out, task = self.preview(rows)
        self.assertIn('причину', task['fixed_reply'])
        self.assertNotIn('500', task['fixed_reply'])
        self.assertEqual(out['facts']['standalone_printer_diagnostic'], {})
        self.assertFalse(out.get('accepted_visit'))

    def test_model_cannot_replace_neutral_answer_with_a_diagnosis(self):
        messages = self.trace() + [client('cause', 'Может ли быть проблема с драйверами?')]
        out, task = self.preview(messages)
        candidate = dict(reply='Точно проблема в драйвере, переустановка всё исправит.', needs_operator=False,
                         context_review=dict(last_intent='Качество печати', latest_client_meaning='Вопрос о возможной причине',
                            selected_step_fits=True, evidence_ids=['cause'], note='Синтетическая отрицательная проверка.'))
        final, code = self.app.handle(dict(owner='owner', action='finalize', request_id=out['request_id'],
                                          revision=out['revision'], candidate=candidate))
        self.assertEqual(code, 200)
        self.assertFalse(final['reply'])
        self.assertIn('fixed_reply_changed', final['validation'])

    def test_past_replacement_is_not_new_cartridge_work_but_explicit_order_stays_agreement(self):
        past = REPORT + ' Картриджи поменяли недавно, сначала всё было хорошо.'
        self.assertEqual(catalog.choose(past, KNOWN)['status'], 'supported')
        out, _ = self.preview([client('order', 'Нужно заменить картридж в принтере.')])
        self.assertEqual(out['action'], 'handoff')
        self.assertFalse(out.get('pending_model'))

    def test_closed_status_does_not_send_a_late_reminder(self):
        rows = self.trace() + [client('cause', 'Может ли быть проблема с драйверами?'),
                               staff('answer', 'Нужно проверить принтер.')]
        out, task = self.preview(rows, conversationStatus='closed')
        self.assertEqual(out['action'], 'wait')
        self.assertFalse(out.get('pending_model'))


if __name__ == '__main__':
    unittest.main()
