"""Clarify an observed drainage complaint without ordering an installation."""
import unittest

import assistant_catalog
import assistant_qualifiers
import contact_facts
from test_history_intake106 import assess, known, rows


class ToiletDrain184Tests(unittest.TestCase):
    def source(self, city='Нижнекамск'):
        return dict(known('mnc', 'Услуги сантехника'), city=city)

    def symptom(self):
        return rows(('in', 'Вода в унитазе смывается, но медленно. Какая цена и сможете сегодня?'))

    def helper(self, messages, source=None):
        source = source or self.source()
        service = assistant_catalog.choose('Нужна помощь с унитазом', source)
        return assistant_qualifiers.toilet_drain_clarification(
            messages, source, service, contact_facts.collect(messages, source))

    def test_current_slow_flush_gets_work_clarification_before_installation_kind(self):
        out = assess(self.symptom(), self.source())
        self.assertEqual(out['next_question']['kind'], 'clog_confirmation')
        self.assertIn('засор', out['next_question']['question'])
        self.assertNotIn('инсталляц', out['next_question']['question'])

    def test_question_is_not_an_observed_clog_or_component_diagnosis(self):
        messages = self.symptom()
        out = assess(messages, self.source())
        self.assertEqual(contact_facts.collect(messages)['confirmed_clog'], {})
        self.assertFalse(out['clog_clarification_evidence']['clog_confirmed'])
        self.assertEqual(out['clog_clarification_evidence']['message_id'], messages[0]['id'])
        self.assertEqual(out['clog_clarification_evidence']['quote'], messages[0]['body'])
        self.assertNotIn('mandatory_price', out)

    def test_normal_word_orders_do_not_require_exact_historical_phrase(self):
        for body in ['В унитазе вода медленно уходит', 'Унитаз плохо смывает',
                     'Медленно сливается вода в унитазе', 'Унитаз смывается очень медленно']:
            with self.subTest(body=body):
                self.assertEqual(assess(rows(('in', body)), self.source())['next_question']['kind'],
                                 'clog_confirmation')

    def test_yes_to_delivered_clog_question_keeps_metre_price(self):
        messages = self.symptom() + rows(('out', 'У вас засор в унитазе?'), ('in', 'Да'))
        for city, price in [('Нижнекамск', '500'), ('Москва', '800')]:
            with self.subTest(city=city):
                out = assess(messages, self.source(city))
                self.assertEqual(out['action'], 'price')
                self.assertIn(price, out['mandatory_price']['reply'])
                self.assertIn('погонный метр', out['mandatory_price']['reply'])
                self.assertNotIn('clog_clarification_evidence', out)
                self.assertNotIn('toilet_kind', out.get('next_question', {}).get('kind', ''))

    def test_bare_yes_to_other_staff_question_is_not_clog_confirmation(self):
        messages = self.symptom() + rows(('out', 'Вы дома?'), ('in', 'Да'))
        out = assess(messages, self.source())
        self.assertEqual(out['next_question']['kind'], 'clog_confirmation')
        self.assertEqual(contact_facts.collect(messages)['confirmed_clog'], {})

    def test_pending_or_multi_question_is_not_a_delivered_clog_answer(self):
        for question, pending in [('У вас засор в унитазе?', True),
                                  ('У вас засор или сломался бачок?', False)]:
            with self.subTest(question=question):
                messages = self.symptom() + rows(('out', question), ('in', 'Да'))
                messages[-2]['out_pending'] = pending
                self.assertEqual(contact_facts.collect(messages)['confirmed_clog'], {})

    def test_installation_replacement_and_tank_work_keep_their_qualification(self):
        for body in ['Нужно заменить унитаз, вода смывается медленно',
                     'Нужно менять унитаз, он плохо смывает',
                     'Установить новый унитаз вместо старого, медленно смывает',
                     'Унитаз плохо смывает, починить бачок',
                     'В бачок унитаза вода медленно набирается',
                     'Вода медленно наполняет унитаз, нужно заменить арматуру']:
            with self.subTest(body=body):
                self.assertIsNone(self.helper(rows(('in', body))))

    def test_different_device_or_service_does_not_receive_toilet_question(self):
        for body in ['В ванной медленно уходит вода', 'У раковины медленно уходит вода',
                     'Нужна сборка шкафа', 'Нужно установить унитаз']:
            with self.subTest(body=body):
                self.assertNotEqual(assess(rows(('in', body)), self.source()).get('next_question', {}).get('kind'),
                                    'clog_confirmation')

    def test_negated_replacement_is_not_a_requested_installation(self):
        for body in ['Унитаз менять не нужно, вода медленно уходит',
                     'Не нужно устанавливать унитаз, он плохо смывает',
                     'Замена унитаза не нужна, вода в унитазе медленно уходит']:
            with self.subTest(body=body):
                self.assertIsNotNone(self.helper(rows(('in', body))))

    def test_separate_positive_installation_survives_negated_tank_work(self):
        messages = rows(('in', 'Не нужно ремонтировать бачок, нужно установить унитаз, вода смывается медленно'))
        self.assertIsNone(self.helper(messages))

    def test_quotes_plans_history_and_third_party_report_are_not_current_symptom(self):
        for body in ['«Вода в унитазе смывается медленно»',
                     'Если вода в унитазе будет медленно смываться, что делать?',
                     'Раньше вода в унитазе медленно уходила',
                     'Сосед сказал, что унитаз плохо смывает']:
            with self.subTest(body=body):
                self.assertIsNone(self.helper(rows(('in', body))))

    def test_nonclient_sender_and_role_cannot_supply_symptom(self):
        for sender in ['operator', 'assistant', 'bot', 'employee', 'staff', 'system', 'avito']:
            with self.subTest(sender=sender):
                message = dict(self.symptom()[0], sender_type=sender)
                self.assertIsNone(self.helper([message]))
        self.assertIsNone(self.helper([dict(self.symptom()[0], role='assistant')]))

    def test_kp_bt_and_mixed_services_do_not_gain_mnc_eligibility(self):
        for direction in ['kp', 'bt']:
            with self.subTest(direction=direction):
                self.assertIsNone(self.helper(self.symptom(), dict(self.source(), direction=direction)))
        service = assistant_catalog.choose('Унитаз медленно смывает. Нужно заменить отопительную трубу', self.source())
        self.assertIsNone(assistant_qualifiers.toilet_drain_clarification(
            self.symptom(), self.source(), service, contact_facts.collect(self.symptom())))

    def test_explicit_clog_and_no_clog_do_not_receive_redundant_confirmation(self):
        self.assertNotEqual(assess(rows(('in', 'Нужно устранить засор унитаза')), self.source()).get('next_question', {}).get('kind'),
                            'clog_confirmation')
        self.assertIsNone(self.helper(rows(('in', 'Унитаз медленно смывает, но это не засор'))))

    def test_no_to_clog_question_persists_after_later_contact_message(self):
        messages = self.symptom() + rows(('out', 'У вас засор в унитазе?'), ('in', 'Нет'),
                                       ('in', 'Мне удобно сегодня'))
        self.assertIsNone(self.helper(messages))

    def test_two_genuinely_unanswered_clog_questions_stop_repetition(self):
        messages = self.symptom() + rows(('out', 'У вас засор в унитазе?'), ('in', 'Не понимаю'),
                                       ('out', 'Это засор?'), ('in', 'Не знаю'))
        out = assess(messages, self.source())
        self.assertEqual(out['action'], 'handoff')
        self.assertNotIn('next_question', out)

    def test_one_unanswered_question_does_not_invent_confirmation(self):
        messages = self.symptom() + rows(('out', 'Это засор?'), ('in', 'Не знаю'))
        out = assess(messages, self.source())
        self.assertNotEqual(out['next_question']['kind'], 'clog_confirmation')
        self.assertEqual(contact_facts.collect(messages)['confirmed_clog'], {})
        self.assertIn('причин', ' '.join(out['required_text']).lower())
        self.assertNotIn('mandatory_price', out)

    def test_new_enquiry_does_not_inherit_an_old_toilet_symptom(self):
        messages = self.symptom() + rows(('in', 'Новая заявка, теперь нужно повесить карниз'))
        self.assertIsNone(self.helper(messages))

    def test_resolved_symptom_does_not_reopen_intake(self):
        messages = self.symptom() + rows(('in', 'Уже всё исправили, помощь не нужна'))
        self.assertIsNone(self.helper(messages))
        self.assertEqual(assess(messages, self.source())['action'], 'wait')

    def test_staff_question_wait_and_existing_booking_guards_still_run_first(self):
        messages = self.symptom() + rows(('out', 'У вас засор в унитазе?'))
        self.assertEqual(assess(messages, self.source())['action'], 'wait')
        messages = self.symptom() + rows(('out', 'Хорошо, записал вас — до встречи'), ('in', 'Спасибо, когда ждать?'))
        out = assess(messages, self.source())
        self.assertEqual(out['action'], 'handoff')
        self.assertNotIn('next_question', out)


if __name__ == '__main__':
    unittest.main()
