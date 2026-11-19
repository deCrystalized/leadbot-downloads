"""A model must review the last client's meaning, not just cite an older goal."""
from copy import deepcopy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from test_assistant import context, message
from assistant_store import Store, digest
from extension_assistant import Assistant


class LatestClientReview94Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner', LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))
        self.ctx = context([
            message('Нужно вставить замки в межкомнатные двери.', mid='job'),
            dict(message('Замок у вас в наличии уже?', 'out', 'availability'), sender_type='operator', delivery_status='sent'),
            message('Да', mid='confirmation'),
        ], dir='mnc', city='Екатеринбург', itemTitle='Мастер на час')

    def prepare(self, mode='neural_review'):
        out, code = self.app.handle(dict(owner='owner', action='preview', ctx=self.ctx, wording_mode=mode))
        self.assertEqual(code, 200)
        self.assertTrue(out.get('pending_model'), out.get('reason'))
        self.assertFalse(out['auto_enabled'])
        return out, json.loads(out['model_task']['task'])

    def candidate(self, task, **changes):
        value = dict(last_intent='Установить замки в межкомнатные двери.',
                     latest_client_meaning='Клиент подтверждает наличие замка.',
                     selected_step_fits=True, evidence_ids=['availability', 'confirmation'],
                     note='Материал двери ещё не уточнён.')
        value.update(changes)
        return dict(reply=task['decision']['next_question']['question'], needs_operator=False, context_review=value)

    def finish(self, out, candidate, **kwargs):
        final, code = self.app.handle(dict(owner='owner', action='finalize',
            request_id=out['request_id'], revision=out['revision'], candidate=candidate, **kwargs))
        self.assertEqual(code, 200)
        self.assertFalse(final['auto_enabled'])
        return final

    def test_latest_confirmation_is_pinned_without_treating_it_as_general_consent(self):
        out, task = self.prepare()
        self.assertEqual(task['latest_client_message'], dict(id='confirmation', position=2, evidence_id='confirmation',
                                                           body='Да', voice_transcript=''))
        self.assertEqual(task['context_review_version'], 2)
        self.assertEqual(out['qualification']['materials']['message_id'], 'confirmation')
        self.assertEqual(out['qualification']['materials']['value'], 'yes')
        final = self.finish(out, self.candidate(task))
        self.assertTrue(final['reply'])
        self.assertEqual(final['context_review']['latest_client_message_id'], 'confirmation')
        self.assertEqual(final['context_review']['latest_client_position'], 2)
        self.assertEqual(final['context_review']['source'], 'model_assertion_unverified')
        self.assertFalse(final['lead']['can_create_automatically'])
        self.assertEqual(final['validation'], [])

    def test_citing_only_the_initial_goal_cannot_approve_the_next_reply(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task, evidence_ids=['job']))
        self.assertFalse(final['reply'])
        self.assertEqual(final['action'], 'handoff')
        self.assertIn('latest_client_evidence_missing', final['validation'])

    def test_old_review_shape_cannot_claim_it_checked_the_latest_turn(self):
        out, task = self.prepare()
        candidate = self.candidate(task)
        del candidate['context_review']['latest_client_meaning']
        final = self.finish(out, candidate)
        self.assertFalse(final['reply'])
        self.assertIn('invalid_context_review', final['validation'])

    def test_whitespace_and_overlong_latest_meanings_are_rejected(self):
        for value in ('   ', 'а' * 201):
            with self.subTest(value=value):
                self.ctx['convId'] = 'meaning-' + str(len(value))
                out, task = self.prepare()
                final = self.finish(out, self.candidate(task, latest_client_meaning=value))
                self.assertFalse(final['reply'])
                self.assertIn('invalid_context_review', final['validation'])

    def test_notes_and_failed_staff_reply_do_not_replace_client_focus(self):
        self.ctx['messages'] += [dict(id='note', direction='note', body='Служебная пометка.'),
            dict(id='staff', direction='out', sender_type='operator', body='Сейчас посмотрю.', delivery_status='failed'),
            dict(id='system', direction='in', sender_type='system', body='Назначено сотруднику.')]
        _, task = self.prepare()
        self.assertEqual(task['latest_client_message']['id'], 'confirmation')
        self.assertEqual(task['latest_client_message']['position'], 2)

    def test_pending_staff_reply_prevents_another_model_reply(self):
        self.ctx['messages'].append(dict(id='staff', direction='out', sender_type='operator',
                                         body='Сейчас посмотрю.', delivery_status='pending'))
        out, code = self.app.handle(dict(owner='owner', action='preview', ctx=self.ctx, wording_mode='neural_review'))
        self.assertEqual(code, 200)
        self.assertEqual(out['action'], 'wait')
        self.assertFalse(out.get('pending_model'))
        self.assertFalse(out['reply'])

    def test_role_based_and_missing_id_messages_have_explicit_local_review_references(self):
        self.ctx['messages'][-1] = dict(role='user', content='Да')
        out, task = self.prepare()
        self.assertEqual(task['latest_client_message'], dict(id='', position=2, evidence_id='context-position:2',
                                                           body='Да', voice_transcript=''))
        final = self.finish(out, self.candidate(task, evidence_ids=['availability', 'context-position:2']))
        self.assertTrue(final['reply'])
        self.assertEqual(final['context_review']['latest_client_message_id'], '')
        self.assertEqual(final['context_review']['latest_client_position'], 2)

    def test_duplicate_transport_ids_require_an_unambiguous_position_reference(self):
        self.ctx['messages'][-1]['id'] = 'job'
        out, task = self.prepare()
        self.assertEqual(task['latest_client_message']['evidence_id'], 'context-position:2')
        final = self.finish(out, self.candidate(task, evidence_ids=['job']))
        self.assertFalse(final['reply'])
        self.assertIn('latest_client_evidence_missing', final['validation'])

    def test_unknown_position_is_not_a_valid_evidence_reference(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task, evidence_ids=['confirmation', 'context-position:999']))
        self.assertFalse(final['reply'])
        self.assertIn('invalid_context_review', final['validation'])

    def test_model_outage_does_not_approve_unreviewed_neural_context(self):
        out, _ = self.prepare()
        final = self.finish(out, {}, model_failure='transport')
        self.assertFalse(final['reply'])
        self.assertEqual(final['action'], 'handoff')
        self.assertEqual(final['response_source'], 'provider_error')
        self.assertEqual(final['code'], 'model_unavailable')
        self.assertEqual(final['model_status'], 'transport')
        self.assertIn('missing_context_review', final['validation'])

    def test_non_context_legacy_model_mode_keeps_the_two_key_protocol(self):
        with patch.dict(os.environ, LEADBOT_ASSISTANT_WORDING='model'):
            out, task = self.prepare(None)
        self.assertNotIn('context_review_version', task)
        final = self.finish(out, dict(reply=task['decision']['next_question']['question'], needs_operator=False))
        self.assertTrue(final['reply'])
        self.assertEqual(final['context_review_status'], 'not_supplied')

    def test_model_context_trace_is_logged_without_promoting_it_to_verified_fact(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task))
        with self.app.store.connect() as db:
            logged = json.loads(db.execute('SELECT payload FROM workflow_audit WHERE scope=? AND kind=? ORDER BY id DESC LIMIT 1',
                ('assistant:' + digest('owner'), 'draft')).fetchone()['payload'])
        self.assertEqual(logged['context_review'], final['context_review'])
        self.assertEqual(logged['context_review']['latest_client_meaning'], 'Клиент подтверждает наличие замка.')
        self.assertNotIn('model_task', logged)

    def test_changed_history_invalidates_an_old_model_explanation(self):
        out, task = self.prepare()
        changed = deepcopy(self.ctx)
        changed['messages'].append(message('Нет, замок ещё не куплен.', mid='correction'))
        self.app.handle(dict(owner='owner', action='observe', ctx=changed))
        final = self.finish(out, self.candidate(task))
        self.assertFalse(final['reply'])
        self.assertTrue(final['needs_operator'])
