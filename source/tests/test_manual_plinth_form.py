"""A documented human tariff may be valid without confirming price consent."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_prices as prices
import contact_facts
from assistant_store import Store
from extension_assistant import Assistant


def msg(text, direction='in'):
    return dict(id=direction+text, body=text, direction=direction)


class ManualPlinthFormTests(unittest.TestCase):
    def rows(self, quote='Укладка плинтуса/порожка (на клипсы/саморезы) 400₽ м²'):
        return [msg('Установить напольный плинтус, цена?'), msg('Здравствуйте', 'out'),
                msg('У вас всё в наличии уже?', 'out'), msg('Ну да плинтуса и шурупы, а ещё что нужно'),
                msg('А по цене сколько?'), msg('От 800р у меня работа', 'out'), msg('800 р что, комната 12 кв'),
                msg(quote, 'out'), msg('Сумма какая будет итоговая?'),
                msg('Давайте подъеду, посмотрю и сориентирую по цене', 'out'),
                msg('Линолеум кое где подрезать надо будет'), msg('Приеду сориентирую', 'out'),
                msg('Через час-полтора удобно?', 'out'), msg('Ок'), msg('110 мкр д5 бл2 кв 58')]

    def form(self, rows, city='Улан-Удэ'):
        ctx=dict(convId='synthetic-plinth',city=city,dir='mnc',channel='avito',partner='7',
                 accountTitle='Григорий МНЧ',itemTitle='Мастер на час',messages=rows)
        with tempfile.TemporaryDirectory() as p:
            result,code=Assistant(Store(p+'/db')).handle(dict(owner='offline-plinth',action='checklist',ctx=ctx))
        self.assertEqual(code,200);self.assertFalse(result['auto_enabled']);return result

    def test_primary_area_tariff_is_valid_but_time_agreement_does_not_confirm_price(self):
        rows=self.rows();consent=prices.consent(rows)
        self.assertEqual(consent['amount'],400);self.assertEqual(consent['status'],'pending')
        self.assertFalse(prices.prior_quote_verified(rows,dict(direction='mnc',city='Улан-Удэ'),consent))
        result=self.form(rows)
        self.assertFalse(result['hard_block']);self.assertIn('DOC-L0515',result['rule_ids'])
        self.assertFalse(next(x for x in result['results'] if x['key']=='price_consent')['done'])
        self.assertEqual(result['facts']['address']['building'],'5 блок 2')
        self.assertTrue(any('110 мкр д5 бл2 кв 58' in x for x in result['facts']['comment_lines']))

    def test_wrong_amount_units_totals_and_missing_method_remain_blocked(self):
        for quote in ['Плинтус на саморезы 800₽ м²','Плинтус на саморезы 400₽ за погонный метр',
                      'Плинтус на саморезы 400₽ за всё','От 400₽ м² плинтус на саморезы',
                      'Плинтус на клей 400₽ м²','Плинтус на саморезы 400₽', 'Плинтус 400₽ м²',
                      'Плинтус на саморезы 400₽ м², линолеум 350₽ м²']:
            with self.subTest(quote=quote):self.assertTrue(self.form(self.rows(quote))['hard_block'])

    def test_glue_combined_methods_and_moscow_are_separately_scoped(self):
        for method,amount,city,ref in [('на клей',500,'Тула','DOC-L0516'),
                ('на саморезы + если клеить плинтус',600,'Тула','DOC-L0517'),
                ('на саморезы',500,'Москва','DOC-L0515'),('на клей',600,'Москва','DOC-L0516')]:
            out=self.form(self.rows(f'Плинтус {method} {amount} рублей за квадратный метр'),city)
            self.assertFalse(out['hard_block']);self.assertIn(ref,out['rule_ids'])
        self.assertTrue(self.form(self.rows(),'Москва')['hard_block'])
        self.assertTrue(self.form(self.rows(),'')['hard_block'])

    def test_multiple_prior_work_kinds_cannot_inherit_one_tariff(self):
        rows=self.rows();rows.insert(1,msg('Ещё уложить ламинат'))
        self.assertTrue(self.form(rows)['hard_block'])

    def test_block_and_literal_house_letter_are_different(self):
        for text,building in [('110 мкр д5 бл2 кв 58','5 блок 2'),
                ('ул Ленина дом 5 блок 2 кв 58','5 блок 2'),
                ('110 мкр д5б/2 кв 58','5б/2'),('110 мкр д5 кв58','5')]:
            facts=contact_facts.collect([msg(text)],dict(city='Улан-Удэ'))
            self.assertEqual(facts['address']['building'],building,text)


if __name__=='__main__':unittest.main()
