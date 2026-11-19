"""Observed979 failures: no invented previous question, no relaxed output limits."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant
from test_assistant import context, message


class ModelHistory107Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def prepare(self, between=()):
        messages = [message('Сколько стоит отремонтировать дверцу шкафа?', mid='job'),
                    *between, message('Живу на Фрунзе', mid='address')]
        ctx = context(messages, dir='mnc', city='Туапсе', itemTitle='Мастер на час')
        out, code = self.app.handle(dict(owner='owner', action='preview', ctx=ctx, wording_mode='neural_review'))
        self.assertEqual(code, 200)
        self.assertTrue(out.get('pending_model'), out.get('reason'))
        return out, json.loads(out['model_task']['task'])

    def finish(self, out, task, meaning='Клиент уточняет улицу, сохраняя запрос ремонта.', note='Нужен ответ о цене и текущий вопрос.'):
        review = dict(last_intent='Узнать стоимость ремонта дверцы шкафа.',
                      latest_client_meaning=meaning, selected_step_fits=True,
                      evidence_ids=['address'], note=note)
        candidate = dict(reply=task.get('fixed_reply') or task['decision']['next_question']['question'],
                         needs_operator=False, context_review=review)
        final, code = self.app.handle(dict(owner='owner', action='finalize', request_id=out['request_id'],
                                          revision=out['revision'], candidate=candidate))
        self.assertEqual(code, 200)
        self.assertFalse(final['auto_enabled'])
        return final

    def test_planned_question_is_explicitly_not_observed_staff_speech(self):
        _, task = self.prepare()
        self.assertFalse(task['history_coverage']['prior_staff_speech_exists'])
        self.assertEqual(task['proposed_reply_status'], 'planned_not_sent')
        self.assertNotIn('latest_exchange', task)

    def test_invented_previously_asked_question_is_rejected(self):
        out, task = self.prepare()
        final = self.finish(out, task, 'Клиент уточнил адрес проживания, но не ответил на предыдущий вопрос о материалах и комплектующих.')
        self.assertEqual(final['action'], 'handoff')
        self.assertFalse(final['reply'])
        self.assertIn('unobserved_prior_staff_question', final['validation'])

    def test_true_initial_meaning_remains_usable(self):
        out, task = self.prepare()
        final = self.finish(out, task)
        self.assertTrue(final['reply'])
        self.assertEqual(final['validation'], [])

    def test_real_delivered_question_can_ground_unanswered_question(self):
        prior = dict(message('Материалы и комплектующие есть?', 'out', 'question'),
                     sender_type='operator', delivery_status='delivered')
        out, task = self.prepare([prior])
        self.assertTrue(task['history_coverage']['prior_staff_speech_exists'])
        final = self.finish(out, task, 'Клиент назвал улицу, но не ответил на предыдущий вопрос о материалах.')
        self.assertTrue(final['reply'])
        self.assertNotIn('unobserved_prior_staff_question', final['validation'])

    def test_failed_question_does_not_make_an_observed_question(self):
        prior = dict(message('Материалы и комплектующие есть?', 'out', 'question'),
                     sender_type='operator', delivery_status='failed')
        out, task = self.prepare([prior])
        self.assertFalse(task['history_coverage']['prior_staff_speech_exists'])
        final = self.finish(out, task, 'Клиент не ответил на предыдущий вопрос о материалах.')
        self.assertIn('unobserved_prior_staff_question', final['validation'])

    def test_service_event_does_not_make_observed_staff_speech(self):
        out, task = self.prepare([dict(id='service', direction='system', sender_type='system', body='Диалог принят')])
        self.assertFalse(task['history_coverage']['prior_staff_speech_exists'])
        self.assertTrue(self.finish(out, task)['reply'])

    def test_two_client_messages_do_not_erase_earlier_staff_question(self):
        prior = dict(message('Материалы и комплектующие есть?', 'out', 'question'),
                     sender_type='operator', delivery_status='delivered')
        out, task = self.prepare([prior, message('Могу принять вечером', mid='visit')])
        self.assertTrue(task['history_coverage']['prior_staff_speech_exists'])
        final = self.finish(out, task, 'Клиент назвал улицу, но не ответил на предыдущий вопрос о материалах.')
        self.assertNotIn('unobserved_prior_staff_question', final['validation'])

    def test_output_contract_exposes_existing_hard_limits(self):
        _, task = self.prepare()
        self.assertEqual(task['output_contract']['context_review_max_lengths'],
                         dict(last_intent=200, latest_client_meaning=200, note=200))

    def test_overlong_note_is_rejected_without_truncation_or_relaxed_limit(self):
        out, task = self.prepare()
        final = self.finish(out, task, note='а' * 201)
        self.assertEqual(final['action'], 'handoff')
        self.assertFalse(final['reply'])
        self.assertIn('invalid_context_review', final['validation'])


if __name__ == '__main__':
    unittest.main()
