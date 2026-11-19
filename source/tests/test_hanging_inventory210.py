import unittest
import qualification_state as qs


def history(answer='Все детали и крепёж уже в наличии.', work='Нужно повесить полку в квартире.'):
    return [dict(id='job', direction='in', sender_type='client', body=work),
            dict(id='stock-question', direction='out', sender_type='operator',
                 body='Материалы и комплектующие есть?', delivery_status='delivered'),
            dict(id='stock-answer', direction='in', sender_type='client', body=answer)]


class HangingInventory210Tests(unittest.TestCase):
    def test_explicit_hanging_parts_answer_has_exact_sources_and_narrow_scope(self):
        messages = history()
        row = qs.inspect(messages)['materials']
        self.assertEqual(row['status'], 'answered')
        self.assertEqual(row['message_id'], 'stock-answer')
        self.assertEqual(row['question_message_id'], 'stock-question')
        self.assertEqual(row['quote'], messages[-1]['body'])
        self.assertEqual(row['question_quote'], messages[-2]['body'])
        self.assertEqual(row['availability_scope'], 'client_reported_hanging_parts_only')
        self.assertNotEqual(row['value'], 'yes')

    def test_completed_statement_and_pause_do_not_erase_inventory(self):
        messages = history('Все детали и крепёж уже в наличии. Секунду, номер найду.')
        row = qs.inspect(messages)['materials']
        self.assertEqual(row['status'], 'answered')
        self.assertEqual(row['quote'], messages[-1]['body'])
        messages.append(dict(id='next', direction='in', sender_type='client', body='Я буду на месте.'))
        self.assertEqual(qs.inspect(messages)['materials']['message_id'], 'stock-answer')

    def test_no_inference_from_partial_purchase_or_unqualified_yes(self):
        for body in ('Крепёж куплен.', 'Все детали есть.', 'Есть полка.', 'Наверное, все детали и крепёж есть.'):
            with self.subTest(body=body):
                self.assertIsNone(qs.hanging_inventory_reply(history(body), 2))

    def test_uncertainty_negation_past_future_questions_and_foreign_reports(self):
        for body in ('Не все детали и крепёж есть.', 'Все детали и крепёж будут завтра.',
                     'Раньше все детали и крепёж были в наличии.', 'Все детали и крепёж есть?',
                     'Сосед сказал: «Все детали и крепёж уже в наличии».',
                     'У мастера все детали и крепёж есть.', 'Если все детали и крепёж есть, начнём.'):
            with self.subTest(body=body):
                self.assertIsNone(qs.hanging_inventory_reply(history(body), 2))

    def test_nonclient_and_failed_input_have_no_authority(self):
        for patch in (dict(sender_type='system'), dict(sender_type='operator'), dict(role='system'),
                      dict(speaker_role='operator'), dict(delivery_status='failed'), dict(out_pending=True)):
            messages = history(); messages[-1].update(patch)
            with self.subTest(patch=patch):self.assertIsNone(qs.hanging_inventory_reply(messages, 2))

    def test_undelivered_or_foreign_question_has_no_authority(self):
        for patch in (dict(delivery_status='failed'), dict(delivery='pending'), dict(out_pending=True),
                      dict(sender_type='client'), dict(body='У мастера все детали и крепёж есть?'),
                      dict(body='Материалы есть? А схема?'), dict(body='Схема и материалы есть?')):
            messages=history(); messages[1].update(patch)
            with self.subTest(patch=patch):self.assertIsNone(qs.hanging_inventory_reply(messages, 2))

    def test_unknown_other_mixed_or_new_order_cannot_borrow_hanging_context(self):
        for work in ('Нужна помощь.', 'Нужно починить принтер.', 'Нужно собрать шкаф.',
                     'Нужно повесить полку и заменить смеситель.'):
            messages=history(work=work)
            with self.subTest(work=work):self.assertIsNone(qs.hanging_inventory_reply(messages, 2))
        messages=history('Новая заявка. Все детали и крепёж уже в наличии.')
        self.assertIsNone(qs.hanging_inventory_reply(messages, 2))

    def test_actual_later_shortage_overrides_reported_inventory(self):
        messages=history()+[dict(id='correction', direction='in', sender_type='client', body='Крепежа нет.')]
        row=qs.inspect(messages)['materials']
        self.assertEqual(row['value'], 'no')
        self.assertEqual(row['message_id'], 'correction')

    def test_later_uncertainty_revokes_confidence_and_binds_new_source(self):
        for body in ('Не уверен, что все детали и крепёж есть.', 'Крепёж вроде есть.'):
            messages=history()+[dict(id='uncertain', direction='in', sender_type='client', body=body)]
            with self.subTest(body=body):
                row=qs.inspect(messages)['materials']
                self.assertEqual(row['status'], 'uncertain')
                self.assertEqual(row['message_id'], 'uncertain')
                self.assertNotIn('question_message_id', row)

    def test_conditional_extras_question_does_not_establish_shortage(self):
        messages=history()+[dict(id='extra', direction='in', sender_type='client',
                                body='А если крепежа окажется мало, мастер привезёт свой?')]
        row=qs.inspect(messages)['materials']
        self.assertEqual(row['status'], 'answered')
        self.assertEqual(row['message_id'], 'stock-answer')


if __name__=='__main__':unittest.main()
