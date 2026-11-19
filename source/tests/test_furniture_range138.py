"""Real504: assembled units, unit counts and a requested time range stay distinct."""
import unittest

import contact_facts as cf
import qualification_state as qs


def row(body, direction='in', mid='client', **extra):
    return dict(id=mid, body=body, direction=direction, **extra)


def furniture(answer='Да. Собранные. Только повесить', **prompt_fields):
    return [row('Надо повесить кухонные шкафы: 60x72 - 2 шт, антресольные 60x36 3шт.', mid='job'),
            row('У вас все в наличии есть уже?', 'out', 'inventory', **prompt_fields),
            row(answer, mid='ready')]


def visit(body='Сегодня с 2:30-3:00', prompt='Хорошо, когда вам будет удобно меня принять?', **extra):
    return [row(prompt, 'out', 'visit-question', **extra), row(body, mid='window')]


class FurnitureRange138Tests(unittest.TestCase):
    def test_quantity_and_dimensions_are_not_device_models(self):
        for text in ['60x72 2шт, 60x36 3шт', '3штуки', '12pcs', '20ед', '2штук']:
            with self.subTest(text=text):
                self.assertEqual(qs.inspect([row(text)])['model']['status'], 'missing')

    def test_actual_device_models_remain_literal(self):
        for text, value in [('Canon MG2540S', 'MG2540S'), ('Epson L3101', 'L3101'),
                            ('Samsung SCX-4200', 'Samsung SCX-4200'), ('Samsung A10', 'A10')]:
            with self.subTest(text=text):
                self.assertEqual(qs.inspect([row(text)])['model']['value'], value)

    def test_complete_original_written_scope_has_no_device_model(self):
        text = ('Нам надо повесить кузонные шкафы,60x72 - 2 шт, 60x72 угловой 1 шт '
                '30x72 2 шт. Антрисольные: 60x36 3шт, 60x36углов 1 шт. Сколько будет стоить?')
        self.assertEqual(qs.inspect([row(text)])['model']['status'], 'missing')
        for size in ['60x36углов', '60х36угловой', '60×36угловая', '60x36угловых']:
            with self.subTest(size=size):
                self.assertEqual(qs.inspect([row(size)])['model']['status'], 'missing')

    def test_assembled_reply_binds_ready_units_only_and_keeps_both_sources(self):
        state = qs.inspect(furniture())
        material = state['materials']
        self.assertEqual(material['status'], 'answered'); self.assertEqual(material['value'], 'yes')
        self.assertEqual(material['availability_scope'], 'client_named_assembled_furniture_only')
        self.assertEqual(material['question_message_id'], 'inventory')
        self.assertEqual(material['message_id'], 'ready')
        self.assertEqual(material['quote'], 'Да. Собранные. Только повесить')
        self.assertEqual(state['model']['status'], 'missing')
        self.assertEqual(state['wall']['status'], 'missing')

    def test_no_inventory_inference_without_actual_delivered_single_question(self):
        for fields in [dict(out_pending=True), dict(delivery_status='failed'), dict(delivery_status='queued')]:
            with self.subTest(fields=fields):
                self.assertEqual(qs.inspect(furniture(**fields))['materials']['status'], 'missing')
        for prompt in ['По цене согласны?', 'Материалы есть? Инструкция есть?', 'Материалы и инструкция есть?']:
            history = furniture(); history[1]['body'] = prompt
            with self.subTest(prompt=prompt):
                self.assertNotEqual(qs.inspect(history)['materials'].get('value'), 'yes')
        self.assertEqual(qs.inspect([furniture()[0], furniture()[2]])['materials']['status'], 'missing')

    def test_conditional_negative_and_customer_questions_are_not_ready_units(self):
        for answer in ['Да? Собранные? Только повесить?', 'Да, если собранные, только повесить',
                       'Нет. Не собранные. Только повесить', 'Да. Собранные. Но крепежа нет']:
            with self.subTest(answer=answer):
                self.assertNotEqual(qs.inspect(furniture(answer))['materials']['value'], 'yes')
        self.assertIsNone(qs.YES.fullmatch('Да. Собранные. Только повесить'))

    def test_original_time_range_is_complete_and_never_silently_shifted_to_afternoon(self):
        history = visit()
        state = qs.inspect(history)['visit_time']; fact = cf.requested_visit(history)
        self.assertEqual(state['value'], 'сегодня с 2:30-3:00')
        self.assertEqual(state['status'], 'uncertain'); self.assertTrue(state['requires_clarification'])
        self.assertEqual(state['message_id'], 'window'); self.assertEqual(state['question_message_id'], 'visit-question')
        self.assertEqual(qs.question('visit_time', dict(visit_time=state))['question'], 'Это время днём?')
        self.assertEqual(fact['window'], state['value']); self.assertFalse(fact['appointment_confirmed'])
        self.assertNotIn('date', fact); self.assertNotIn('14:30', str(fact))

    def test_clear_24_hour_range_keeps_both_ends_without_proving_booking(self):
        for body in ['Сегодня с 14:30-15:00', 'Завтра с 14:30 до 15:00', 'Послезавтра с 14.30–15.00']:
            with self.subTest(body=body):
                history = visit(body); state = qs.inspect(history)['visit_time']; fact = cf.requested_visit(history)
                self.assertEqual(state['value'], body.casefold())
                self.assertEqual(state['status'], 'answered'); self.assertFalse(state['requires_clarification'])
                self.assertFalse(fact['appointment_confirmed'])

    def test_call_purchase_self_dropoff_quotes_and_undelivered_question_are_not_visit_ranges(self):
        for prompt in ['Когда вам позвонить?', 'Когда купите материалы?', 'Когда вы приедете к нам?',
                       'Когда удобно отправить фото?', 'Когда вам удобно меня принять? Телефон есть?']:
            with self.subTest(prompt=prompt):
                self.assertEqual(cf.requested_visit(visit(prompt=prompt)), {})
                self.assertEqual(qs.inspect(visit(prompt=prompt))['visit_time']['status'], 'missing')
        for text in ['Я сам приеду сегодня с 2:30-3:00', 'Позвоните сегодня с 2:30-3:00',
                     'Если сегодня с 2:30-3:00, тогда посмотрим', 'Мастер написал: «Сегодня с 2:30-3:00»',
                     'Сегодня с 2:30-3:00 или завтра с 14:00-15:00']:
            with self.subTest(text=text):
                self.assertEqual(cf.requested_visit(visit(text)), {})
                self.assertEqual(qs.inspect(visit(text))['visit_time']['status'], 'missing')
        for delivery in ['failed', 'pending', 'queued', 'cancelled']:
            with self.subTest(delivery=delivery):
                self.assertEqual(cf.requested_visit(visit(delivery_status=delivery)), {})

    def test_later_cancellation_clears_the_preference(self):
        self.assertEqual(cf.requested_visit(visit() + [row('Не нужно, отмените')]), {})

    def test_reversed_or_empty_ranges_remain_unresolved(self):
        for body in ['Сегодня с 15:00-14:30', 'Сегодня с 15:00-15:00']:
            with self.subTest(body=body):
                history = visit(body)
                self.assertEqual(qs.inspect(history)['visit_time']['status'], 'uncertain')
                self.assertEqual(cf.requested_visit(history)['clarification_kind'], 'range_order')
                history += [row('Это время днём?', 'out', 'clarify'), row('Да')]
                self.assertTrue(cf.requested_visit(history)['requires_clarification'])

    def test_explicit_daypart_is_preserved_without_clock_conversion(self):
        fact = cf.requested_visit(visit('Сегодня с 2:30-3:00 днём'))
        self.assertEqual(fact['window'], 'сегодня с 2:30-3:00 днём')
        self.assertFalse(fact['requires_clarification']); self.assertFalse(fact['appointment_confirmed'])

    def test_daypart_answer_resolves_only_the_specific_delivered_clarification(self):
        for answer in ['Да', 'Да, днём']:
            history = visit() + [row('Это время днём?', 'out', 'clarify'), row(answer, mid='daypart')]
            state = qs.inspect(history)['visit_time']; fact = cf.requested_visit(history)
            self.assertEqual(state['status'], 'answered'); self.assertFalse(state['requires_clarification'])
            self.assertEqual(state['value'], 'сегодня с 2:30-3:00 днём')
            self.assertEqual(fact['range_message_id'], 'window'); self.assertEqual(fact['message_id'], 'daypart')
            self.assertFalse(fact['appointment_confirmed'])
            comment = '\n'.join(cf.collect(history, dict(city='Нижневартовск', direction='mnc'))['comment_lines'])
            self.assertIn('Сегодня с 2:30-3:00', comment)
            self.assertIn('Это время днём?', comment)
            self.assertIn(answer, comment)
        for fields in [dict(body='По цене согласны?'), dict(body='Это время днём?', delivery_status='failed'),
                       dict(body='Это время днём? Номер телефона есть?')]:
            history = visit() + [dict(row('', 'out', 'clarify'), **fields), row('Да', mid='daypart')]
            self.assertTrue(cf.requested_visit(history)['requires_clarification'])
            self.assertEqual(qs.inspect(history)['visit_time']['status'], 'uncertain')
        history = visit() + [row('Я сам позже позвоню', mid='new'), row('Это время днём?', 'out', 'clarify'), row('Да')]
        self.assertTrue(cf.requested_visit(history)['requires_clarification'])

    def test_later_explicit_time_does_not_keep_stale_range_clarification(self):
        history = visit() + [row('Нет, сегодня в 15:30', mid='corrected')]
        state = qs.inspect(history)['visit_time']
        self.assertEqual(state['status'], 'answered'); self.assertEqual(state['message_id'], 'corrected')
        self.assertNotIn('range_source', state); self.assertNotIn('clarification_kind', state)


if __name__ == '__main__': unittest.main()
