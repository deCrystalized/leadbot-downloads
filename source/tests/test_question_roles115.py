"""Preserve the real113 rationale error and distinguish service qualification."""
import unittest
import test_context_grounding110 as fixtures
from test_assistant import message


class QuestionRoles115Tests(unittest.TestCase):
    def setUp(self):
        fixtures.ContextGrounding110Tests.setUp(self)

    def prepare(self, rows):
        return fixtures.ContextGrounding110Tests.prepare(self, rows)

    def finish(self, out, task, note, intent='Узнать возможность замены деталей шкафа'):
        return fixtures.ContextGrounding110Tests.finish(self, out, task,
            'Клиент спрашивает, можно ли заменить разбухшие детали шкафа.', note, intent)

    def rows(self):
        return [message('Здравствуйте. Подскажите пожалуйста, можно ли заменить взбухшие детали у шкафа после потопа 🙏', mid='job')]

    def test_explicit_replacement_with_another_damage_word_does_not_repeat_the_job_question(self):
        _, task = self.prepare([message('Здравствуйте! Можно заменить вздувшиеся после потопа детали шкафа?', mid='job')])
        self.assertEqual(task['planned_question_roles']['qualification_kind'], 'materials')
        self.assertTrue(task['service_capability_question'])

    def test_planned_material_question_has_its_own_actor_and_is_not_goal_evidence(self):
        _, task = self.prepare(self.rows())
        roles = task['planned_question_roles']
        self.assertEqual(roles['questioner'], 'service')
        self.assertEqual(roles['respondent'], 'client')
        self.assertEqual(roles['qualification_kind'], 'materials')
        self.assertFalse(roles['is_evidence_of_client_goal'])
        self.assertEqual(roles['status'], 'planned_not_sent')
        self.assertEqual(task['selected_question_history']['observed_question_ids'], [])

    def test_actual113_bad_note_is_rejected_before_any_reply(self):
        out, task = self.prepare(self.rows())
        final = self.finish(out, task,
            'Вопрос сотрудника соответствует цели клиента — уточнить наличие материалов для замены деталей шкафа.')
        self.assertFalse(final['reply'])
        self.assertIn('staff_question_as_client_goal', final['validation'])

    def test_correct_service_goal_and_separate_future_question_are_accepted(self):
        out, task = self.prepare(self.rows())
        final = self.finish(out, task,
            'Клиент спрашивает о замене деталей; следующий вопрос уточнит наличие материалов.')
        self.assertTrue(final['reply'])
        self.assertEqual(final['validation'], [])

    def test_staff_qualification_is_not_a_replacement_goal_in_last_intent(self):
        out, task = self.prepare(self.rows())
        final = self.finish(out, task, 'Следующий вопрос проверит материалы.',
                            'Уточнить наличие материалов')
        self.assertFalse(final['reply'])
        self.assertIn('staff_question_as_client_goal', final['validation'])

    def test_negative_explanation_does_not_define_materials_as_the_customer_goal(self):
        out, task = self.prepare(self.rows())
        final = self.finish(out, task,
            'Цель клиента — замена деталей; наличие материалов ещё не подтверждено.')
        self.assertTrue(final['reply'])
        self.assertEqual(final['validation'], [])

    def test_a_real_client_question_about_materials_is_not_relabelled_as_staff_goal(self):
        out, task = self.prepare([message('Можно заменить детали шкафа? Материалы у вас есть?', mid='job')])
        self.assertTrue(task['planned_question_roles']['explicit_client_materials_question'])
        final = fixtures.ContextGrounding110Tests.finish(self, out, task,
            'Клиент спрашивает о замене деталей и наличии материалов у сервиса.',
            'Клиент также спрашивает про материалы, их наличие у сервиса не подтверждено.',
            'Узнать наличие материалов')
        self.assertNotIn('staff_question_as_client_goal', final['validation'])

    def test_actual115_meaning_cannot_add_a_materials_question_from_the_planned_staff_step(self):
        rows = self.rows() + [message('Здравствуйте!', 'out', 'hello'),
            message('Фото есть? Пришлите, пожалуйста', 'out', 'photos'),
            message('Дело в том что это у соседей, я их затопила. Как сфоткают отправлю. '
                    'Там боковые стенки взбухли чуть чуть снизу. Вы берете такую работу?', mid='followup')]
        out, task = self.prepare(rows)
        final = fixtures.ContextGrounding110Tests.finish(self, out, task,
            'клиент уточняет, возьмётся ли сервис за замену деталей шкафа у соседей, '
            'пострадавшего после потопа, и интересуется наличием материалов',
            'Следующий вопрос уточнит материалы для замены деталей.',
            'спросить, возможна ли замена вздувшихся деталей шкафа после потопа')
        self.assertFalse(final['reply'])
        self.assertIn('staff_question_as_client_goal', final['validation'])

    def test_explicit_negative_does_not_invent_a_materials_question(self):
        out, task = self.prepare(self.rows())
        final = fixtures.ContextGrounding110Tests.finish(self, out, task,
            'Клиент не интересуется наличием материалов, спрашивает о замене деталей.',
            'Наличие материалов ещё не обсуждалось.', 'Узнать возможность замены деталей')
        self.assertNotIn('staff_question_as_client_goal', final['validation'])


if __name__ == '__main__':
    unittest.main()
