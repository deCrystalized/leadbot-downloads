"""Source-derived access details and withdrawn appointments survive drafting."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import contact_facts
import assistant_policy


def history(*rows):
    return [dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)]


class CrmAccess66Tests(unittest.TestCase):
    def test_typo_and_foot_arrival_call_keep_the_client_condition(self):
        for condition in ('только позвоните как подъедите, я спущусь открою',
                          'нужно будет позвонить как подойдете, встретим',
                          'наберите, когда подойдёте', 'позвоните как приедите'):
            facts = contact_facts.collect(history(('in', 'Ленина 10. ' + condition)))
            self.assertEqual(facts['call_timing'], 'upon_arrival', condition)
            self.assertIn(condition, facts['evidence']['call_before_visit']['quote'])
            self.assertTrue(any(condition in x for x in facts['comment_lines']))

    def test_phone_contact_is_not_implied_by_a_staff_promise(self):
        facts = contact_facts.collect(history(('in', 'Ленина 10'), ('out', 'Позвоню как подъеду')))
        self.assertFalse(facts['call_before_visit'])

    def test_explicit_no_call_overrides_an_arrival_phrase(self):
        facts = contact_facts.collect(history(('in', 'Позвоните как подойдете'), ('in', 'Не звоните, я встречу')))
        self.assertEqual(facts['call_timing'], 'not_stated')

    def test_single_entrance_and_landmark_are_kept_from_the_client(self):
        text = 'Ул. Топкинская, 10/2, кв. 52. Подъезд один - со стороны Ретро клуба.\nДомофона нет, нужно будет позвонить как подойдете, встретим.'
        facts = contact_facts.collect(history(('in', text)))
        self.assertEqual(facts['address']['entrance'], '1')
        self.assertEqual(facts['address']['building'], '10/2')
        self.assertEqual(facts['address']['office'], '52')
        self.assertFalse(facts['intercom_present'])
        self.assertTrue(any('со стороны Ретро клуба' in x for x in facts['comment_lines']))

    def test_single_worker_does_not_supply_entrance_or_floor(self):
        facts = contact_facts.collect(history(('in', 'Ленина 10. Нужен один мастер')))
        self.assertNotIn('entrance', facts['address'])
        self.assertNotIn('floor', facts['address'])

    def test_quiet_period_is_a_client_constraint_not_a_legal_rule(self):
        text = 'А можете в 15? А то под нами детсад, режим тишины с 13 до 15.'
        facts = contact_facts.collect(history(('in', text)))
        self.assertEqual(facts['visit_constraints'][0]['quote'], 'режим тишины с 13 до 15')
        self.assertTrue(any('со слов клиента' in x and 'с 13 до 15' in x for x in facts['comment_lines']))
        self.assertEqual(facts['address'], {})

    def test_staff_quiet_period_is_not_a_client_constraint(self):
        facts = contact_facts.collect(history(('out', 'Режим тишины с 13 до 15')))
        self.assertEqual(facts['visit_constraints'], [])

    def test_repeated_flat_and_intercom_are_separate_fields(self):
        text = 'Ленинский 53к4 подъезд 3 КВ 168. Этаж 9\n Домофон так же 168.'
        facts = contact_facts.collect(history(('in', text)))
        self.assertEqual(facts['address'], dict(street='Ленинский', building='53к4', entrance='3', office='168', floor='9', intercom='168'))
        self.assertIn('Домофон: 168.', facts['comment_lines'])

    def test_intercom_price_is_not_an_access_code(self):
        for text in ('Домофон тоже 500 рублей', 'Домофон так же 500 ₽'):
            facts = contact_facts.collect(history(('in', 'Ленина 10. ' + text)))
            self.assertNotIn('intercom', facts['address'])

    def test_withdrawn_visit_is_not_revived_by_later_discussion(self):
        messages = history(('out', 'К 11 будет удобно?'), ('in', 'Хорошо'),
                           ('out', 'Прошу прогения к 11 не смогу'),
                           ('out', 'Могу позднее или в 10'), ('in', 'Давайте попозже тогда'),
                           ('out', 'Давайте в 10 спишгся обсудим по времени'), ('in', 'Хорошо'))
        self.assertIsNone(assistant_policy._accepted_staff_visit(messages))

    def test_replacement_visit_requires_its_own_acceptance(self):
        messages = history(('out', 'К 11 будет удобно?'), ('in', 'Хорошо'),
                           ('out', 'К 11 не смогу'), ('out', 'К 15 будет удобно?'))
        self.assertIsNone(assistant_policy._accepted_staff_visit(messages))
        messages.append(dict(id='new-consent', direction='in', body='Да, удобно'))
        visit = assistant_policy._accepted_staff_visit(messages)
        self.assertEqual(visit['proposal_quote'], 'К 15 будет удобно?')
        self.assertEqual(visit['answer_message_id'], 'new-consent')

    def test_pending_withdrawal_cannot_erase_a_confirmed_appointment(self):
        messages = history(('out', 'К 11 удобно?'), ('in', 'Хорошо'))
        messages.append(dict(id='not-sent', direction='out', body='К 11 не смогу', out_pending=True))
        self.assertEqual(assistant_policy._accepted_staff_visit(messages)['answer_message_id'], '1')

    def test_unavailable_callback_does_not_cancel_an_accepted_visit(self):
        messages = history(('out', 'К 11 удобно?'), ('in', 'Хорошо'),
                           ('out', 'В 10 позвонить не смогу'), ('in', 'Хорошо'))
        self.assertEqual(assistant_policy._accepted_staff_visit(messages)['proposal_quote'], 'К 11 удобно?')

    def test_withdrawal_keeps_lookup_evidence_without_claiming_crm_cancellation(self):
        messages = history(('out', 'К 11 удобно?'), ('in', 'Хорошо'),
                           ('out', 'К 11 не смогу'), ('out', 'Давайте в 10 обсудим по времени'), ('in', 'Хорошо'))
        evidence = assistant_policy._withdrawn_staff_visit(messages)
        self.assertEqual(evidence['withdrawal_quote'], 'К 11 не смогу')
        self.assertFalse(evidence['crm_cancellation_confirmed'])
        messages.extend(history(('in', 'Новая заявка: теперь нужно собрать шкаф')))
        self.assertIsNone(assistant_policy._withdrawn_staff_visit(messages))


if __name__ == '__main__':
    unittest.main()
