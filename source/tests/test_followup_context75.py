"""Client access conditions and existing-equipment status from manual812/819."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_policy
import contact_facts
from assistant_store import Store
from extension_assistant import Assistant


def history(*pairs):
    return [dict(id=str(i), direction=d, body=t, created_at='2026-10-19T10:00:00Z')
            for i, (d, t) in enumerate(pairs)]


class FollowupContext75Tests(unittest.TestCase):
    def test_reverse_access_clause_retains_arrival_and_exact_customer_words(self):
        for body in ('Позвоните по телефону домофон не работает',
                     'Наберите мне, домофона нет',
                     'Позвоните пожалуйста по номеру — домофон отсутствует'):
            f = contact_facts.collect(history(('in', body)))
            self.assertEqual(f['call_timing'], 'upon_arrival')
            self.assertEqual(f['evidence']['call_before_visit']['quote'], body)
            self.assertIn('Позвонить при подъезде по просьбе клиента.', f['comment_lines'])

    def test_explicit_advance_call_keeps_timing_in_both_orders(self):
        for body in ('Позвоните по телефону заранее, домофон не работает',
                     'Домофон не работает, позвоните за 15 минут',
                     'Позвоните перед выездом, домофона нет'):
            self.assertEqual(contact_facts.collect(history(('in', body)))['call_timing'], 'before_visit')

    def test_other_call_time_negation_and_sentence_boundary_do_not_invent_arrival(self):
        for body in ('Позвоните по телефону сейчас, домофон не работает',
                     'Позвоните по телефону после ремонта, домофон не работает',
                     'Не звоните по телефону, домофона нет',
                     'Позвоните по телефону. Домофон не работает',
                     'Позвоните по телефону, домофон работает'):
            self.assertEqual(contact_facts.collect(history(('in', body)))['call_timing'], 'not_stated')

    def test_staff_access_promise_is_not_customer_condition(self):
        for direction in ('out', 'note', 'system'):
            self.assertEqual(contact_facts.collect(history((direction,
                'Позвоните по телефону домофон не работает')))['call_timing'], 'not_stated')

    def test_own_equipment_ready_question_keeps_unverified_source(self):
        body = 'Здравствуйте, можно узнать когда будет готов мой принтер и ноутбук?'
        e = assistant_policy._service_readiness_request(history(('in', body)))
        self.assertEqual(e['message_id'], '0')
        self.assertEqual(e['quote'], body)
        self.assertEqual(e['source'], 'client_report_unverified')
        self.assertFalse(e['crm_receipt_confirmed'])
        self.assertFalse(e['repair_completion_confirmed'])

    def test_handover_date_followup_does_not_reopen_new_intake(self):
        rows = history(('in', 'Принтер не берёт бумагу'), ('out', 'Ожидайте через час'),
                       ('in', 'Когда будет готов мой принтер и ноутбук?'),
                       ('in', '13 числа его отдала'))
        with tempfile.TemporaryDirectory() as tmp:
            out, code = Assistant(Store(tmp+'/offline.sqlite')).handle(dict(owner='offline-followup75',
                action='preview',ctx=dict(convId='synthetic-ready75',dir='kp',city='Москва',partner='7',
                                         channel='avito',messages=rows)))
        self.assertEqual(code, 200)
        self.assertEqual(out['action'], 'handoff')
        self.assertIn('существующей заявки', out['reason'])
        self.assertNotIn('ОКК', out['reason'])  # A status question alone is not a complaint.
        self.assertFalse(out['reply'])
        self.assertFalse(out['auto_enabled'])
        self.assertEqual(out['equipment_readiness_evidence']['message_id'], '2')

    def test_explicit_prior_handover_supports_ready_question_without_my(self):
        rows = history(('in', 'Я отдала вам принтер на ремонт'),
                       ('in', 'Когда будет готов принтер?'))
        self.assertTrue(assistant_policy._service_readiness_request(rows))

    def test_hypothetical_future_delivery_and_other_workshop_do_not_prove_our_order(self):
        for body in ('Когда будет готов мой принтер, если закажу ремонт?',
                     'Если отдам в ремонт, когда будет готов мой принтер?',
                     'Когда будет готов мой принтер? Завтра его привезу.',
                     'Когда будет готов мой принтер в другой мастерской?',
                     'Когда будет готов стол для сборки?',
                     'Когда доставят новый принтер?'):
            self.assertFalse(assistant_policy._service_readiness_request(history(('in', body))), body)

    def test_operator_and_pasted_review_do_not_create_customer_status_request(self):
        for direction, body in (('out', 'Когда будет готов мой принтер?'),
                                ('note', 'Когда будет готов мой принтер?'),
                                ('in', 'Сделка состоялась\nКогда будет готов мой принтер?')):
            self.assertFalse(assistant_policy._service_readiness_request(history((direction, body))))

    def test_unfulfilled_handover_is_not_a_receipt(self):
        for body in ('Я ещё не отдала вам принтер', 'Если я отдала вам принтер',
                     'Я отдала принтер в другой сервис, а вам хочу привезти ноутбук'):
            self.assertFalse(assistant_policy._service_readiness_request(history(
                ('in', body), ('in', 'Когда будет готов принтер?'))))


if __name__ == '__main__':
    unittest.main()
