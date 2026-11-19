"""A queued question and a service event are not the first delivered reply."""
import copy
import unittest
from unittest.mock import patch

import assistant_policy as policy
import contact_facts
import test_native_wording209 as native_fixture
import test_workflow as workflow_fixture


SOURCE = dict(channel='avito', direction='mnc', city='Чита', partner='7',
              title='Сантехника', direction_source='source', origin='С1')


def client(mid='client', body='Нужно заменить два смесителя в ванной. Материалы есть.'):
    return dict(id=mid, direction='in', sender_type='client', body=body)


def outgoing(**extra):
    return dict(id='staff', direction='out', sender_type='operator',
                body='Телефон подскажите?', **extra)


def decision(rows):
    return policy.assess(rows, SOURCE, contact_facts.collect(rows, SOURCE))


class GreetingDelivery256Tests(unittest.TestCase):
    def test_explicitly_unavailable_sends_do_not_suppress_first_greeting(self):
        for status in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled'):
            with self.subTest(status=status):
                rows = [client(), outgoing(delivery_status=status), client('reminder', '?')]
                original = copy.deepcopy(rows)
                result = decision(rows)
                self.assertTrue(result['greeting_required'])
                self.assertTrue(result['greeting_allowed'])
                self.assertEqual(rows, original)

    def test_legacy_delivery_field_and_case_are_respected(self):
        result = decision([client(), outgoing(delivery='PENDING')])
        self.assertTrue(result['greeting_required'])

    def test_pending_marker_overrides_a_delivery_label(self):
        result = decision([client(), outgoing(delivery_status='delivered', out_pending=True)])
        self.assertTrue(result['greeting_required'])

    def test_service_role_cannot_count_as_delivered_staff_speech(self):
        for fields in (dict(sender_type='system'), dict(sender_type='avito'),
                       dict(role='system'), dict(speaker_role='service')):
            with self.subTest(fields=fields):
                row = dict(outgoing(delivery_status='delivered'), **fields)
                self.assertTrue(decision([client(), row])['greeting_required'])

    def test_delivered_human_reply_prevents_a_repeated_greeting(self):
        for status in ('delivered', 'read'):
            with self.subTest(status=status):
                result = decision([client(), outgoing(delivery_status=status), client('last', 'Да')])
                self.assertFalse(result['greeting_required'])
                self.assertFalse(result['greeting_allowed'])

    def test_delivered_bot_reply_prevents_a_repeated_greeting(self):
        row = dict(outgoing(delivery_status='delivered'), sender_type='bot')
        self.assertFalse(decision([client(), row])['greeting_required'])

    def test_legacy_outgoing_without_delivery_keeps_compatibility(self):
        self.assertFalse(decision([client(), outgoing()])['greeting_required'])

    def test_client_quote_of_a_greeting_is_not_our_reply(self):
        row = client('quote', 'Сосед написал «Здравствуйте». Нужно заменить два смесителя.')
        self.assertTrue(decision([row])['greeting_required'])

    def test_unavailable_question_does_not_erase_a_real_previous_reply(self):
        rows = [client(), outgoing(delivery_status='delivered'),
                dict(outgoing(delivery_status='pending'), id='pending'), client('last', '?')]
        self.assertFalse(decision(rows)['greeting_required'])

    def test_required_first_greeting_is_composed_once_without_changing_question(self):
        result = decision([client(), outgoing(delivery_status='pending')])
        reply = policy.compose_reply('Это квартира или частный дом?', result)
        self.assertTrue(reply.startswith('Здравствуйте! '))
        self.assertEqual(reply.count('Здравствуйте'), 1)
        self.assertIn('Это квартира или частный дом?', reply)


class NativeGreetingDelivery256Tests(unittest.TestCase):
    setUp = native_fixture.NativeWording209Tests.setUp
    tearDown = native_fixture.NativeWording209Tests.tearDown
    prepare = native_fixture.NativeWording209Tests.prepare
    finish = native_fixture.NativeWording209Tests.finish

    def source(self):
        self.ctx['messages'] = [client(body='Нужно собрать комод. Схема, все детали и крепёж есть.'),
            client('question', 'Как это происходит'), outgoing(delivery_status='pending'),
            client('reminder', '?')]
        return self.prepare()

    def test_real_native_preview_requires_first_greeting_after_pending_question(self):
        _, task = self.source()
        self.assertTrue(task['decision']['greeting_allowed'])
        self.assertTrue(task['proposed_reply'].startswith('Здравствуйте! '))
        self.assertEqual(task['intake_question_context']['query_message_ids'], ['question', 'reminder'])
        self.assertFalse(task['facts']['phone_received'])
        self.assertEqual(task['facts']['address_fields'], [])

    def test_finalize_keeps_original_candidate_and_adds_required_greeting(self):
        prepared, _ = self.source()
        candidate = dict(reply='Это квартира или частный дом?', needs_operator=False,
            context_review=dict(last_intent='Собрать комод и узнать порядок обращения.',
                latest_client_meaning='Клиент напоминает вопрос о порядке работы.',
                selected_step_fits=True, evidence_ids=['question', 'reminder'],
                note='Неотправленный вопрос сотрудника не ответил клиенту.'))
        original = copy.deepcopy(candidate)
        out = self.finish(prepared, candidate)
        self.assertEqual(candidate, original)
        self.assertFalse(out['validation'])
        self.assertFalse(out['needs_operator'])
        self.assertTrue(out['reply'].startswith('Здравствуйте! '))
        self.assertIn('выезд', out['reply'].lower())


class GreetingAuthorization256Tests(unittest.TestCase):
    setUp = workflow_fixture.WorkflowTests.setUp
    tearDown = workflow_fixture.WorkflowTests.tearDown
    call = workflow_fixture.WorkflowTests.call
    ctx = workflow_fixture.WorkflowTests.ctx
    operation = workflow_fixture.WorkflowTests.operation
    review_confirmation = workflow_fixture.WorkflowTests.review_confirmation

    def test_send_authority_rejects_missing_greeting_after_pending_staff_send(self):
        ctx = self.ctx()
        ctx['messages'].append(outgoing(delivery_status='pending'))
        ctx['messages'].append(client('reminder', '?'))
        draft = self.call('preview', ctx=ctx)
        operation = self.operation(ctx, 'reply', draft_id=draft['draft_id'], reply='Марку и модель подскажите?')
        with patch.dict('os.environ', {'LEADBOT_PERSONAL_AUTO_AVAILABLE': '1'}), \
                patch.object(self.app.store, 'draft', return_value={**draft, 'reply': 'Марку и модель подскажите?'}):
            out = self.call('personal_review_authorize', ctx=ctx, operation=operation,
                            **self.review_confirmation())
        self.assertFalse(out['ok'])
        self.assertEqual(out['code'], 'greeting')
        self.assertFalse(out['execution_allowed'])
