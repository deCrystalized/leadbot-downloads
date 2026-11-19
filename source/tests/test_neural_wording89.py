"""Actual GigaChat additions must not change a selected qualification question."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant


class NeuralWording89Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='offline-89', LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(self.temp.name+'/db'))

    def complete(self, text, direction, candidate=None):
        ctx = dict(convId='synthetic-wording89', city='Чита', dir=direction, partner='7', channel='avito',
            accountTitle='Денис', itemTitle='Мастер на час' if direction=='mnc' else 'Компьютерный мастер',
            messages=[dict(id='in', direction='in', body=text)])
        prepared, _ = self.app.handle(dict(owner='offline-89',action='preview',ctx=ctx,wording_mode='neural_review'))
        question = json.loads(prepared['model_task']['task'])['decision']['next_question']['question']
        candidate = dict(candidate or dict(reply=question, needs_operator=False), context_review=dict(
            last_intent='Клиент просит услугу.', latest_client_meaning=text,
            selected_step_fits=True, evidence_ids=['in'], note='Сведения для выбранного вопроса не получены.'))
        out, _ = self.app.handle(dict(owner='offline-89',action='finalize',ctx=ctx,
            request_id=prepared['request_id'],revision=prepared['revision'],
            candidate=candidate))
        return out, question

    def test_unknown_rooms_are_not_added_to_wall_material_question(self):
        out, question = self.complete('Нужно повесить полку.','mnc',
            dict(reply='Какой материал стен в помещении кухни или ванной?',needs_operator=False))
        self.assertEqual(out['reply'],'Здравствуйте! '+question)
        self.assertEqual(out['response_source'],'server_template')
        self.assertEqual(out['model_status'],'unreviewed_wording')
        self.assertNotIn('кухн',out['reply'])
        self.assertTrue(out['requires_operator_review'])
        self.assertFalse(out['auto_enabled'])

    def test_unknown_apartment_is_not_added_to_internet_question(self):
        out, question = self.complete('Нужно настроить роутер TP-Link Archer A6.','kp',
            dict(reply='Проведен ли интернет в вашу квартиру?',needs_operator=False))
        self.assertEqual(out['reply'],'Здравствуйте! '+question)
        self.assertNotIn('квартир',out['reply'])
        self.assertEqual(out['response_source'],'server_template')

    def test_approved_question_remains_a_model_draft(self):
        out, question = self.complete('Нужно повесить полку.','mnc')
        self.assertEqual(out['reply'],'Здравствуйте! '+question)
        self.assertEqual(out['response_source'],'model')
        self.assertEqual(out['validation'],[])

    def test_unsafe_promise_is_blocked_instead_of_hidden_by_fallback(self):
        out, _ = self.complete('Нужно повесить полку.','mnc',
            dict(reply='Уже отправил мастера. Какой материал стен?',needs_operator=False))
        self.assertEqual(out['reply'],'')
        self.assertEqual(out['action'],'handoff')
        self.assertIn('unconfirmed_action_or_visit',out['validation'])
        self.assertNotEqual(out.get('model_status'),'unreviewed_wording')

    def test_model_operator_request_is_preserved(self):
        out, _ = self.complete('Нужно повесить полку.','mnc',dict(reply='',needs_operator=True))
        self.assertEqual(out['reply'],'')
        self.assertTrue(out['needs_operator'])
        self.assertEqual(out['action'],'handoff')
