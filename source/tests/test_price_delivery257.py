"""Unavailable staff speech cannot quote/answer/accept a customer price."""
import copy
import unittest

import assistant_prices as prices
import test_native_wording209 as native_fixture


KNOWN = dict(direction='mnc', city='Чита', partner='7', channel='avito')
WORK = 'Нужно заменить смеситель. Смеситель куплен, материалы есть.'
FIXED = 'Замена смесителя — 2000 рублей за штуку. Такая стоимость Вас устраивает?'
MINIMUM = 'Замена смесителя — от 800 рублей. Такая стоимость Вас устраивает?'


def client(mid, text):
    return dict(id=mid, direction='in', sender_type='client', body=text)


def staff(text=FIXED, status='pending', **extra):
    row = dict(id='staff-price', direction='out', sender_type='operator', body=text)
    if status is not None:
        row['delivery_status'] = status
    row.update(extra)
    return row


def source(row=None):
    return [client('client-request', WORK), row or staff(), client('client-yes', 'Да, устраивает.')]


class PriceDelivery257Tests(unittest.TestCase):
    def test_explicitly_unavailable_price_does_not_establish_consent(self):
        for status in ('pending', 'queued', 'sending', 'failed', 'error', 'cancelled', 'canceled'):
            with self.subTest(status=status):
                result = prices.consent(source(staff(status=status)))
                self.assertEqual(result['status'], 'not_quoted')
                self.assertEqual(result['amount'], 0)
                self.assertIsNone(result['message_id'])

    def test_pending_marker_and_legacy_delivery_field_are_respected(self):
        for row in (staff(status='delivered', out_pending=True), staff(status=None, delivery='PENDING')):
            with self.subTest(row=row):
                self.assertEqual(prices.consent(source(row))['status'], 'not_quoted')

    def test_service_event_is_not_our_price_quote(self):
        for fields in (dict(sender_type='system'), dict(sender_type='avito'),
                       dict(role='system'), dict(speaker_role='service')):
            with self.subTest(fields=fields):
                self.assertEqual(prices.consent(source(staff(status='delivered', **fields)))['status'], 'not_quoted')

    def test_observed_and_legacy_human_prices_keep_original_consent(self):
        for status in ('delivered', 'read', None):
            with self.subTest(status=status):
                result = prices.consent(source(staff(status=status)))
                self.assertEqual(result['status'], 'accepted')
                self.assertEqual(result['amount'], 2000)
                self.assertEqual(result['message_id'], 'staff-price')

    def test_pending_new_price_cannot_replace_the_previous_observed_quote(self):
        rows = [client('work', WORK), dict(staff(MINIMUM, 'delivered'), id='observed-price'),
                staff(FIXED, 'pending'), client('yes', 'Да, устраивает.')]
        result = prices.consent(rows)
        self.assertEqual(result['amount'], 800)
        self.assertEqual(result['message_id'], 'observed-price')
        self.assertEqual(result['status'], 'accepted')

    def test_unavailable_price_response_does_not_advance_objection_stage(self):
        rows = [client('cost', 'Сколько стоит заменить смеситель?'),
                staff('Стоимость скажу после осмотра.', 'pending'), client('followup', 'А примерно?')]
        self.assertEqual(prices.price_turns(rows), 1)
        self.assertTrue(prices.asks_current(rows))
        self.assertIn('Сколько стоит', prices.current_price_question(rows))

    def test_observed_price_response_still_advances_the_stage(self):
        rows = [client('cost', 'Сколько стоит заменить смеситель?'),
                staff('Стоимость скажу после осмотра.', 'delivered'), client('followup', 'А примерно?')]
        self.assertEqual(prices.price_turns(rows), 2)

    def test_price_reminder_cannot_borrow_an_earlier_newly_superseded_subject(self):
        rows = [client('cost', 'Сколько стоит заменить смеситель?'),
                client('arrival', 'Во сколько сможете приехать?'), client('followup', 'А примерно?')]
        self.assertFalse(prices.asks_current(rows))

    def test_resolved_price_and_new_duration_question_are_not_another_price_stage(self):
        rows = [client('cost', 'Сколько стоит заменить смеситель?'),
                staff('Стоимость скажу после осмотра.', 'delivered'),
                client('duration', 'Сколько времени займёт работа?'), client('followup', 'А примерно?')]
        self.assertFalse(prices.asks_current(rows))

    def test_pending_fixed_tariff_cannot_be_verified_by_a_direct_caller(self):
        rows = source()
        state = dict(message_id='staff-price', amount=2000, status='accepted')
        self.assertIsNone(prices.mnc_fixed_quote(rows, KNOWN, state))
        self.assertFalse(prices.prior_quote_verified(rows, KNOWN, state))

    def test_delivered_fixed_tariff_and_primary_unit_are_still_verified(self):
        rows = source(staff(status='delivered'))
        state = prices.consent(rows)
        self.assertEqual(prices.mnc_fixed_quote(rows, KNOWN, state)['amount'], 2000)
        self.assertTrue(prices.prior_quote_verified(rows, KNOWN, state))

    def test_unavailable_correction_does_not_withdraw_a_real_quote(self):
        rows = [client('work', WORK), staff(MINIMUM, 'delivered'),
                dict(staff('Ой, не вам', 'pending'), id='correction')]
        self.assertEqual(prices.quote_retraction_evidence(rows), [])

    def test_observed_correction_cannot_withdraw_an_unavailable_quote(self):
        rows = [client('work', WORK), staff(MINIMUM, 'pending'),
                dict(staff('Ой, не вам', 'delivered'), id='correction')]
        self.assertEqual(prices.quote_retraction_evidence(rows), [])

    def test_observed_correction_keeps_original_source_positions(self):
        rows = [client('work', WORK), dict(staff('Диалог принят', 'delivered'), sender_type='system'),
                staff(MINIMUM, 'delivered'), dict(staff('Ой, не вам', 'delivered'), id='correction')]
        evidence = prices.quote_retraction_evidence(rows)
        self.assertEqual(evidence[0]['quote_index'], 2)
        self.assertEqual(evidence[0]['quote_message_id'], 'staff-price')

    def test_pending_bare_amount_cannot_trigger_a_quote_handoff(self):
        self.assertFalse(prices.unverified_bare_quote([client('work', WORK), staff('От 800', 'pending')]))

    def test_source_rows_and_delivery_metadata_are_not_rewritten(self):
        rows = source(); original = copy.deepcopy(rows)
        prices.consent(rows); prices.price_turns(rows); prices.current_price_question(rows)
        self.assertEqual(rows, original)


