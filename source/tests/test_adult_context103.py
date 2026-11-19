"""A model cannot turn a conditional adult visit into confirmed client consent."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from test_assistant import context
from test_adult_presence102 import history
from assistant_store import Store
from extension_assistant import Assistant


class AdultContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner', LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(self.tmp.name + '/db'))

    def prepare(self, messages=None):
        ctx = context(messages if messages is not None else history()[:4], channel='avito', dir='kp',
                      city='Тула', partner='7', itemTitle='Ремонт компьютеров')
        out, code = self.app.handle(dict(owner='owner', action='preview', ctx=ctx, wording_mode='neural_review'))
        self.assertEqual(code, 200)
        self.assertTrue(out['pending_model'])
        return out, json.loads(out['model_task']['task'])

    def candidate(self, task, state='possible', evidence='3', note='Когда взрослый сможет присутствовать, ещё не известно.'):
        return dict(reply=task.get('fixed_reply') or task['decision']['next_question']['question'], needs_operator=False,
                    context_review=dict(last_intent='Клиенту нужен ремонт компьютера с чёрным экраном.',
                        latest_client_meaning='Родители могут присутствовать, конкретное время ещё не подтверждено.',
                        evidence_ids=[task['latest_client_message']['evidence_id']], selected_step_fits=True, note=note,
                        adult_presence_review=dict(client_is_minor=True, status=state, evidence_id=evidence,
                                                   appointment_confirmed=False)))

    def finish(self, prepared, candidate):
        out, code = self.app.handle(dict(owner='owner', action='finalize', request_id=prepared['request_id'],
                                        revision=prepared['revision'], candidate=candidate))
        self.assertEqual(code, 200)
        self.assertFalse(out['auto_enabled'])
        self.assertFalse(out['lead']['can_create_automatically'])
        return out

    def test_task_requires_condition_review_with_latest_relevant_client_evidence(self):
        _, task = self.prepare()
        self.assertIn('adult_presence_review', task['output_contract']['context_review_fields'])
        self.assertEqual(task['adult_presence_condition']['evidence_id'], '3')
        self.assertEqual(task['adult_presence_condition']['status'], 'possible')

    def test_system_result_example_matches_the_required_condition_schema(self):
        out, task = self.prepare()
        system = out['model_task']['system']
        example, _ = json.JSONDecoder().raw_decode(system.split('Верни только JSON: ', 1)[1])
        self.assertEqual(set(example['context_review']), set(task['output_contract']['context_review_fields']))
        self.assertEqual(example['context_review']['adult_presence_review']['status'], 'possible')
        self.assertEqual(example['context_review']['adult_presence_review']['evidence_id'], '3')

    def test_grounded_possible_state_can_pass_without_becoming_booking(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task))
        self.assertFalse(final['needs_operator'])
        self.assertEqual(final['validation'], [])
        self.assertFalse(final['context_review']['adult_presence_review']['appointment_confirmed'])

    def test_legacy_model_review_without_condition_proof_cannot_approve_minor(self):
        out, task = self.prepare()
        candidate = self.candidate(task)
        candidate['context_review'].pop('adult_presence_review')
        final = self.finish(out, candidate)
        self.assertEqual(final['action'], 'handoff')
        self.assertFalse(final['reply'])

    def test_possibility_cannot_become_confirmation(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task, state='confirmed'))
        self.assertIn('adult_presence_review_mismatch', final['validation'])
        self.assertFalse(final['reply'])

    def test_parent_presence_does_not_make_the_client_an_adult(self):
        out, task = self.prepare()
        candidate = self.candidate(task)
        candidate['context_review']['adult_presence_review']['client_is_minor'] = False
        final = self.finish(out, candidate)
        self.assertIn('adult_presence_review_mismatch', final['validation'])

    def test_unverified_booking_is_never_confirmed_by_model_review(self):
        out, task = self.prepare()
        candidate = self.candidate(task)
        candidate['context_review']['adult_presence_review']['appointment_confirmed'] = True
        final = self.finish(out, candidate)
        self.assertIn('adult_presence_review_mismatch', final['validation'])

    def test_valid_but_unrelated_evidence_is_not_condition_evidence(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task, evidence='0'))
        self.assertIn('adult_presence_review_mismatch', final['validation'])

    def test_old_actual_false_confirmation_note_is_rejected_even_if_state_was_copied(self):
        out, task = self.prepare()
        candidate = self.candidate(task, note='Осмотр возможен только в присутствии взрослого, что было подтверждено клиентом ранее.')
        final = self.finish(out, candidate)
        self.assertIn('adult_presence_context_contradiction', final['validation'])
        self.assertEqual(final['action'], 'handoff')

    def test_explicitly_unconfirmed_note_does_not_trigger_false_contradiction(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task, note='Присутствие родителей пока не подтверждено. Нужно уточнить время.'))
        self.assertEqual(final['validation'], [])

    def test_confirmed_age_is_distinct_from_confirmed_parent_presence(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task, note='Возраст подтверждён: 16 лет. Время присутствия взрослого нужно уточнить.'))
        self.assertEqual(final['validation'], [])

    def test_withdrawn_confirmation_cannot_be_reused(self):
        messages = history() + [dict(id='9', direction='in', body='Родителей не будет дома оказывается')]
        out, task = self.prepare(messages)
        final = self.finish(out, self.candidate(task, state='confirmed', evidence='8'))
        self.assertIn('adult_presence_review_mismatch', final['validation'])

    def test_true_past_confirmation_and_current_withdrawal_can_be_described(self):
        messages = history() + [dict(id='9', direction='in', body='Родителей не будет дома оказывается')]
        out, task = self.prepare(messages)
        candidate = self.candidate(task, state='unavailable', evidence='9',
                                   note='Ранее присутствие родителей подтвердили, но теперь клиент сообщил, что их не будет.')
        candidate['context_review']['latest_client_meaning'] = 'Клиент отозвал присутствие родителей при визите.'
        final = self.finish(out, candidate)
        self.assertEqual(final['validation'], [])

    def test_changed_window_requires_fresh_condition_evidence(self):
        messages = history() + [dict(id='9', direction='in', body='Лучше завтра в 18')]
        out, task = self.prepare(messages)
        self.assertEqual(task['adult_presence_condition']['evidence_id'], '9')
        candidate = self.candidate(task, state='needs_reconfirmation', evidence='8')
        final = self.finish(out, candidate)
        self.assertIn('adult_presence_review_mismatch', final['validation'])

    def test_question_about_future_presence_is_not_an_assertion(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task, note='Нужно уточнить, будут ли родители дома.'))
        self.assertEqual(final['validation'], [])

    def test_past_confirmation_does_not_allow_a_new_false_current_confirmation(self):
        messages = history() + [dict(id='9', direction='in', body='Родителей не будет дома оказывается')]
        out, task = self.prepare(messages)
        candidate = self.candidate(task, state='unavailable', evidence='9',
                                   note='Ранее родители подтвердили присутствие, но теперь они точно будут дома.')
        final = self.finish(out, candidate)
        self.assertIn('adult_presence_context_contradiction', final['validation'])

    def test_unknown_age_does_not_gain_an_adult_condition_contract(self):
        _, task = self.prepare([dict(id='a', direction='in', body='У компьютера чёрный экран и курсор.')])
        self.assertNotIn('adult_presence_review', task['output_contract']['context_review_fields'])


if __name__ == '__main__':
    unittest.main()
