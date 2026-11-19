"""A new diagnostic-only request takes priority over an earlier repair basis."""
import unittest
import assistant_prices as prices

KNOWN = dict(direction='mnc', channel='avito', partner='7', city='Елец',
             account_name='Учебный мастер МНЧ', title='Мастер на час')
HOSE = 'Нужно заменить шланг к смесителю в кухне. Шланг имеется.'
WIRE = 'Нужно нарастить обломанный провод на выключателе света.'


def message(mid, body, direction='in'):
    return dict(id=mid, body=body, direction=direction,
                sender_type='client' if direction == 'in' else 'operator',
                delivery_status='delivered')


class DiagnosticPricePrecedence128Tests(unittest.TestCase):
    def check_diagnostic(self, job):
        rows = [message('job', job), message('diagnostic', 'Нужна только диагностика без ремонта. Сколько стоит?')]
        answer = prices.answer(rows, KNOWN, '\n'.join(m['body'] for m in rows))
        self.assertEqual(answer['amounts'], [])
        self.assertIn('бесплатный', answer['reply'])
        self.assertIsNone(prices.mnc_price_basis(rows, KNOWN))
        quoted = rows + [message('quote', 'Диагностика — от 500 рублей.', 'out'), message('yes', 'Да')]
        self.assertFalse(prices.prior_quote_verified(quoted, KNOWN, prices.consent(quoted)))

    def test_diagnostic_after_hose_does_not_inherit800(self):
        self.check_diagnostic(HOSE)

    def test_diagnostic_after_wire_does_not_inherit_per_metre_price(self):
        self.check_diagnostic(WIRE)

    def check_ordinary(self, job, kind, quote):
        rows = [message('job', job)]
        self.assertEqual(prices.mnc_price_basis(rows, KNOWN)['kind'], kind)
        quoted = rows + [message('quote', quote, 'out'), message('yes', 'Да')]
        self.assertTrue(prices.prior_quote_verified(quoted, KNOWN, prices.consent(quoted)))

    def test_ordinary_hose_keeps_its_minimum(self):
        self.check_ordinary(HOSE, 'hose', 'Замена шланга — от 800 рублей.')

    def test_ordinary_wire_keeps_its_unit(self):
        self.check_ordinary(WIRE, 'wire', 'Работы с проводами — от 800 рублей за метр.')

    def check_return_to_repair_price(self, job, kind):
        rows = [message('job', job), message('diagnostic', 'Пока нужна только диагностика без ремонта.'),
                message('repair', 'А сколько будет стоить ремонт?')]
        self.assertFalse(prices.diagnostic_only_applies(rows))
        self.assertEqual(prices.mnc_price_basis(rows, KNOWN)['kind'], kind)

    def test_hose_repair_price_question_not_diagnostic_only_quote(self):
        self.check_return_to_repair_price(HOSE, 'hose')

    def test_wire_repair_price_question_not_diagnostic_only_quote(self):
        self.check_return_to_repair_price(WIRE, 'wire')
