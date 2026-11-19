"""A scoped inventory answer is not general acceptance of price or a visit."""
import unittest
import qualification_state as qs
import contact_facts
import assistant_policy


def history(answer='да, всё есть', prompt='у вас всё в наличии уже есть?', failed=False):
    return [dict(id='c1', direction='in', body='Сколько стоит поменять кран-буксу на смесителе?'),
            dict(id='q', direction='out', body=prompt, delivery_status='failed' if failed else 'sent'),
            dict(id='c2', direction='in', body=answer)]


class InventoryAnswer105Tests(unittest.TestCase):
    def test_actual_short_reply_binds_one_material_question(self):
        state = qs.inspect(history())['materials']
        self.assertEqual(state['status'], 'answered')
        self.assertEqual(state['value'], 'yes')
        self.assertEqual(state['question_message_id'], 'q')
        self.assertEqual(state['message_id'], 'c2')
        self.assertEqual(state['availability_scope'], 'question_subject_only')

    def test_compact_inventory_variants(self):
        for answer in ('Всё есть', 'Да, всё уже есть.', 'Всё в наличии', 'Да, всё куплено'):
            with self.subTest(answer=answer):
                self.assertEqual(qs.inspect(history(answer))['materials']['value'], 'yes')

    def test_no_question_does_not_bind_unlabelled_inventory(self):
        messages = [history()[0], history()[2]]
        self.assertNotEqual(qs.inspect(messages)['materials']['status'], 'answered')

    def test_failed_material_question_cannot_bind(self):
        self.assertNotEqual(qs.inspect(history(failed=True))['materials']['status'], 'answered')

    def test_price_question_does_not_establish_materials(self):
        self.assertNotEqual(qs.inspect(history(prompt='По цене согласны?'))['materials']['status'], 'answered')
        self.assertIsNone(qs.YES.fullmatch('да, всё есть'))

    def test_multiple_questions_and_customer_questions_are_not_confirmation(self):
        for messages in (history(prompt='Материалы есть? По цене согласны?'), history(answer='А у вас всё есть?'),
                         history(answer='Да, не всё есть')):
            self.assertNotEqual(qs.inspect(messages)['materials']['value'], 'yes')

    def test_fact_keeps_actual_question_and_client_quote(self):
        known = dict(channel='avito', direction='mnc', city='Брянск', partner='7')
        facts = contact_facts.collect(history(), known)
        state = facts['material_availability']
        self.assertEqual(state['value'], 'yes')
        self.assertEqual(state['question_quote'], 'у вас всё в наличии уже есть?')
        self.assertEqual(state['quote'], 'да, всё есть')

    def test_after_required_room_answer_materials_are_not_asked_again(self):
        messages = history() + [dict(id='q2', direction='out', body='Работа нужна на кухне или в ванной?'),
                                dict(id='c3', direction='in', body='В ванной')]
        known = dict(channel='avito', direction='mnc', city='Брянск', partner='7')
        decision = assistant_policy.assess(messages, known, contact_facts.collect(messages, known))
        self.assertNotEqual(decision.get('next_question', {}).get('kind'), 'materials')


if __name__ == '__main__':
    unittest.main()
