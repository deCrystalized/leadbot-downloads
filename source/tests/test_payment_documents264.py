"""Document files and payment paperwork have different causal subjects.

No provider, customer, CRM or Telegram action is exercised here.
"""
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))

import assistant_policy as policy
import contact_facts
import personal_workflow
from assistant_store import Store
from extension_assistant import Assistant, _parse


INITIAL = ('Здравствуйте. На ноутбуке с Windows 11 перестали открываться Word и Excel: '
           'пишут, что не удалось запустить приложение. Документы важные, удалять их нельзя. '
           'Это можно исправить без потери файлов?')


def msg(body, mid='c1', direction='in', **extra):
    return dict(id=mid, body=body, direction=direction, **extra)


class PaymentDocumentSubject264Tests(unittest.TestCase):
    def question(self, *rows):
        return policy._document_question(list(rows))

    def test_existing_word_excel_failure_does_not_ask_for_a_cash_receipt(self):
        self.assertIsNone(self.question(msg(INITIAL)))

    def test_save_error_is_about_the_clients_file(self):
        self.assertIsNone(self.question(msg('Excel не сохраняет документ. Что делать?')))

    def test_software_installation_and_needed_files_do_not_order_payment_paperwork(self):
        self.assertIsNone(self.question(msg('Нужно поставить Word. Документы с ноутбука нужны, не удаляйте их. Сможете?')))

    def test_document_recovery_is_not_issuance_of_new_paperwork(self):
        self.assertIsNone(self.question(msg('Можете восстановить удалённые документы?')))

    def test_printed_documents_are_not_receipts(self):
        self.assertIsNone(self.question(msg('Принтер не печатает документы. Можно исправить?')))

    def test_payment_content_of_a_file_does_not_order_payment_paperwork(self):
        self.assertIsNone(self.question(msg('Документ об оплате в Word не сохраняется, можно починить?')))

    def test_another_document_request_survives_withdrawal_of_the_first_type(self):
        row = self.question(msg('Квитанция не нужна, а кассовый чек нужен.'))
        self.assertTrue(row['explicit_type'])

    def test_past_receipt_statement_does_not_borrow_a_later_file_question(self):
        self.assertIsNone(self.question(msg('Раньше мне выдали чек. Сейчас можно восстановить документы Word?')))

    def test_issuance_without_question_mark_still_requires_clarification(self):
        self.assertIsNotNone(self.question(msg('После работы предоставите документы.')))

    def test_generic_observed_human_promise_is_not_lost(self):
        row = self.question(msg('Документы выдаёте?'), msg('Да, документ будет.', 'o1', 'out', sender_type='operator'))
        self.assertEqual(row['staff_answer'], 'Да, документ будет.')

    def test_generic_issuance_question_still_requires_document_clarification(self):
        row = self.question(msg('Вы документы выдаёте после работы?'))
        self.assertEqual(row['message_id'], 'c1')
        self.assertFalse(row['explicit_type'])

    def test_accounting_document_request_survives_a_software_subject(self):
        row = self.question(msg('Нужен ремонт Word и документы об оплате для бухгалтерии.'))
        self.assertIsNotNone(row)

    def test_named_fiscal_type_is_not_a_general_file_question(self):
        for text in ('Нужен кассовый чек', 'Выдаёте БСО?'):
            with self.subTest(text=text):
                self.assertTrue(self.question(msg(text))['explicit_type'])

    def test_unanswered_receipt_question_survives_later_file_information(self):
        row = self.question(msg('Квитанцию даёте?'), msg('Документы с компьютера важные, сохранятся?', 'c2'))
        self.assertEqual(row['message_id'], 'c1')

    def test_actual_receipt_withdrawal_releases_its_block(self):
        self.assertIsNone(self.question(msg('Квитанцию даёте?'), msg('Квитанция не нужна.', 'c2')))

    def test_negative_file_statement_does_not_withdraw_an_unrelated_receipt(self):
        row = self.question(msg('Квитанцию даёте?'), msg('Электронные документы не нужны, восстановить только фотографии.', 'c2'))
        self.assertEqual(row['message_id'], 'c1')

    def test_real_receipt_question_is_not_lost_because_same_turn_mentions_files(self):
        row = self.question(msg('Документы Word удалять нельзя. А кассовый чек Вы выдаёте?'))
        self.assertTrue(row['explicit_type'])

    def test_reported_receipt_question_does_not_become_the_clients_request(self):
        self.assertIsNone(self.question(msg('Сосед спросил: «Вы выдаёте кассовый чек?» У меня Word не открывается.')))

    def test_quoted_fiscal_name_in_a_real_question_remains_a_request(self):
        self.assertTrue(self.question(msg('Вы выдаёте «кассовый чек»?'))['explicit_type'])

    def test_service_or_operator_incoming_alias_cannot_supply_client_intent(self):
        for role in ('system', 'operator', 'bot', 'automation'):
            with self.subTest(role=role):
                self.assertIsNone(self.question(msg('Нужен кассовый чек?', sender_type=role)))

    def test_explicit_service_speaker_or_system_role_is_not_a_client_request(self):
        for extra in (dict(speaker_role='service'), dict(role='system'), dict(role='assistant')):
            with self.subTest(extra=extra):
                self.assertIsNone(self.question(msg('Нужен кассовый чек?', **extra)))

    def test_pending_flag_without_a_status_cannot_supply_speech_or_a_promise(self):
        self.assertIsNone(self.question(msg('Нужен кассовый чек?', out_pending=True)))
        row = self.question(msg('Квитанцию даёте?'), msg('Квитанция будет.', 'o1', 'out', out_pending=True))
        self.assertNotIn('staff_answer', row)

    def test_failed_or_pending_incoming_question_is_not_delivered_client_speech(self):
        for status in ('failed', 'pending', 'queued'):
            with self.subTest(status=status):
                self.assertIsNone(self.question(msg('Нужен БСО?', delivery_status=status)))

    def test_observed_human_promise_remains_a_commitment_to_check(self):
        row = self.question(msg('Документы выдаёте?'), msg('Выдам квитанцию.', 'o1', 'out', sender_type='operator', delivery_status='delivered'))
        self.assertEqual(row['staff_answer'], 'Выдам квитанцию.')

    def test_failed_or_automated_outgoing_text_does_not_prove_a_human_promise(self):
        for extra in (dict(delivery_status='failed'), dict(sender_type='system'), dict(sender_type='bot')):
            with self.subTest(extra=extra):
                row = self.question(msg('Квитанцию даёте?'), msg('Квитанция выдана.', 'o1', 'out', **extra))
                self.assertNotIn('staff_answer', row)

    def test_generic_payment_documents_can_be_explicitly_withdrawn(self):
        self.assertIsNone(self.question(msg('Документы выдаёте?'), msg('Документы не нужны.', 'c2')))

    def test_assistant_preserves_ordinary_software_scope_in_full_initial_message(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,
                LEADBOT_PERSONAL_AUTO_AVAILABLE='0', LEADBOT_ASSISTANT_WORDING='reviewed'):
            app = Assistant(Store(str(Path(tmp) / 'assistant.sqlite3')))
            ctx = dict(convId='synthetic-files264', messages=[msg(INITIAL)], dir='kp',
                partner='7', city='Чита', accountTitle='Георгий КП', itemTitle='Компьютерная помощь', origin='С1')
            result, code = app.handle(dict(owner='synthetic264', action='preview', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertNotRegex(result['reply'] + result['reason'], 'БСО|кассов|квитанц')
        self.assertNotRegex(result['reply'], 'модель|операционн|какая.*Windows')
        self.assertFalse(result['auto_enabled'])

    def test_workflow_does_not_handoff_an_ordinary_software_case_for_false_paperwork(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(str(Path(tmp) / 'assistant.sqlite3'))
            ctx = dict(convId='synthetic-workflow264', messages=[msg(INITIAL)], dir='kp',
                partner='7', city='Чита', accountTitle='Георгий КП', itemTitle='Компьютерная помощь',
                origin='С1', assigneeId='actor264', assignmentKnown=True, conversationStatus='in_progress',
                botActive=False, hasTransfer=False, channelAssigned=True)
            _, rows, known, revision = _parse(ctx, store, 'synthetic264')
            decision = policy.assess(rows, known, contact_facts.collect(rows, known))
            plan = personal_workflow.plan_for_actor(rows, known, ctx, 'actor264', 0, revision)
        self.assertNotIn('forced_reply', decision)
        self.assertTrue(plan['eligible'], plan)
        self.assertEqual(plan['step'], 'reply')
        self.assertFalse(plan['execution_allowed'])


if __name__ == '__main__':
    unittest.main()
