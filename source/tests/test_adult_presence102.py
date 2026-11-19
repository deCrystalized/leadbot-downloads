"""An adult must attend a minor's visit; a prior yes is not permanent consent."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_policy as policy
import contact_facts
import qualification_state as qs
import personal_assistant
from extension_assistant import manual_checklist


def rows(*items):
    return [dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(items)]


def history():
    return rows(('in', 'У компьютера чёрный экран и курсор.'),
                ('out', 'Подскажите, вам есть 18?'), ('in', 'Нет. 16'),
                ('in', 'Но родители могу присутствовать'),
                ('out', 'Когда вам удобно?'), ('in', 'Можно завтра'), ('in', 'В 14-15'),
                ('out', 'А родители будут дома в это время?'), ('in', 'Да'))


KNOWN = dict(channel='avito', direction='kp', city='Тула', partner='7',
             direction_source='synthetic', title='Ремонт компьютеров', account_name='Синтетический мастер', origin='В83')


def assess(messages):
    return policy.assess(messages, KNOWN, contact_facts.collect(messages, KNOWN))


class AdultPresenceTests(unittest.TestCase):
    def test_age_question_and_short_reply_are_linked(self):
        age = qs.client_age(history()[:3])
        self.assertEqual(age['status'], 'minor')
        self.assertEqual(age['value'], 16)
        self.assertEqual(age['message_id'], '2')

    def test_only_possible_parent_presence_is_not_time_confirmation(self):
        state = qs.adult_presence(history()[:4])
        self.assertEqual(state['status'], 'possible')
        self.assertEqual(state['message_id'], '3')

    def test_yes_to_actual_presence_question_confirms_that_window(self):
        state = qs.adult_presence(history())
        self.assertEqual(state['status'], 'confirmed')
        self.assertEqual(state['message_id'], '8')
        self.assertEqual(state['question_message_id'], '7')
        self.assertEqual(set(state['window_message_ids']), {'5', '6'})
        self.assertFalse(state['appointment_confirmed'])

    def test_later_absence_revokes_previous_confirmation(self):
        messages = history() + [dict(id='9', direction='in', body='Родителей не будет дома оказывается')]
        state = qs.adult_presence(messages)
        self.assertEqual(state['status'], 'unavailable')
        self.assertEqual(state['message_id'], '9')
        self.assertEqual(state['prior_confirmation']['message_id'], '8')

    def test_new_visit_time_requires_new_adult_confirmation(self):
        state = qs.adult_presence(history() + [dict(id='9', direction='in', body='Лучше завтра в 18')])
        self.assertEqual(state['status'], 'needs_reconfirmation')

    def test_unrelated_yes_is_not_adult_presence(self):
        messages = history()[:4] + rows(('out', 'Материалы есть?'), ('in', 'Да'))
        self.assertNotEqual(qs.adult_presence(messages)['status'], 'confirmed')

    def test_failed_question_does_not_bind_yes(self):
        messages = history()
        messages[-2]['delivery_status'] = 'failed'
        self.assertNotEqual(qs.adult_presence(messages)['status'], 'confirmed')

    def test_past_absence_does_not_revoke_future_confirmation(self):
        messages = history() + [dict(id='9', direction='in', body='Вчера родителей не было дома')]
        self.assertEqual(qs.adult_presence(messages)['status'], 'confirmed')

    def test_brother_of_unknown_age_is_not_an_adult(self):
        self.assertNotEqual(qs.adult_presence(history()[:3] + [dict(id='3', direction='in', body='Брат будет дома')])['status'], 'confirmed')

    def test_person_surname_is_not_a_parent_role(self):
        messages = history()[:7] + [dict(id='9', direction='in', body='Мамонтов будет дома')]
        self.assertNotEqual(qs.adult_presence(messages)['status'], 'confirmed')

    def test_parents_at_work_withdraw_presence_at_home(self):
        for body in ('Родители будут на работе', 'Мама будет в отъезде', 'Родители не дома'):
            with self.subTest(body=body):
                state = qs.adult_presence(history() + [dict(id='9', direction='in', body=body)])
                self.assertEqual(state['status'], 'unavailable')

    def test_client_question_about_parents_is_not_confirmation(self):
        state = qs.adult_presence(history()[:7] + [dict(id='9', direction='in', body='Родители будут дома?')])
        self.assertNotEqual(state['status'], 'confirmed')

    def test_yes_no_to_negative_presence_question_requires_clarification(self):
        for answer in ('Да', 'Нет'):
            with self.subTest(answer=answer):
                messages = history()[:7] + rows(('out', 'Родителей не будет дома?'), ('in', answer))
                self.assertNotEqual(qs.adult_presence(messages)['status'], 'confirmed')

    def test_age_question_does_not_consume_equipment_quantity(self):
        self.assertEqual(qs.client_age(rows(('out', 'Вам есть 18 розеток заменить?'), ('in', 'Да')))['status'], 'missing')

    def test_age_is_not_number_of_work_items(self):
        self.assertEqual(qs.client_age(rows(('out', 'Вам 18 розеток заменить?'), ('in', 'Да')))['status'], 'missing')
        self.assertEqual(qs.client_age(rows(('out', 'Вам есть 18?'), ('in', 'Да')))['status'], 'adult')

    def test_free_unconfirmed_minor_is_skipped_but_owned_can_clarify(self):
        ctx = dict(assigneeId='', assignmentKnown=True, conversationStatus='in_progress',
                   botActive=False, hasTransfer=False, channelAssigned=True)
        free = personal_assistant.screen(history()[:3], KNOWN, ctx, 'george', 0, 0)
        self.assertFalse(free['eligible'])
        ctx['assigneeId'] = 'george'
        mine = personal_assistant.screen(history()[:3], KNOWN, ctx, 'george', 0, 0)
        self.assertTrue(mine['eligible'])
        self.assertTrue(mine['qualification_only'])

    def test_minor_is_asked_for_adult_time_not_rejected_as_a_device_unknown(self):
        out = assess(history()[:3])
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['forced_reply'], 'взросл')
        self.assertIn('DOC-L1572', out['rule_ids'])
        self.assertNotIn('техник', out['forced_reply'])

    def test_repair_question_keeps_adult_condition_and_does_not_guarantee_repair(self):
        out = assess(history()[:4] + [dict(id='4', direction='in', body='Ну вы сможете решить эту проблему?')])
        self.assertEqual(out['action'], 'question')
        self.assertIn('осмотр', out['forced_reply'])
        self.assertIn('взросл', out['forced_reply'])
        self.assertNotRegex(out['forced_reply'], 'починю|отремонтирую|точно')

    def test_confirmed_adult_does_not_turn_minor_into_adult_client(self):
        facts = contact_facts.collect(history(), KNOWN)
        self.assertEqual(facts['client_age']['status'], 'minor')
        self.assertEqual(facts['adult_presence']['status'], 'confirmed')
        self.assertNotIn('несовершеннолетний', assess(history())['reason'].lower())

    def test_withdrawal_after_staff_booking_requires_existing_visit_review(self):
        messages = history() + rows(('out', 'Записал на завтра к 14-14:30'),
                                   ('in', 'Родителей не будет дома оказывается'))
        out = assess(messages)
        self.assertEqual(out['action'], 'handoff')
        self.assertIn('существующ', out['reason'])
        self.assertIn('взросл', out['reason'])
        self.assertIn('VERIFY_ADULT_PRESENCE', [r['id'] for r in out['decision_guards']])

    def test_booking_claim_is_not_a_recorded_phone_or_actual_crm_write(self):
        self.assertIsNone(policy._staff_booking_claim(rows(('out', 'Записал номер телефона.'))))
        claim = policy._staff_booking_claim(rows(('out', 'Записал к 14:30')))
        self.assertIsNotNone(claim)
        self.assertFalse(claim['crm_write_confirmed'])

    def test_why_parents_gets_document_explanation(self):
        messages = history() + rows(('out', 'Записал на завтра к 14-14:30'),
                                   ('in', 'Родителей не будет дома'), ('out', 'А когда будут?'), ('in', 'А зачем они'))
        out = assess(messages)
        self.assertEqual(out['action'], 'question')
        self.assertIn('Документы', out['forced_reply'])
        self.assertIn('совершеннолет', out['forced_reply'])

    def test_form_cannot_treat_withdrawn_parent_presence_as_completed(self):
        messages = history() + [dict(id='9', direction='in', body='Родителей не будет дома')]
        out = manual_checklist(messages, KNOWN)
        item = next(r for r in out['results'] if r['key'] == 'adult_presence')
        self.assertFalse(item['done'])
        self.assertTrue(out['hard_block'])

    def test_adult_does_not_get_parent_question_and_avito_does_not_ask_age_routinely(self):
        for messages in [rows(('in', 'Нужно настроить компьютер. Мне 26 лет.')),
                         rows(('in', 'Нужно настроить компьютер.'))]:
            out = assess(messages)
            self.assertNotRegex(out.get('forced_reply', ''), 'взросл|возраст')


if __name__ == '__main__':
    unittest.main()
