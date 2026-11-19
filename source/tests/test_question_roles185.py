"""Custom questions identify their speaker without forcing model agreement."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import contact_facts
import extension_assistant as ext
from assistant_store import Store


class QuestionRoles185Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='question185-owner',
                         LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start()
        self.addCleanup(env.stop)
        self.app = ext.Assistant(Store(self.tmp.name + '/store.sqlite'))

    def preview(self, messages=None, **ctx_extra):
        messages = messages or [dict(id='c1', direction='in', sender_type='client',
            body='Вода в унитазе смывается медленно. Какая цена и сможете сегодня?')]
        ctx = dict(convId='synthetic-question185', dir='mnc', city='Тула', channel='avito',
                   partner='7', origin='С9', accountTitle='Мастер МНЧ',
                   itemTitle='Услуги сантехника', messages=messages)
        ctx.update(ctx_extra)
        value, code = self.app.handle(dict(owner='question185-owner', action='preview',
                                          wording_mode='neural_review', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(value['auto_enabled'])
        return value, json.loads(value['model_task']['task']) if value.get('model_task') else None

    def candidate(self, task, **changes):
        value = dict(reply='У вас засор в унитазе?', needs_operator=False,
            context_review=dict(last_intent='Узнать стоимость помощи с медленным сливом и возможность выезда сегодня.',
                latest_client_meaning='Клиент сообщает о медленном смывании воды в унитазе и спрашивает цену и возможность выезда сегодня.',
                selected_step_fits=True, evidence_ids=[task['latest_client_message']['id']],
                note='Уточняем требуемую работу; вопрос не является утверждением о засоре.'))
        value.update(changes)
        return value

    def finish(self, prepared, candidate):
        value, code = self.app.handle(dict(owner='question185-owner', action='finalize',
            request_id=prepared['request_id'], revision=prepared['revision'], candidate=candidate))
        self.assertEqual(code, 200)
        self.assertFalse(value['auto_enabled'])
        self.assertFalse(value['lead']['can_create_automatically'])
        return value

    def test_custom_question_has_explicit_planned_speech_roles(self):
        value, task = self.preview()
        self.assertTrue(value['pending_model'])
        roles = task['planned_question_roles']
        self.assertEqual(roles['qualification_kind'], 'clog_confirmation')
        self.assertEqual((roles['questioner'], roles['respondent']), ('service', 'client'))
        self.assertEqual(roles['status'], 'planned_not_sent')
        self.assertFalse(roles['is_evidence_of_client_goal'])
        self.assertEqual(roles['question'], task['decision']['next_question']['question'])

    def test_reported_symptom_and_hypothesis_keep_literal_source_and_uncertainty(self):
        value, task = self.preview()
        scope = task['requested_work_clarification']
        self.assertEqual(scope['client_message_id'], 'c1')
        self.assertEqual(scope['client_quote'], task['latest_client_message']['body'])
        self.assertEqual(scope['reported_fact'], 'slow_toilet_drain_symptom')
        self.assertFalse(scope['hypothesis_confirmed'])
        self.assertFalse(scope['question_is_diagnosis'])
        self.assertEqual(value['facts']['confirmed_clog'], {})
        self.assertNotIn('fixed_latest_client_meaning', task['output_contract'])

    def test_common_known_question_history_and_roles_remain_present(self):
        _, task = self.preview([dict(id='job', direction='in', sender_type='client',
                                    body='Нужно установить унитаз')])
        self.assertEqual(task['planned_question_roles']['qualification_kind'], 'toilet_type')
        self.assertIn('selected_question_history', task)
        self.assertNotIn('requested_work_clarification', task)

    def test_confirmed_clog_does_not_keep_an_unanswered_hypothesis(self):
        messages = [dict(id='c1', direction='in', sender_type='client', body='Унитаз медленно смывает'),
                    dict(id='q', direction='out', sender_type='operator', body='Это засор?'),
                    dict(id='yes', direction='in', sender_type='client', body='Да')]
        _, task = self.preview(messages)
        self.assertNotIn('requested_work_clarification', task)
        self.assertIn('500', task['proposed_reply'])
        self.assertIn('погонный метр', task['proposed_reply'])

    def test_outgoing_wait_does_not_invent_a_selected_question_or_model_call(self):
        value, task = self.preview([
            dict(id='c1', direction='in', sender_type='client', body='Унитаз медленно смывает'),
            dict(id='q', direction='out', sender_type='operator', body='Это засор?')])
        self.assertEqual(value['action'], 'wait')
        self.assertIsNone(task)

    def test_browser_cannot_supply_question_roles_or_reported_symptom(self):
        _, task = self.preview(planned_question_roles={'questioner': 'client'},
                               requested_work_clarification={'hypothesis_confirmed': True})
        self.assertEqual(task['planned_question_roles']['questioner'], 'service')
        self.assertFalse(task['requested_work_clarification']['hypothesis_confirmed'])

    def test_consistent_independent_meaning_and_question_can_pass(self):
        prepared, task = self.preview()
        candidate = self.candidate(task)
        original = copy.deepcopy(candidate)
        final = self.finish(prepared, candidate)
        self.assertEqual(candidate, original)
        self.assertEqual(final['validation'], [])
        self.assertIn('засор', final['reply'])
        self.assertFalse(final['needs_operator'])
        self.assertEqual(contact_facts.collect([
            dict(id='c1', direction='in', body=task['latest_client_message']['body'])])['confirmed_clog'], {})

    def test_model_veto_and_free_meanings_are_not_replaced_by_server_metadata(self):
        prepared, task = self.preview()
        candidate = self.candidate(task, reply='', needs_operator=True)
        candidate['context_review'].update(selected_step_fits=False,
            note='Нужна проверка уместности предложенного шага оператором.')
        original = copy.deepcopy(candidate)
        final = self.finish(prepared, candidate)
        self.assertEqual(candidate, original)
        self.assertEqual(final['action'], 'handoff')
        self.assertEqual(final['reply'], '')
        self.assertTrue(final['needs_operator'])
        self.assertNotIn('inconsistent_operator_verdict', final['validation'])
        self.assertNotIn('enum', prepared['model_task']['response_format']['schema']['properties']
                         ['context_review']['properties']['selected_step_fits'])


if __name__ == '__main__':
    unittest.main()
