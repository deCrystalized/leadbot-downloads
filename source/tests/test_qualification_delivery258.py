"""A short answer cannot confirm a prerequisite from an unavailable question."""
import copy
import unittest

import qualification_state as qualification
import test_native_wording209 as native_fixture


CASES = {
    'gas_type': ('Нужен ремонт духового шкафа.', 'Духовой шкаф без газа?', 'без газа'),
    'plumbing_ready': ('Нужно подключить стиральную машину.', 'Подвод и отвод воды уже подготовлены?', 'yes'),
    'electrics_ready': ('Нужно подключить духовой шкаф.', 'Электрика подготовлена к подключению?', 'yes'),
    'floor_ready': ('Нужно уложить ламинат.', 'Пол подготовлен к укладке?', 'yes'),
    'ceiling': ('Нужно повесить люстру.', 'Потолок натяжной?', 'натяжной'),
}


def source(key, status='pending', answer='Да', **extra):
    work, prompt, _ = CASES[key]
    question = dict(id='question', direction='out', sender_type='operator', body=prompt)
    if status is not None:
        question['delivery_status'] = status
    question.update(extra)
    return [dict(id='request', direction='in', sender_type='client', body=work), question,
            dict(id='answer', direction='in', sender_type='client', body=answer)]


class QualificationDelivery258Tests(unittest.TestCase):
    def test_explicitly_unavailable_question_does_not_confirm_a_short_yes(self):
        for key in CASES:
            for status in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled'):
                with self.subTest(key=key, status=status):
                    row = qualification.inspect(source(key, status))[key]
                    self.assertEqual(row['status'], 'missing')
                    self.assertEqual(row['asked'], 0)

    def test_unavailable_question_does_not_bind_a_short_negative_either(self):
        for key in CASES:
            with self.subTest(key=key):
                self.assertEqual(qualification.inspect(source(key, answer='Нет'))[key]['status'], 'missing')

    def test_observed_and_legacy_human_questions_keep_short_positive_answers(self):
        for key in CASES:
            for status in ('delivered', 'read', None):
                with self.subTest(key=key, status=status):
                    row = qualification.inspect(source(key, status))[key]
                    self.assertEqual(row['status'], 'answered')
                    self.assertEqual(row['message_id'], 'answer')
                    self.assertEqual(row['asked'], 1)

    def test_pending_flag_and_legacy_delivery_field_cannot_be_bypassed(self):
        for fields in (dict(out_pending=True), dict(delivery='PENDING')):
            with self.subTest(fields=fields):
                self.assertEqual(qualification.inspect(source('plumbing_ready', None, **fields))['plumbing_ready']['status'], 'missing')

    def test_service_and_system_outgoing_rows_are_not_questions(self):
        for fields in (dict(sender_type='system'), dict(sender_type='avito'),
                       dict(role='system'), dict(speaker_role='service'), dict(sender_type='partner')):
            with self.subTest(fields=fields):
                row = qualification.inspect(source('plumbing_ready', 'delivered', **fields))['plumbing_ready']
                self.assertEqual(row['status'], 'missing')
                self.assertEqual(row['asked'], 0)

    def test_explicit_client_readiness_survives_an_unavailable_question(self):
        rows = source('plumbing_ready', answer='Подвод и отвод воды готовы.')
        row = qualification.inspect(rows)['plumbing_ready']
        self.assertEqual(row['status'], 'answered')
        self.assertEqual(row['message_id'], 'answer')
        self.assertEqual(row['asked'], 0)

    def test_explicit_electric_type_is_not_lost_with_pending_gas_question(self):
        row = qualification.inspect(source('gas_type', answer='Духовка электрическая.'))['gas_type']
        self.assertEqual(row['status'], 'answered')
        self.assertIn('электрическ', row['value'])
        self.assertEqual(row['asked'], 0)

    def test_floor_ready_shorthand_needs_an_observed_question(self):
        for status, expected in (('pending', 'missing'), ('delivered', 'answered')):
            with self.subTest(status=status):
                row = qualification.inspect(source('floor_ready', status, answer='Да, всё готово'))['floor_ready']
                self.assertEqual(row['status'], expected)

    def test_pending_floor_question_cannot_infer_a_negative_readiness(self):
        self.assertEqual(qualification.inspect(source('floor_ready', answer='Пока не готово'))['floor_ready']['status'], 'missing')

    def test_office_queued_question_does_not_become_observed_context(self):
        rows = [dict(id='work', direction='in', body='Word не работает.'),
                dict(id='question', direction='out', sender_type='operator', delivery_status='queued',
                     body='Что именно происходит при работе с Word?'),
                dict(id='answer', direction='in', body='Не открывается.')]
        row = qualification.office_symptom_answer(rows)
        self.assertEqual(row['asked'], 0)
        self.assertNotEqual(row.get('question_message_id'), 'question')

    def test_office_pending_flag_with_delivered_status_does_not_count_question(self):
        rows = [dict(id='work', direction='in', body='Word не работает.'),
                dict(id='question', direction='out', sender_type='operator', delivery_status='delivered',
                     out_pending=True, body='Что именно происходит при работе с Word?')]
        self.assertEqual(qualification.office_symptom_answer(rows)['asked'], 0)

    def test_unavailable_short_answer_is_not_confirmation(self):
        rows = source('plumbing_ready', 'delivered')
        rows[-1]['delivery_status'] = 'pending'
        self.assertEqual(qualification.inspect(rows)['plumbing_ready']['status'], 'missing')

    def test_system_yes_is_not_client_confirmation(self):
        for fields in (dict(sender_type='system'), dict(role='system'), dict(speaker_role='service')):
            with self.subTest(fields=fields):
                rows = source('plumbing_ready', 'delivered'); rows[-1].update(fields)
                self.assertEqual(qualification.inspect(rows)['plumbing_ready']['status'], 'missing')

    def test_input_order_ids_and_delivery_are_not_rewritten(self):
        rows = source('plumbing_ready'); original = copy.deepcopy(rows)
        qualification.inspect(rows)
        self.assertEqual(rows, original)


class NativeQualificationDelivery258Tests(unittest.TestCase):
    setUp = native_fixture.NativeWording209Tests.setUp
    tearDown = native_fixture.NativeWording209Tests.tearDown

    def test_native_preview_does_not_advance_past_an_unsent_readiness_question(self):
        self.ctx.update(itemTitle='Сантехника', messages=source('plumbing_ready'))
        prepared, task = native_fixture.NativeWording209Tests.prepare(self)
        self.assertEqual(task['decision']['next_question']['kind'], 'plumbing_ready')
        self.assertTrue(prepared.get('pending_model'))

    def test_native_preview_keeps_readiness_answer_to_delivered_question(self):
        self.ctx.update(itemTitle='Сантехника', messages=source('plumbing_ready', 'delivered'))
        _, task = native_fixture.NativeWording209Tests.prepare(self)
        self.assertEqual(task['decision']['next_question']['kind'], 'electrics_ready')

