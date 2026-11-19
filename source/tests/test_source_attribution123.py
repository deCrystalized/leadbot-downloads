"""A saved native122 response was falsely blocked on 'masters asserted'."""
import unittest
import test_diagnostic_reasoning119 as helpers


class SourceAttribution123Tests(unittest.TestCase):
    setUp = helpers.DiagnosticReasoning119Tests.setUp
    prepare = helpers.DiagnosticReasoning119Tests.prepare
    candidate = helpers.DiagnosticReasoning119Tests.candidate
    finish = helpers.DiagnosticReasoning119Tests.finish

    def check(self, meaning):
        out, task = self.prepare(job='Нужна только диагностика принтера, без ремонта.')
        value = self.candidate(task)
        value['context_review']['latest_client_meaning'] = meaning
        value['context_review']['note'] = 'Диагностика без ремонта от500; чужую оценку не подтверждаем.'
        return self.finish(out, value)

    def test_asserted_third_party_opinion_preserves_attribution(self):
        out = self.check('Клиент уточняет цену, поскольку другие мастера утверждали, что принтер наверняка нерабочий')
        self.assertEqual(out['validation'], [])
        self.assertEqual(out['reply'], 'Диагностика без ремонта — от 500 рублей.')

    def test_ordinary_speech_variants_stay_useful(self):
        for verb in ['сказали', 'считали', 'сообщили']:
            with self.subTest(verb=verb):
                self.setUp()
                self.assertEqual(self.check('Другие мастера '+verb+', что принтер нерабочий')['validation'], [])

    def test_our_assertion_without_source_remains_blocked(self):
        out = self.check('Клиент уточняет цену, поскольку принтер наверняка нерабочий')
        self.assertIn('unverified_third_party_device_condition', out['validation'])
        self.assertFalse(out['reply'])

    def test_cost_uncertainty_does_not_qualify_an_asserted_fault(self):
        out = self.check('Клиент беспокоится о напрасной трате денег на диагностику неисправного принтера')
        self.assertIn('unverified_third_party_device_condition', out['validation'])

    def test_attribution_does_not_invent_irreparability(self):
        out = self.check('Другие мастера утверждали, что принтер невозможно починить')
        self.assertIn('unsupported_repair_infeasibility', out['validation'])


if __name__ == '__main__':
    unittest.main()
