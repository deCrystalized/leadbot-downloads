"""Owner fine1074596: a resolved correction is not three valid CRM prices."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_prices as prices

def rows(*pairs):
    return [dict(id=str(i), direction=d, body=t) for i,(d,t) in enumerate(pairs)]

def history():
    return rows(('in','Повесить две полки. Сколько стоит?'), ('out','от 800р будет'),
                ('in','И до какой суммы предел? От чего зависит?'),
                ('out','12000 рублей будет за две полки'), ('in','Не за 12 тысяч же две полки вешаются'),
                ('out','1200р все верно, стандартный прайс по городу'),
                ('in','1200 или 12000?'), ('system','Диалог принят'), ('out','Я же написал, 1200'))

class CorrectedPrice80Tests(unittest.TestCase):
    def test_resolved_choice_supersedes_wrong_total_and_generic_minimum(self):
        self.assertEqual(prices.withdrawn_quote_indexes(history()), {1,3})
        self.assertEqual(prices.consent(history())['amount'], 1200)
    def test_resolution_has_source_quotes_and_confirmation_not_a_guessed_zero(self):
        evidence=prices.quote_retraction_evidence(history())
        correction=next(r for r in evidence if r.get('kind')=='numeric_correction')
        self.assertEqual(correction['quote_message_id'],'3')
        self.assertEqual(correction['replacement_message_id'],'5')
        self.assertEqual(correction['choice_message_id'],'6')
        self.assertEqual(correction['correction_message_id'],'8')
        self.assertEqual(correction['replacement_amount'],1200)
    def test_amount_difference_alone_does_not_prove_a_correction(self):
        self.assertEqual(prices.withdrawn_quote_indexes(history()[:6]),set())
    def test_customer_words_cannot_correct_the_staff_quote_alone(self):
        h=history();h[-1]['direction']='in'
        self.assertEqual(prices.withdrawn_quote_indexes(h),set())
    def test_pending_correction_cannot_delete_the_old_total(self):
        h=history();h[-1]['out_pending']=True
        self.assertEqual(prices.withdrawn_quote_indexes(h),set())
    def test_an_accepted_old_price_requires_review_instead_of_erasure(self):
        h=history();h.insert(4,dict(id='accept',direction='in',body='Да, 12000 рублей устраивает'))
        self.assertEqual(prices.withdrawn_quote_indexes(h),set())
    def test_independent_scoped_price_is_preserved(self):
        h=history();h[1]['body']='Замена розетки от 800 рублей'
        self.assertEqual(prices.withdrawn_quote_indexes(h),{3})
    def test_diagnostic_payment_condition_is_not_a_superseded_service_minimum(self):
        h=history();h[1]['body']='Выезд 800 рублей, при ремонте бесплатно'
        self.assertEqual(prices.withdrawn_quote_indexes(h),{3})
    def test_new_service_between_minimum_and_total_does_not_erase_the_minimum(self):
        h=history();h[2]['body']='Ещё нужно установить розетку, сколько стоит?'
        self.assertEqual(prices.withdrawn_quote_indexes(h),{3})
    def test_other_amount_and_grouped_digits_are_supported_without_a_special_tariff(self):
        h=history()
        for m in h:m['body']=m['body'].replace('12000','14500').replace('1200','1450')
        h[6]['body']='1 450 или 14 500?'
        self.assertEqual(prices.withdrawn_quote_indexes(h),{1,3})
        self.assertEqual(prices.consent(h)['amount'],1450)

if __name__=='__main__':unittest.main()
