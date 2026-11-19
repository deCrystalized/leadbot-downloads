"""Literal locality replies and corrections precede unrelated qualification."""
import json
import unittest
import contact_facts
import test_context_grounding110 as fixtures
from test_assistant import context, message


class LocationAnswer113Tests(unittest.TestCase):
    setUp = fixtures.ContextGrounding110Tests.setUp

    def rows(self, answers=('Миасском',), question='А куда нужно будет приехать?', delivery='delivered'):
        return [message('Телевизор Sunwind включается и зависает. Emms похоже перепаять нужно.', mid='job'),
            dict(message(question, 'out', 'where'), sender_type='operator', delivery_status=delivery),
            *[message(text, mid='place'+str(i)) for i,text in enumerate(answers)]]

    def preview(self, rows, mode='reviewed'):
        out, code = self.app.handle(dict(owner='owner', action='preview', wording_mode=mode,
            ctx=context(rows, dir='kp', city='Челябинск', itemTitle='Ремонт телевизоров')))
        self.assertEqual(code, 200)
        return out

    def test_bring_question_explains_onsite_then_checks_actual_outoftown_place(self):
        rows = [message('Телевизор включается и замирает.', mid='job'),
            dict(message('Когда вам будет удобно меня принять?', 'out', 'when'), sender_type='operator'),
            message('Я иногородний, хотел вам его привезти. Есть такая возможность?', mid='bring')]
        out = self.preview(rows)
        self.assertIn('Мастер выезжает на адрес к клиенту.', out['reply'])
        self.assertIn('населённом пункте', out['reply'])
        self.assertNotIn('плазм', out['reply'].lower())
        self.assertNotIn('мастерская', out['reply'].lower())

    def test_location_reply_is_literal_unverified_lookup_not_a_guessed_city(self):
        out = self.preview(self.rows())
        hint = out['facts']['untyped_place_candidate']
        self.assertEqual(hint['value'], 'Миасском')
        self.assertEqual(hint['question_message_id'], 'where')
        self.assertFalse(hint['map_verified'])
        self.assertEqual(out['action'], 'handoff')
        self.assertFalse(out['reply'])
        self.assertFalse(out.get('pending_model'))

    def test_consecutive_correction_retains_question_and_both_reply_ids(self):
        out = self.preview(self.rows(('Миасском', 'Миасское')))
        hint = out['facts']['untyped_place_candidate']
        self.assertEqual(hint['value'], 'Миасское')
        self.assertEqual(hint['message_id'], 'place1')
        self.assertEqual(hint['answer_window_message_ids'], ['place0', 'place1'])
        self.assertEqual(hint['prior_values'], ['Миасском'])
        self.assertEqual(out['action'], 'handoff')

    def test_short_reply_to_model_question_is_not_a_location(self):
        out = self.preview(self.rows(('Sunwind',), question='Какой марки телевизор?'))
        self.assertFalse(out['facts']['untyped_place_candidate'])

    def test_failed_or_pending_question_never_grounds_a_place(self):
        for delivery in ('failed', 'pending', 'sending'):
            with self.subTest(delivery=delivery):
                out = self.preview(self.rows(delivery=delivery))
                self.assertFalse(out['facts']['untyped_place_candidate'])

    def test_time_yes_and_unspecified_home_are_not_locality_names(self):
        for reply in ('Да', 'Завтра', 'Дома', 'Ко мне', 'Не знаю', 'Позже напишу', 'Воронежская область'):
            with self.subTest(reply=reply):
                hint = contact_facts.untyped_place_candidate(self.rows((reply,)), {'city':'Челябинск'}, {})
                self.assertFalse(hint)

    def test_matching_advert_city_does_not_create_an_unrelated_place_conflict(self):
        out = self.preview(self.rows(('Челябинск',)))
        self.assertNotEqual(out['action'], 'handoff')
        self.assertNotIn('населённом пункте', out.get('reply', ''))

    def test_model_task_exposes_observed_question_without_canonicalizing_name(self):
        out = self.preview(self.rows(('Челябинск',)), 'neural_review')
        task = json.loads(out['model_task']['task'])
        link = task['location_answer_context']
        self.assertEqual(link['question_evidence_id'], 'where')
        self.assertEqual(link['answer_evidence_id'], 'place0')
        self.assertEqual(link['literal_place'], 'Челябинск')
        self.assertFalse(link['map_verified'])

    def test_planned_tv_type_question_is_not_the_clients_goal_after_a_place_answer(self):
        out = self.preview(self.rows(('Челябинск',)), 'neural_review')
        task = json.loads(out['model_task']['task'])
        final = fixtures.ContextGrounding110Tests.finish(self, out, task,
            'Клиент сообщает Челябинск как место для выезда.',
            'Вопрос о типе телевизора логично продолжает сбор.', intent='Уточнить тип телевизора')
        self.assertFalse(final['reply'])
        self.assertIn('staff_question_as_client_goal', final['validation'])

    def test_real_repair_goal_and_literal_city_answer_can_continue(self):
        out = self.preview(self.rows(('Челябинск',)), 'neural_review')
        task = json.loads(out['model_task']['task'])
        final = fixtures.ContextGrounding110Tests.finish(self, out, task,
            'Клиент сообщает Челябинск как место для выезда.',
            'Место названо, тип телевизора ещё неизвестен.', intent='Отремонтировать зависающий телевизор')
        self.assertTrue(final['reply'])
        self.assertEqual(final['validation'], [])


if __name__ == '__main__':
    unittest.main()
