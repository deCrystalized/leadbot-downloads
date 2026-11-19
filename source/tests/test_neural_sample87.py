"""Regressions found by actual GigaChat previews; no network in unit tests."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant
import assistant_prices
import assistant_policy
import qualification_state


class NeuralSample87Tests(unittest.TestCase):
    def test_explicit_stop_and_slowness_symptoms_are_not_asked_again(self):
        for text in ('Компьютер перестал включаться.', 'Ноутбук очень медленно работает.',
                     'Принтер перестал печатать.'):
            state = qualification_state.inspect([dict(direction='in', body=text)])
            self.assertEqual(state['problem']['status'], 'answered', text)

    def test_price_dependence_is_not_a_reported_freezing_symptom(self):
        state = qualification_state.inspect([dict(direction='in', body='От чего зависит стоимость?')])
        self.assertEqual(state['problem']['status'], 'missing')

    def test_selected_room_question_cannot_become_a_question_about_area(self):
        decision = dict(action='draft', next_question=dict(kind='room',
            question='Работа нужна на кухне или в ванной?', groups=[['кухн','ванн']]))
        facts = dict(contact_phone_to_use='')
        self.assertIn('unselected_measurement_question', assistant_policy.validate_reply(
            'На какой площади необходим ремонт: кухня или ванна?', decision, facts))
        self.assertEqual(assistant_policy.validate_reply('Работа нужна на кухне или в ванной?', decision, facts), [])
        decision['next_question'] = dict(kind='area',question='Какая площадь помещения?',groups=[['площад']])
        self.assertEqual(assistant_policy.validate_reply('Какая площадь помещения?', decision, facts), [])

    def test_problem_question_is_not_replaced_by_a_model_example(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,
                LEADBOT_PERSONAL_OWNER_ID='offline-87', LEADBOT_ASSISTANT_WORDING='reviewed'):
            app = Assistant(Store(temp+'/db'))
            ctx = dict(convId='synthetic-pc87', city='Чита', dir='kp', partner='7', channel='avito',
                accountTitle='Денис КП', itemTitle='Компьютерный мастер',
                messages=[dict(id='in', direction='in', body='Нужна помощь с компьютером.')])
            pending, _ = app.handle(dict(owner='offline-87', action='preview', ctx=ctx, wording_mode='neural_review'))
            task = json.loads(pending['model_task']['task'])
            question = task['decision']['next_question']['question']
            self.assertEqual(task['decision']['next_question']['kind'], 'problem')
            self.assertEqual(task['output_contract']['example']['reply'], question)
            # Reproduce the actual rejected GigaChat answer. The semantic
            # guard must stay in place; only the misleading example changes.
            out, _ = app.handle(dict(owner='offline-87', action='finalize', ctx=ctx,
                request_id=pending['request_id'], revision=pending['revision'],
                candidate=dict(reply='Марку и модель подскажите?', needs_operator=False)))
            self.assertIn('required_question_missing', out['validation'])
            self.assertEqual(out['reply'], '')

    def test_client_reported_our_price_is_checked_without_inventing_a_prior_quote(self):
        for text in ('За сборку шкафа вы обещали 200 рублей, подтверждаете эту цену?',
                     'Вы мне раньше писали про стоимость. Всё ещё так?',
                     'Вы озвучили 1200 ₽, верно?'):
            self.assertTrue(assistant_prices.asks_to_confirm_previous_total([
                dict(direction='in', body=text)]), text)

    def test_other_technicians_price_and_nonprice_messages_do_not_become_our_promise(self):
        for text in ('Другой мастер обещал 200 рублей, сколько у вас?',
                     'Вы писали про номер дома, это дом 200?',
                     'Сколько стоит собрать шкаф?'):
            self.assertFalse(assistant_prices.asks_to_confirm_previous_total([
                dict(direction='in', body=text)]), text)

    def test_reported_price_does_not_start_new_order_collection(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,
                LEADBOT_PERSONAL_OWNER_ID='offline-87', LEADBOT_ASSISTANT_WORDING='reviewed'):
            ctx = dict(convId='synthetic-price87', city='Чита', dir='mnc', partner='7', channel='avito',
                accountTitle='Денис МНЧ', itemTitle='Сборка мебели',
                messages=[dict(id='in', direction='in', body='За сборку шкафа вы обещали 200 рублей, подтверждаете эту цену?')])
            out, _ = Assistant(Store(temp+'/db')).handle(dict(owner='offline-87', action='preview', ctx=ctx))
            self.assertEqual(out['action'], 'handoff')
            self.assertEqual(out['reply'], '')
            self.assertFalse(out['auto_enabled'])
