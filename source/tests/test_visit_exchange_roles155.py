"""Reciprocal scheduling speech must retain its actors and evidential limits."""
import unittest

import assistant_policy as policy
import test_dialogue_context150 as fixture
import test_visit_day_preference154 as day_fixture


def exchange(client_proposes=True):
    if client_proposes:
        return [fixture.row('На 16.30 вы сможете заехать, удобно?', mid='proposal'),
                fixture.row('Да, напишите полный адрес куда нужно приехать', 'out', 'answer')]
    return [fixture.row('К 16:30 удобно?', 'out', 'proposal'), fixture.row('Да, удобно', mid='answer')]


class VisitExchangeRoles155Tests(unittest.TestCase):
    def test_staff_answer_to_client_proposal_keeps_both_actors(self):
        v = policy._accepted_staff_visit(exchange())
        self.assertEqual((v['proposal_speaker'], v['answer_speaker']), ('client', 'staff'))

    def test_client_answer_to_staff_proposal_keeps_both_actors(self):
        v = policy._accepted_staff_visit(exchange(False))
        self.assertEqual((v['proposal_speaker'], v['answer_speaker']), ('staff', 'client'))

    def test_source_quotes_and_ids_are_retained(self):
        h = exchange(); v = policy._accepted_staff_visit(h)
        self.assertEqual((v['proposal_message_id'], v['proposal_quote']), ('proposal', h[0]['body']))
        self.assertEqual((v['answer_message_id'], v['answer_quote']), ('answer', h[1]['body']))

    def test_reciprocal_speech_is_not_crm_or_current_availability_proof(self):
        for h in (exchange(), exchange(False)):
            with self.subTest(h=h):
                v = policy._accepted_staff_visit(h)
                self.assertFalse(v['crm_write_confirmed']); self.assertFalse(v['current_availability_verified'])
                self.assertEqual(v['source'], 'observed_historical_timed_exchange')

    def test_later_client_address_does_not_become_the_acceptance(self):
        h = exchange() + [fixture.row('Ленина 12 подъезд 6', mid='address')]
        v = policy._accepted_staff_visit(h)
        self.assertEqual((v['answer_message_id'], v['answer_speaker']), ('answer', 'staff'))

    def test_later_day_restriction_does_not_become_current_availability(self):
        h = exchange() + [fixture.row('Только вечером, днём работаю', mid='restriction')]
        v = policy._accepted_staff_visit(h)
        self.assertEqual(v['answer_message_id'], 'answer'); self.assertFalse(v['current_availability_verified'])

    def test_duplicate_source_identity_is_not_arbitrarily_attributed(self):
        h = exchange(); h.append(dict(h[0]))
        self.assertIsNone(policy._accepted_staff_visit(h))

    def test_pending_staff_acceptance_is_not_an_observed_exchange(self):
        h = exchange(); h[1]['out_pending'] = True
        self.assertIsNone(policy._accepted_staff_visit(h))

    def test_staff_response_rejecting_time_does_not_become_acceptance(self):
        h = exchange(); h[1]['body'] = 'Нет, не смогу'
        self.assertIsNone(policy._accepted_staff_visit(h))

    def test_client_legacy_role_does_not_override_explicit_out_direction(self):
        h = exchange(); h[1]['role'] = 'client'
        self.assertEqual(policy._accepted_staff_visit(h)['answer_speaker'], 'staff')

    def test_operator_incoming_cannot_be_attributed_to_client(self):
        h = exchange(False); h[1]['sender_type'] = 'operator'
        self.assertIsNone(policy._accepted_staff_visit(h))

    def test_actual_reciprocal_lookup_reason_does_not_claim_client_accepted_staff_offer(self):
        # Use the normal installed-preview path with one missing qualification
        # and an already observed reciprocal exchange; never create a lead.
        h = day_fixture.history()[:1] + exchange() + [fixture.row('Ленина 12', mid='address')]
        fixture_case = day_fixture.VisitDayPreference154Tests('test_direct_alternative_is_an_unselected_day')
        self.addCleanup(fixture_case.doCleanups)
        o, t = fixture_case.preview(h)
        self.assertEqual(o['action'], 'handoff'); self.assertEqual(o['reply'], '')
        self.assertIn('Сотрудник ответил на предложение времени клиента', o['reason'])
        self.assertNotIn('Клиент подтвердил предложение времени', o['reason'])
        self.assertEqual(o['existing_visit_evidence']['answer_speaker'], 'staff')

