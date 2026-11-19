"""Answered coordination and explicit service-format questions stay causal."""
import unittest

import assistant_policy as policy
import contact_facts
from extension_assistant import _context_review
import test_caller_id189 as helper
import test_onsite_only114 as onsite


class CommunicationProgress192Tests(unittest.TestCase):
    known = helper.CallerId189Tests.known
    assess = helper.CallerId189Tests.assess

    def history(self, **delivery):
        return [helper.row('Напишите мне, я фото отправлю', ident='request'),
                helper.row('Здравствуйте!', ident='response', role='operator', **delivery),
                helper.row('Лесная 15 кв 1 п1', ident='address')]

    def progress(self, messages):
        return policy.photo_reply_progress(messages, self.known(), contact_facts.collect(messages, self.known()))

    def test_delivered_reply_and_new_address_wait_for_photo(self):
        out = self.assess(*self.history())
        self.assertEqual(out['action'], 'wait')
        self.assertFalse(out.get('forced_reply'))
        self.assertFalse(out.get('next_question'))
        self.assertFalse(out.get('accepted_visit'))
        self.assertFalse(out.get('crm_preparation'))

    def test_source_ids_preserved_without_upload_permission_claim(self):
        progress = self.progress(self.history())
        self.assertEqual(progress['request']['message_id'], 'request')
        self.assertEqual(progress['response']['message_id'], 'response')
        self.assertEqual(progress['status'], 'reply_observed_photo_pending')
        self.assertFalse(progress['upload_received'])
        self.assertFalse(progress['upload_permission_verified'])

    def test_unanswered_address_still_gets_invitation(self):
        rows = self.history();del rows[1]
        out = self.assess(*rows)
        self.assertEqual(out['forced_reply'], 'Пришлите, пожалуйста, фото.')
        self.assertIsNone(self.progress(rows))

    def test_failed_queued_pending_reply_does_not_fulfill_request(self):
        for delivery in [dict(out_pending=True)] + [dict(delivery_status=s) for s in
                ('failed', 'error', 'pending', 'queued', 'sending', 'cancelled', 'canceled')]:
            rows = self.history(**delivery)
            self.assertIsNone(self.progress(rows), delivery)
            self.assertEqual(self.assess(*rows)['forced_reply'], 'Пришлите, пожалуйста, фото.')

    def test_system_and_automation_are_not_staff_response(self):
        for role in ('system', 'avito', 'bot', 'assistant'):
            rows = self.history();rows[1]['sender_type'] = role
            self.assertIsNone(self.progress(rows), role)

    def test_quoted_or_empty_staff_text_not_response(self):
        for text in ('', 'Он сказал «Здравствуйте»', '«Жду»'):
            rows = self.history();rows[1]['body'] = text
            self.assertIsNone(self.progress(rows))

    def test_renewed_actual_unblock_request_needs_response(self):
        rows = self.history() + [helper.row('Не могу отправить фото, пока вы не напишите', ident='renewed')]
        self.assertIsNone(self.progress(rows))
        self.assertEqual(self.assess(*rows)['forced_reply'], 'Пришлите, пожалуйста, фото.')

    def test_new_price_question_does_not_wait_silently_for_photo(self):
        rows = self.history() + [helper.row('Сколько стоит собрать шкаф?', ident='price')]
        self.assertIsNone(self.progress(rows))
        self.assertEqual(self.assess(*rows)['action'], 'price')

    def test_new_enquiry_does_not_inherit_answered_photo_request(self):
        rows = self.history() + [helper.row('Новая заявка: заменить смеситель', ident='new')]
        self.assertIsNone(self.progress(rows))
        self.assertNotEqual(self.assess(*rows)['action'], 'wait')

    def test_received_image_ends_pending_photo(self):
        for metadata in (dict(attachments=[{'type': 'image'}]), dict(media_signature='viewed'), dict(media_reviewed=True)):
            rows = self.history() + [helper.row('', ident='image', **metadata)]
            self.assertIsNone(self.progress(rows))

    def test_staff_wait_is_not_client_wait_for_first_reply(self):
        rows = self.history();rows[1]['body'] = 'жду'
        self.assertTrue(self.progress(rows))
        self.assertEqual(self.assess(*rows)['action'], 'wait')

    def test_unrelated_named_job_retains_its_own_conditions(self):
        rows = self.history();rows[-1]['body'] += ', заменить газовую плиту'
        self.assertIsNone(self.progress(rows))
        self.assertEqual(self.assess(*rows)['action'], 'handoff')

    def task(self):
        return dict(context_review_version=2, conversation=[{'id': 'address'}],
                    latest_client_message={'id': 'address', 'position': 2, 'evidence_id': 'address'},
                    photo_reply_progress=self.progress(self.history()))

    def candidate(self):
        return dict(reply='Пришлите, пожалуйста, фото.', needs_operator=False,
                    context_review=dict(last_intent='Передать фото и адрес',
                        latest_client_meaning='Сообщил адрес', selected_step_fits=True,
                        evidence_ids=['address'], note='Сотрудник уже ответил, фото ещё ожидается'))

    def test_stale_prerequisite_rejected_in_every_free_field(self):
        for key in ('last_intent', 'latest_client_meaning', 'note', 'reply'):
            c = self.candidate()
            target = c if key == 'reply' else c['context_review']
            target[key] = 'Ожидает ответа для начала отправки фото'
            self.assertEqual(_context_review(c, self.task())[2], ['photo_first_reply_already_observed'], key)

    def test_correct_free_review_and_justified_veto_remain_independent(self):
        for veto in (False, True):
            c = self.candidate()
            if veto:
                c.update(reply='', needs_operator=True)
                c['context_review'].update(selected_step_fits=False, note='Фото ещё нет; лучше дождаться его')
            review, status, errors = _context_review(c, self.task())
            self.assertEqual(status, 'provided')
            self.assertEqual(review['selected_step_fits'], not veto)
            self.assertEqual(errors, ['model_context_mismatch'] if veto else [])

    def test_no_blanket_ban_on_waiting_for_new_answer_or_photo(self):
        for text in ('Ждёт фото', 'Клиент ждёт ответа о цене', 'Не ожидает ответа для отправки фото',
                     'Для отправки фото уже получил ответ сотрудника'):
            self.assertFalse(policy.photo_first_reply_pending_claim(text), text)
        c = self.candidate();c['context_review']['note'] = 'Клиент ждёт ответа для отправки фото'
        task = self.task();del task['photo_reply_progress']
        self.assertEqual(_context_review(c, task)[2], [])