class NativePriceDelivery257Tests(unittest.TestCase):
    setUp = native_fixture.NativeWording209Tests.setUp
    tearDown = native_fixture.NativeWording209Tests.tearDown

    def preview(self, price, status):
        self.ctx.update(itemTitle='Сантехника', messages=source(staff(price, status)))
        result, code = self.app.handle(dict(owner='wording209', action='preview',
            wording_mode='neural_review', ctx=self.ctx))
        self.assertEqual(code, 200)
        return result

    def test_pending_minimum_does_not_send_a_simple_intake_to_a_human(self):
        result = self.preview(MINIMUM, 'pending')
        self.assertTrue(result.get('pending_model'))
        self.assertEqual(result['crm_flags']['price_consent'], 'not_quoted')

    def test_pending_fixed_price_is_not_recorded_as_customer_acceptance(self):
        result = self.preview(FIXED, 'pending')
        self.assertTrue(result.get('pending_model'))
        self.assertEqual(result['crm_flags']['price_consent'], 'not_quoted')

    def test_delivered_fixed_price_keeps_customer_acceptance(self):
        result = self.preview(FIXED, 'delivered')
        self.assertTrue(result.get('pending_model'))
        self.assertEqual(result['crm_flags']['price_consent'], 'accepted')


if __name__ == '__main__':
    unittest.main()
