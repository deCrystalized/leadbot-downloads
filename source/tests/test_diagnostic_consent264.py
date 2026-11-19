"""Explicit diagnostic terms are distinct from LPR and repair consent."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import assistant_prices as prices

QUOTE='Выезд и диагностика бесплатны при выполнении работ. При отказе от работ стоимость составит 1000 рублей.'
ANSWER='Да, эти условия диагностики принимаю. Решение принимаю я, оплачиваю сам и буду присутствовать.'


def history(quote=QUOTE,answer=ANSWER):
    return [dict(id='o1',direction='out',sender_type='operator',delivery_status='delivered',body=quote),
            dict(id='o2',direction='out',sender_type='operator',delivery_status='delivered',body='Такая стоимость вас устраивает?'),
            dict(id='c1',direction='in',sender_type='client',delivery_status='delivered',body=answer)]


class DiagnosticConsent264Tests(unittest.TestCase):
    def test_frozen_exact_acceptance_retains_quote_amount_and_source_ids(self):
        out=prices.consent(history())
        self.assertEqual(out['status'],'accepted');self.assertEqual(out['amount'],1000)
        self.assertEqual(out['message_id'],'o1');self.assertEqual(out['accepted_message_id'],'c1')

    def test_lpr_statement_alone_is_not_price_consent(self):
        self.assertEqual(prices.consent(history(answer='Решение принимаю я, оплачиваю сам и буду присутствовать.'))['status'],'pending')

    def test_diagnostic_acceptance_does_not_accept_an_unrelated_repair_quote(self):
        self.assertEqual(prices.consent(history(quote='Ремонт от 500 рублей.'))['status'],'pending')

    def test_diagnostic_terms_do_not_accept_an_ambiguous_or_separate_repair_amount(self):
        for quote in ('Диагностика 1000 рублей, ремонт 2000 рублей.',
                      'Диагностика бесплатная, ремонт 2000 рублей.',
                      'Диагностика от 1000 рублей.'):
            with self.subTest(quote=quote):self.assertEqual(prices.consent(history(quote=quote))['status'],'pending')

    def test_absent_quote_or_another_question_has_no_diagnostic_acceptance(self):
        rows=history();rows.pop(0)
        self.assertEqual(prices.consent(rows)['status'],'not_quoted')
        rows=history();rows[1]['body']='Вы будете присутствовать?'
        self.assertEqual(prices.consent(rows)['status'],'pending')

    def test_conditions_negation_or_objection_are_not_unqualified_acceptance(self):
        for text in ('Эти условия диагностики не принимаю.', 'Да, эти условия диагностики принимаю, если не дороже.',
                     'Да, эти условия диагностики принимаю. Но только без доплат.'):
            with self.subTest(text=text):self.assertNotEqual(prices.consent(history(answer=text))['status'],'accepted')

    def test_system_failed_or_quoted_acceptance_does_not_create_client_agreement(self):
        for change in (dict(sender_type='system'),dict(delivery_status='failed'),dict(body='Сосед сказал: «'+ANSWER+'»')):
            rows=history();rows[-1].update(change)
            with self.subTest(change=change):self.assertNotEqual(prices.consent(rows)['status'],'accepted')


if __name__=='__main__':unittest.main()
