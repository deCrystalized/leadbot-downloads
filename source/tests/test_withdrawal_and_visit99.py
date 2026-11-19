"""581/22 and586/7: current client meaning outranks the old appointment."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from test_assistant import context, message
from assistant_store import Store
from extension_assistant import Assistant
import assistant_policy as policy
import contact_facts


class WithdrawalAndVisit99Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner', LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def preview(self, rows, neural=False):
        body = dict(owner='owner', action='preview', ctx=context(rows, dir='mnc', city='Бийск', itemTitle='Мастер на час'))
        if neural:
            body['wording_mode'] = 'neural_review'
        result, code = self.app.handle(body)
        self.assertEqual(code, 200)
        self.assertFalse(result['auto_enabled'])
        return result

    def test_explicit_future_withdrawal_is_a_decline_not_an_old_time_confirmation(self):
        text = 'Добрый вечер, извините пожалуйста😫🙏🙏💓 но мне теперь ваша помощь не понадобится'
        self.assertTrue(policy._client_declined(text, 'хорошо'))
        rows = [message('Повесить одну полку.'),
                message('Через час-полтора буду у вас', 'out', 'promise'),
                message('Хорошо жду', mid='accepted'), message('хорошо', 'out', 'staff'),
                message(text, mid='withdrawal')]
        out = self.preview(rows)
        self.assertEqual(out['action'], 'handoff')
        self.assertFalse(out['reply'])
        self.assertIn('отказался', out['reason'])
        self.assertEqual(out['client_decline_evidence']['message_id'], 'withdrawal')
        self.assertEqual(out['client_decline_evidence']['quote'], text)
        self.assertFalse(out['client_decline_evidence']['crm_cancellation_confirmed'])
        self.assertFalse(out['lead']['can_create_automatically'])

    def test_future_withdrawals_allow_politeness_but_not_conditional_partial_or_past_claims(self):
        for text in ['Ваша помощь не понадобится.', 'Спасибо! Ваша помощь нам больше не понадобится. Спасибо!',
                     'Ваши услуги мне уже не понадобятся.', 'Помощь мне теперь не потребуется.']:
            with self.subTest(text=text):
                self.assertTrue(policy._client_declined(text, 'Когда могу к вам приехать?'))
        for text in ['Если справлюсь, ваша помощь не понадобится.', 'Ваша помощь не понадобится?',
                     'Ваша помощь мне ещё понадобится.', 'Ваша помощь не понадобится с дверью, но с батареей нужна.',
                     'Его помощь не понадобится, нужна ваша.', 'Ваша помощь не понадобилась вчера.',
                     'Ваша помощь не понадобится, если придёт другой мастер.',
                     'Не думаю, что ваша помощь не понадобится.', 'Возможно, ваша помощь не понадобится.']:
            with self.subTest(text=text):
                self.assertFalse(policy._client_declined(text, 'Когда могу к вам приехать?'))

    def test_a_withdrawal_clears_old_requested_time_without_claiming_a_CRM_cancellation(self):
        rows = [message('Мне удобно завтра вечером', mid='old'),
                message('Ваша помощь мне теперь не понадобится', mid='withdrawal')]
        self.assertEqual(contact_facts.requested_visit(rows), {})

    def test_counterquestion_after_actual_visit_question_preserves_tomorrow(self):
        rows = [message('Мне в комнате надо сделать плинтус, вы сможете?', mid='job'),
                message('У вас все в наличии есть?', 'out', 'materials'), message('Да', mid='yes'),
                dict(message('Хорошо, когда вам будет удобно меня принять?', 'out', 'visit-question'),
                     sender_type='operator', delivery_status='sent'),
                message('Завтра сможете?', mid='tomorrow')]
        out = self.preview(rows, neural=True)
        fact = out['facts']['requested_visit']
        self.assertEqual(fact['window'], 'завтра')
        self.assertEqual(fact['question_message_id'], 'visit-question')
        self.assertEqual(fact['message_id'], 'tomorrow')
        self.assertFalse(fact['appointment_confirmed'])
        task = json.loads(out['model_task']['task'])
        self.assertIn('Учту пожелание: завтра.', task['proposed_reply'])
        self.assertNotRegex(task['proposed_reply'], r'приеду|записал|буду у вас')

    def test_short_day_question_does_not_become_a_visit_from_unrelated_or_unsent_prompts(self):
        for prompt in ['Когда сможете позвонить?', 'Когда вы купите материалы?',
                       'Когда вам удобно приехать к нам?', 'Когда удобно отправить фото?',
                       'На какое время записать звонок?', 'Когда вам удобно меня принять? Телефон есть?']:
            with self.subTest(prompt=prompt):
                rows = [message(prompt, 'out', 'prompt'), message('Завтра сможете?', mid='tomorrow')]
                self.assertEqual(contact_facts.requested_visit(rows), {})
        for delivery in ['failed', 'pending', 'queued', 'cancelled']:
            rows = [dict(message('Когда вам удобно меня принять?', 'out', 'prompt'),delivery_status=delivery),
                    message('Завтра сможете?', mid='tomorrow')]
            self.assertEqual(contact_facts.requested_visit(rows), {})

    def test_an_intervening_client_statement_does_not_answer_a_more_distant_staff_question(self):
        rows = [message('Когда вам удобно меня принять?', 'out', 'prompt'),
                message('Я сам завтра приеду за деталями.', mid='own-plan'),
                message('Завтра сможете?', mid='question')]
        self.assertEqual(contact_facts.requested_visit(rows), {})

    def test_neural_review_shows_the_actual_previous_question_not_its_planned_next_question(self):
        rows = [message('Нужно починить дверцу шкафа.', mid='job'),
                dict(message('Что у вас с ней?', 'out', 'actual-question'),sender_type='operator'),
                message('Непонятно', mid='answer')]
        out = self.preview(rows, neural=True)
        task = json.loads(out['model_task']['task'])
        exchange = task['latest_exchange']
        self.assertEqual(exchange['previous_staff_speech']['body'], 'Что у вас с ней?')
        self.assertEqual(exchange['previous_staff_speech']['evidence_id'], 'actual-question')
        self.assertEqual(exchange['client_message_evidence_id'], 'answer')
        self.assertEqual(exchange['source'], 'observed_turn_order')
        self.assertFalse(exchange['confirms_planned_action'])

