"""A useful accepted step and reported equipment condition must agree."""
import unittest
import test_diagnostic_reasoning119 as helpers
from extension_assistant import _response_consistency_errors, _repair_infeasibility_review_errors


class NeuralConsistency121Tests(unittest.TestCase):
    setUp = helpers.DiagnosticReasoning119Tests.setUp
    prepare = helpers.DiagnosticReasoning119Tests.prepare
    candidate = helpers.DiagnosticReasoning119Tests.candidate
    finish = helpers.DiagnosticReasoning119Tests.finish

    def test_accepted_empty_reply_is_not_a_successful_step(self):
        out, task = self.prepare()
        value = self.candidate(task)
        value.update(reply='', needs_operator=True)
        final = self.finish(out, value)
        self.assertIn('accepted_step_empty_reply', final['validation'])
        self.assertIn('inconsistent_operator_verdict', final['validation'])
        self.assertFalse(final['reply'])

    def test_correct_price_can_be_released_without_invented_condition(self):
        out, task = self.prepare(job='Нужна только диагностика принтера, без ремонта.')
        value = self.candidate(task)
        value['context_review']['note'] = 'Только диагностика: от 500 рублей. Чужое мнение не подтверждает диагноз.'
        final = self.finish(out, value)
        self.assertEqual(final['validation'], [])
        self.assertEqual(final['reply'], 'Диагностика без ремонта — от 500 рублей.')

    def test_nonworking_and_refusal_are_not_irreparability(self):
        out, task = self.prepare(job='Нужна только диагностика принтера, без ремонта.')
        value = self.candidate(task)
        value['context_review']['latest_client_meaning'] = 'Клиент передаёт мнение других мастеров о невозможности починки принтера'
        final = self.finish(out, value)
        self.assertIn('unsupported_repair_infeasibility', final['validation'])
        self.assertFalse(final['reply'])

    def test_legitimate_rejected_step_still_allows_handoff(self):
        value = dict(reply='', needs_operator=True, context_review=dict(selected_step_fits=False))
        self.assertEqual(_response_consistency_errors(value), [])
        value['reply'] = 'Приеду через час.'
        self.assertIn('rejected_step_has_reply', _response_consistency_errors(value))

    def test_explicit_report_keeps_its_source_and_never_verifies_diagnosis(self):
        task = dict(conversation=[dict(speaker_role='client', body='В сервисе сказали: принтер неремонтопригоден.')])
        attributed = dict(last_intent='Клиент передаёт мнение сервиса: принтер неремонтопригоден')
        self.assertEqual(_repair_infeasibility_review_errors(attributed, task), [])
        self.assertIn('unattributed_repair_infeasibility', _repair_infeasibility_review_errors(dict(note='Принтер неремонтопригоден'), task))

    def test_denied_or_hypothetical_impossibility_is_not_a_diagnosis(self):
        task = dict(conversation=[dict(speaker_role='client', body='Принтер не печатает.')])
        for text in ['Неремонтопригодность не подтверждена.',
                     'Клиент не говорил, что принтер невозможно починить.',
                     'Нельзя утверждать, что принтер невозможно починить.',
                     'Если принтер невозможно починить, цена диагностики остаётся минимальной.']:
            with self.subTest(text=text):
                self.assertEqual(_repair_infeasibility_review_errors(dict(note=text), task), [])


if __name__ == '__main__':
    unittest.main()
