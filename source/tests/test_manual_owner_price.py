"""A human quote must be checked against its service rule, not the bot's script order."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_prices as prices
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant


def msg(text, direction='in', number=0):
    return dict(id=str(number) + direction + text[:35], direction=direction, body=text)


class ManualOwnerPriceTests(unittest.TestCase):
    def history(self, job='Собрать комод', quote='ОТ 1500р у меня работа, более точно на месте вас сориентирую'):
        return [msg(job), msg('Здравствуйте', 'out', 1), msg('Какая цена будет?', number=2),
                msg('Могу в 19', 'out', 3), msg('Адрес и номер?', 'out', 4),
                msg('Ленина 5, кв 90, 7 подъезд', number=5), msg('А что по цене будет?', number=6),
                msg(quote, 'out', 7), msg('Хорошо', number=8), msg('В 19 буду у вас', 'out', 9), msg('Ок', number=10)]

    def form(self, rows):
        ctx=dict(convId='synthetic-owner-price',city='Оренбург',dir='mnc',channel='avito',partner='7',
                 accountTitle='Григорий МНЧ',itemTitle='Мастер на час',origin='С79.2',messages=rows)
        with tempfile.TemporaryDirectory() as p:
            result,code=Assistant(Store(p+'/db')).handle(dict(owner='offline-owner-price',action='checklist',ctx=ctx))
        self.assertEqual(code,200);self.assertFalse(result['auto_enabled']);return result

    def test_accepted_documented_assembly_minimum_is_valid_at_early_human_quote(self):
        for job in ('Собрать комод', 'Сможете сделать комод, пришел без инструкции'):
            rows=self.history(job)
            self.assertEqual(prices.price_turns(rows),1)
            self.assertTrue(prices.prior_quote_verified(rows,dict(direction='mnc'),prices.consent(rows)))
            self.assertTrue(prices.prior_quote_verified(rows,dict(direction='mnc'),prices.consent(rows),manual=True))
            out=self.form(rows);self.assertFalse(out['hard_block']);self.assertIn('DOC-L0326',out['rule_ids'])
            self.assertTrue(next(r for r in out['results'] if r['key']=='price_consent')['done'])

    def test_wrong_amount_fixed_total_and_multiple_services_do_not_inherit_minimum(self):
        for job,quote in [('Собрать комод','От 1000 рублей'),('Собрать комод','1500 рублей'),
                          ('Собрать комод','От 1500 рублей за всё, окончательная стоимость'),
                          ('Собрать шкаф и установить мойку','От 1500 рублей')]:
            out=self.form(self.history(job,quote));self.assertTrue(out['hard_block'],(job,quote))

    def test_client_stated_absence_of_instructions_and_apartment_are_not_missing(self):
        rows=self.history('Сможете сделать комод, пришел без инструкции')
        out=self.form(rows)
        for key in ('instructions','place','volume','materials'):
            row=next(r for r in out['results'] if r['key']==key)
            self.assertTrue(row['done'],key);self.assertTrue(row['evidence'],key)
        self.assertIn('без инструкции',next(r for r in out['results'] if r['key']=='instructions')['answer'])
        self.assertNotRegex(next(r for r in out['results'] if r['key']=='materials')['answer'],'все|полный|комплектный')
        state=qs.inspect([msg('Комод придет завтра, какая цена?')])
        self.assertEqual(state['materials']['status'],'missing')
        state=qs.inspect([msg('Нужно собрать шкафы')])
        self.assertEqual(state['volume']['status'],'missing')

    def test_bots_own_first_price_response_stays_non_numeric(self):
        rows=[msg('В Оренбурге собрать комод, сколько стоит?')]
        out=prices.answer(rows,dict(direction='mnc'),rows[0]['body'])
        self.assertEqual(out['amounts'],[]);self.assertNotIn('1500',out['reply'])


if __name__=='__main__':
    unittest.main()
