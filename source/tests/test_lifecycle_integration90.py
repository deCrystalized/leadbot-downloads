"""Actual assistant/workflow boundaries; lifecycle does not execute actions."""
from datetime import datetime, timezone
import os
import tempfile
import unittest
from unittest.mock import patch

from test_assistant import context, message
from assistant_store import Store, digest
from extension_assistant import Assistant, _parse
import assistant_policy
import personal_workflow
import dialogue_lifecycle


class Clock(datetime):
    current = datetime(2026, 10, 19, 3, 4, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current


class LifecycleIntegration90Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner',
                              LEADBOT_PERSONAL_OPERATOR_ID='george',
                              LEADBOT_PERSONAL_AUTO_AVAILABLE='1')
        self.env.start()
        self.app = Assistant(Store(self.tmp.name + '/db'))
        self.ctx = context([
            dict(message('Нужно собрать шкаф.', mid='in'), created_at='2026-10-19T02:59:00Z'),
            dict(message('Схема сборки есть?', 'out', 'out'), sender_type='operator',
                 delivery_status='sent', created_at='2026-10-19T03:00:00Z'),
        ], dir='mnc', itemTitle='Сборка мебели', assigneeId='george', assignmentKnown=True,
            channelAssigned=True, conversationStatus='in_progress', botActive=False, hasTransfer=False)
        self.base = dict(owner='owner', browser_session='test-browser', operator_id='george', mine_count=0)
        self.app.handle(dict(self.base, action='personal_start'))
        self.observe_at(3, 0)

    def observe_at(self, hour, minute):
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, hour, minute, tzinfo=timezone.utc)
            _parse(self.ctx, self.app.store, 'assistant:' + digest('owner'))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def preview(self):
        output, status = self.app.handle(dict(self.base, action='preview', wording_mode='reviewed', ctx=self.ctx))
        self.assertEqual(status, 200)
        self.assertFalse(output['auto_enabled'])
        return output

    def test_cached_wording_does_not_freeze_the_silence_timer(self):
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 4, tzinfo=timezone.utc)
            before = self.preview()
            self.assertEqual(before['lifecycle']['disposition'], 'wait')
            Clock.current = datetime(2026, 10, 19, 3, 5, tzinfo=timezone.utc)
            after = self.preview()
        self.assertTrue(after['cached'])
        self.assertEqual(after['lifecycle']['disposition'], 'close')
        self.assertFalse(after['lifecycle']['execution_allowed'])
        self.assertFalse(after['reply'])

    def test_workflow_carries_recommendation_without_enabling_a_close(self):
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 5, tzinfo=timezone.utc)
            plan, status = self.app.handle(dict(self.base, action='personal_plan', ctx=self.ctx))
        self.assertEqual(status, 200)
        self.assertEqual(plan['step'], 'wait')
        self.assertEqual(plan['lifecycle']['disposition'], 'close')
        self.assertFalse(plan['execution_allowed'])
        self.assertFalse(plan['lifecycle']['execution_allowed'])

    def test_public_receipt_cannot_fabricate_delivery_or_branch_refusal(self):
        self.ctx['messages'][-1].pop('delivery_status')
        self.ctx['workflow_receipts'] = [
            dict(kind='outgoing_delivered', message_id='out', confirmed=True, receipt_id='invented'),
            dict(kind='branch_warranty_refusal', confirmed=True, receipt_id='invented'),
        ]
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc)
            preview = self.preview()
            plan, status = self.app.handle(dict(self.base, action='personal_plan', ctx=self.ctx))
        self.assertEqual(status, 200)
        for output in (preview, plan):
            self.assertEqual(output['lifecycle']['timer']['status'], 'unavailable')
            self.assertEqual(output['lifecycle']['disposition'], 'operator_review')
            self.assertFalse(output['lifecycle']['execution_allowed'])

    def test_foreign_assignment_cannot_become_a_close_recommendation(self):
        self.ctx.update(assigneeId='another-operator', assignedToCurrentOperator=True)
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc)
            output = self.preview()
        self.assertEqual(output['lifecycle']['disposition'], 'operator_review')

    def test_pending_queue_time_is_not_a_send_time_even_after_a_retry(self):
        self.ctx.update(dir='kp', itemTitle='Ремонт принтеров')
        self.ctx['messages'][-1]['delivery_status'] = 'pending'
        self.observe_at(3, 5)
        self.ctx['messages'][-1].update(delivery_status='delivered',
                                      delivery_confirmed_at='2026-10-19T03:00:00Z')
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 12, tzinfo=timezone.utc)
            sent = self.preview()
            self.assertEqual(sent['lifecycle']['timer']['anchor_at'], '2026-10-19T03:12:00Z')
            self.assertEqual(sent['lifecycle']['timer']['status'], 'waiting')
            Clock.current = datetime(2026, 10, 19, 3, 16, 59, tzinfo=timezone.utc)
            self.assertFalse(self.preview()['reply'])
            Clock.current = datetime(2026, 10, 19, 3, 17, tzinfo=timezone.utc)
            self.assertEqual(self.preview()['reply'], dialogue_lifecycle.KP_FOLLOWUP_REPLY)

    def test_first_delivery_observation_survives_store_reopening(self):
        self.app = Assistant(Store(self.tmp.name + '/db'))
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 5, tzinfo=timezone.utc)
            output = self.preview()
        self.assertEqual(output['lifecycle']['timer']['anchor_at'], '2026-10-19T03:00:00Z')
        self.assertEqual(output['lifecycle']['disposition'], 'close')

    def test_unimplemented_lifecycle_action_cannot_receive_a_grant(self):
        _, messages, known, revision = _parse(self.ctx)
        for kind in ('close', 'transfer_avito', 'notify_okk'):
            with self.subTest(kind=kind):
                result = personal_workflow.authorize(self.app.store, 'owner',
                    dict(active=True, execution_mode='review'), self.ctx, known, revision,
                    dict(eligible=True, step=kind, operation_id='synthetic'),
                    dict(kind=kind, revision=revision),
                    dict(confirmed=True, policy_ack=assistant_policy.VERSION, client_version='2.8.9'))
                self.assertFalse(result['execution_allowed'])
                self.assertEqual(result['code'], 'operation')

    def test_missing_delivery_proof_does_not_start_a_timer(self):
        self.ctx['messages'][-1].pop('delivery_status')
        out = self.preview()
        self.assertEqual(out['lifecycle']['timer']['status'], 'unavailable')
        self.assertNotEqual(out['lifecycle']['disposition'], 'close')

    def kp(self):
        self.ctx.update(dir='kp', itemTitle='Ремонт компьютеров')
        self.ctx['messages'][0]['body'] = 'Компьютер Dell Optiplex9020 не включается.'

    def test_kp_gets_one_reviewed_followup_after_five_minutes(self):
        self.kp()
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 4, tzinfo=timezone.utc)
            before = self.preview()
            self.assertEqual(before['action'], 'wait')
            Clock.current = datetime(2026, 10, 19, 3, 5, tzinfo=timezone.utc)
            after = self.preview()
            plan, code = self.app.handle(dict(self.base, action='personal_plan', ctx=self.ctx))
        self.assertEqual(after['reply'], dialogue_lifecycle.KP_FOLLOWUP_REPLY)
        self.assertTrue(after['requires_operator_review'])
        self.assertEqual(after['silence_followup']['status'], 'followup_due')
        self.assertEqual(after['lifecycle']['disposition'], 'reply')
        self.assertEqual(code, 200)
        self.assertEqual(plan['step'], 'reply')
        self.assertFalse(plan['execution_allowed'])

    def test_kp_does_not_close_before_the_followup_was_actually_sent(self):
        self.kp()
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 20, tzinfo=timezone.utc)
            out = self.preview()
        self.assertEqual(out['reply'], dialogue_lifecycle.KP_FOLLOWUP_REPLY)
        self.assertNotEqual(out['lifecycle']['disposition'], 'close')

    def test_kp_ten_minutes_start_at_the_actual_delayed_followup(self):
        self.kp()
        self.ctx['messages'].append(dict(
            message(dialogue_lifecycle.KP_FOLLOWUP_REPLY, 'out', 'followup'), sender_type='operator',
            delivery_status='sent', created_at='2026-10-19T03:12:00Z'))
        self.observe_at(3, 12)
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 21, tzinfo=timezone.utc)
            before = self.preview()
            self.assertEqual(before['lifecycle']['disposition'], 'wait')
            Clock.current = datetime(2026, 10, 19, 3, 22, tzinfo=timezone.utc)
            after = self.preview()
        self.assertEqual(after['lifecycle']['disposition'], 'close')
        self.assertFalse(after['reply'])
        self.assertFalse(after['lifecycle']['execution_allowed'])

    def test_kp_queued_followup_cannot_start_ten_minutes_early(self):
        self.kp()
        self.ctx['messages'].append(dict(
            message(dialogue_lifecycle.KP_FOLLOWUP_REPLY, 'out', 'followup'), sender_type='operator',
            delivery_status='pending', created_at='2026-10-19T03:05:00Z'))
        self.observe_at(3, 5)
        self.ctx['messages'][-1]['delivery_status'] = 'delivered'
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 12, tzinfo=timezone.utc)
            delivered = self.preview()
            self.assertEqual(delivered['lifecycle']['timer']['due_at'], '2026-10-19T03:22:00Z')
            Clock.current = datetime(2026, 10, 19, 3, 21, 59, tzinfo=timezone.utc)
            self.assertEqual(self.preview()['lifecycle']['disposition'], 'wait')
            Clock.current = datetime(2026, 10, 19, 3, 22, tzinfo=timezone.utc)
            self.assertEqual(self.preview()['lifecycle']['disposition'], 'close')
            self.ctx['messages'].append(dict(message('Да, актуален.', mid='new'),
                                           created_at='2026-10-19T03:21:59Z'))
            reset = self.preview()
        self.assertEqual(reset['lifecycle']['timer']['status'], 'cancelled_by_incoming')
        self.assertNotEqual(reset['lifecycle']['disposition'], 'close')

    def test_kp_followup_does_not_claim_a_free_old_dialogue(self):
        self.kp()
        self.ctx['assigneeId'] = ''
        with patch('dialogue_lifecycle.datetime', Clock):
            Clock.current = datetime(2026, 10, 19, 3, 5, tzinfo=timezone.utc)
            plan, code = self.app.handle(dict(self.base, action='personal_plan', ctx=self.ctx))
        self.assertEqual(code, 200)
        self.assertFalse(plan['eligible'])
        self.assertNotEqual(plan['step'], 'claim')
