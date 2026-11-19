"""A client's short answer refers to the exact named fitting, not all supplies."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import qualification_state as qs
import assistant_policy
import contact_facts


def state(question='Замок у вас в наличии уже?', answer='Да', *, pending=False, delivery=''):
    return qs.inspect([
        dict(id='job', direction='in', body='Нужно вставить замки в межкомнатные двери.'),
        dict(id='question', direction='out', body=question, out_pending=pending, delivery_status=delivery),
        dict(id='answer', direction='in', body=answer),
    ])['materials']


class NamedMaterial93Tests(unittest.TestCase):
    def test_yes_answers_a_question_about_the_client_lock(self):
        result = state()
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['value'], 'yes')
        self.assertEqual(result['availability_subject'], 'замок')
        self.assertEqual(result['question_message_id'], 'question')
        self.assertEqual(result['message_id'], 'answer')

    def test_no_does_not_become_available(self):
        result = state(answer='Нет, нету')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['value'], 'no')

    def test_instruction_presence_is_not_material_presence(self):
        self.assertEqual(state('Схема или инструкция есть?')['status'], 'missing')

    def test_two_different_questions_do_not_get_a_bare_yes_interpretation(self):
        self.assertEqual(state('Замок у вас есть? Схема есть?')['status'], 'missing')

    def test_unsent_or_failed_question_is_not_an_answer_anchor(self):
        for extra in (dict(pending=True), dict(delivery='failed')):
            with self.subTest(extra=extra):
                self.assertEqual(state(**extra)['status'], 'missing')

    def test_an_unmentioned_handle_does_not_become_confirmed_from_the_lock_request(self):
        self.assertEqual(state('Ручка у вас в наличии уже?')['status'], 'missing')

    def test_a_statement_without_a_question_does_not_anchor_yes(self):
        self.assertEqual(state('Замок у вас в наличии уже.')['status'], 'missing')


class ClientAccess93Tests(unittest.TestCase):
    def assess(self, tail):
        rows = [dict(id='job', direction='in', body='Нужно вставить замки в межкомнатные двери.'),
                dict(id='offer', direction='out', body='Давайте подъеду и посмотрю на месте.'),
                dict(id='absence', direction='in', body='Я не живу там и поэтому показывать не получится.')]
        rows += [dict(id=str(i), direction='in', body=body) for i, body in enumerate(tail)]
        known = dict(city='Екатеринбург', direction='mnc', partner='7', channel='avito', title='Мастер на час')
        return assistant_policy.assess(rows, known, contact_facts.collect(rows, known))

    def test_inability_to_show_the_property_is_not_ignored_by_material_intake(self):
        out = self.assess([])
        self.assertEqual(out['action'], 'handoff')
        self.assertIn('DOC-L0797', out['rule_ids'])
        self.assertFalse(out.get('next_question'))

    def test_a_later_explicit_deferral_still_waits_for_the_client(self):
        out = self.assess(['Когда буду планировать приехать я вам напишу'])
        self.assertEqual(out['action'], 'wait')

    def test_not_residing_there_does_not_mean_inability_to_attend(self):
        rows = [dict(id='job', direction='in', body='Нужно вставить замки в межкомнатные двери.'),
                dict(id='client', direction='in', body='Я не живу там, но приеду и покажу.')]
        self.assertFalse(assistant_policy._decision_maker_absent(rows))