class ServiceFormat192Tests(unittest.TestCase):
    def setUp(self):
        self.h = onsite.OnsiteOnly114Tests('test_direct_dropoff_question_receives_an_explicit_answer')
        self.h.setUp();self.addCleanup(self.h.doCleanups)

    def test_typo_and_standard_remote_questions_answer_before_contact(self):
        for text in ('Да чем раньше, тем лучше, вы работаете удалено или с выездом ?',
                     'Вы работаете удалённо?', 'Удаленно можно?', 'Дистанционно можете?'):
            out = self.h.preview(text)
            self.assertIn('Мастер выезжает на адрес к клиенту.', out['reply'])
            self.assertNotIn('Номер', out['reply'])
            self.assertFalse(out.get('accepted_visit'))
            self.assertFalse(out.get('crm_preparation'))

    def test_deleted_objects_quotes_negations_conditions_are_not_format_question(self):
        for text in ('Удалено приложение, можно вернуть?', 'Удалено фото, можете восстановить?',
                     'Он спросил «Вы работаете удалено?»', 'Если вы работаете удалено, я позже подумаю',
                     'Удалённо не нужно, потом напишу', 'Вы работаете с удалёнными файлами?'):
            self.assertFalse(policy._remote_service_question(text), text)

    def test_kp_format_not_transferred_to_mnc(self):
        out = self.h.preview('Вы работаете удалено или с выездом?', dir='mnc')
        self.assertNotIn('OWNER-KP-ONSITE-ONLY-20261020', out['rule_ids'])

    def test_multiclause_condition_and_report_do_not_become_current_question(self):
        for text in ('Если понадобится, вы работаете удалено?',
                     'Сосед спросил, вы работаете удалено?'):
            self.assertFalse(policy._remote_service_question(text), text)

    def test_statement_of_no_remote_service_is_not_a_renewed_question(self):
        self.assertFalse(policy._remote_service_question('Вы удалено не работаете, я понял.'))
        self.assertTrue(policy._remote_service_question('Вы не работаете удалённо?'))

    def test_remote_question_keeps_price_answer(self):
        out = self.h.preview('Сколько стоит? Вы работаете удалено или с выездом?')
        self.assertIn('Мастер выезжает на адрес к клиенту.', out['reply'])
        self.assertTrue(out.get('mandatory_price') or 'Стоимость' in out['reply'] or 'руб' in out['reply'])


if __name__ == '__main__':
    unittest.main()
