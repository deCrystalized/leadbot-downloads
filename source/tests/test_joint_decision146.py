"""A coherent answer or a justified handoff; never repair a model verdict."""
import copy
import itertools
import unittest

import test_diagnostic_reasoning119 as helpers
from extension_assistant import _response_consistency_errors


class JointDecision146Tests(unittest.TestCase):
    setUp = helpers.DiagnosticReasoning119Tests.setUp
    prepare = helpers.DiagnosticReasoning119Tests.prepare
    candidate = helpers.DiagnosticReasoning119Tests.candidate
    finish = helpers.DiagnosticReasoning119Tests.finish

    def test_model_receives_both_joint_states_without_forced_acceptance(self):
        prepared, task = self.prepare(job='Нужна только диагностика принтера, без ремонта.')
        answer, handoff = task['output_contract']['decision_states']
        self.assertEqual(answer['reply'], task['fixed_reply'])
        self.assertEqual(_response_consistency_errors(answer), [])
        self.assertEqual(_response_consistency_errors(handoff), [])
        self.assertTrue(answer['context_review']['selected_step_fits'])
        self.assertFalse(handoff['context_review']['selected_step_fits'])
        schema = prepared['model_task']['response_format']['schema']['properties']
        self.assertNotIn('enum', schema['needs_operator'])
        self.assertNotIn('enum', schema['context_review']['properties']['selected_step_fits'])

    def test_all_boolean_reply_combinations_keep_exactly_two_coherent_states(self):
        allowed = []
        for fits, operator, nonempty in itertools.product([False, True], repeat=3):
            candidate = dict(context_review=dict(selected_step_fits=fits),
                             needs_operator=operator, reply='Уместный ответ.' if nonempty else '')
            untouched = copy.deepcopy(candidate)
            if not _response_consistency_errors(candidate):
                allowed.append((fits, operator, nonempty))
            self.assertEqual(candidate, untouched)
        self.assertEqual(allowed, [(False, True, False), (True, False, True)])

    def test_observed_empty_accepted_operator_verdict_is_not_repaired(self):
        prepared, task = self.prepare(job='Нужна только диагностика принтера, без ремонта.')
        value = self.candidate(task)
        value.update(reply='', needs_operator=True)
        untouched = copy.deepcopy(value)
        final = self.finish(prepared, value)
        self.assertEqual(value, untouched)
        self.assertEqual(final['action'], 'handoff')
        self.assertEqual(final['reply'], '')
        self.assertIn('accepted_step_empty_reply', final['validation'])
        self.assertIn('inconsistent_operator_verdict', final['validation'])
        self.assertFalse(final['auto_enabled'])

    def test_coherent_answer_keeps_its_checked_reply(self):
        prepared, task = self.prepare(job='Нужна только диагностика принтера, без ремонта.')
        value = self.candidate(task)
        final = self.finish(prepared, value)
        self.assertEqual(final['validation'], [])
        self.assertEqual(final['reply'], 'Диагностика без ремонта — от 500 рублей.')
        self.assertFalse(final['needs_operator'])

    def test_coherent_model_handoff_remains_possible_with_nonempty_proposal(self):
        prepared, task = self.prepare(job='Нужна только диагностика принтера, без ремонта.')
        value = self.candidate(task)
        self.assertTrue(task['fixed_reply'])
        value.update(reply='', needs_operator=True)
        value['context_review'].update(selected_step_fits=False,
            note='Выбранный шаг не подходит по истории, требуется проверка оператора.')
        final = self.finish(prepared, value)
        self.assertEqual(final['action'], 'handoff')
        self.assertEqual(final['reply'], '')
        self.assertTrue(final['needs_operator'])
        self.assertNotIn('inconsistent_operator_verdict', final['validation'])
        self.assertNotIn('accepted_step_empty_reply', final['validation'])

    def test_decision_states_do_not_fabricate_review_or_execution_evidence(self):
        _, task = self.prepare(job='Нужна только диагностика принтера, без ремонта.')
        for state in task['output_contract']['decision_states']:
            self.assertEqual(set(state['context_review']), {'selected_step_fits'})
            self.assertNotIn('evidence_ids', state)
            self.assertNotIn('sent', state)
        self.assertIn('не факты диалога', task['output_contract']['decision_states_scope'])


if __name__ == '__main__':
    unittest.main()
