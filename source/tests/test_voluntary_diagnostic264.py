"""Voluntary declining repair is not technically impossible repair."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import assistant_prices as prices
from assistant_store import Store
from extension_assistant import Assistant


def rows(*texts):
    return [dict(id='c'+str(i),direction='in',sender_type='client',body=text)for i,text in enumerate(texts)]


class VoluntaryDiagnostic264Tests(unittest.TestCase):
    def test_exact_frozen_voluntary_refusal_is_not_impossible_repair(self):
        self.assertFalse(prices.conditional_diagnostic_question(rows('А выезд и диагностика сколько стоят, если ремонт делать не будем?')))

    def test_first_person_refusal_variants_remain_distinct_from_feasibility(self):
        for text in ('Если ремонт делать не буду, диагностика платная?',
                     'Если я не буду делать ремонт, сколько стоит диагностика?',
                     'Если мы откажемся от ремонта, диагностику оплачиваем?'):
            with self.subTest(text=text):self.assertFalse(prices.conditional_diagnostic_question(rows(text)))

    def test_impossible_unprofitable_or_unresolved_repair_keeps_the_guard(self):
        for text in ('Если ремонт невозможен, диагностику оплачивать?',
                     'Если ремонт невыгоден, диагностика платная?',
                     'Если не получится починить, диагностика платная?'):
            with self.subTest(text=text):self.assertTrue(prices.conditional_diagnostic_question(rows(text)))

    def test_voluntary_words_do_not_erase_an_earlier_unresolved_technical_condition(self):
        self.assertTrue(prices.conditional_diagnostic_question(rows('Ремонт невыгоден.',
            'А диагностика сколько стоит, если ремонт делать не будем?')))

    def test_unverified_other_actor_not_repairing_is_not_our_voluntary_exception(self):
        self.assertTrue(prices.conditional_diagnostic_question(rows('Если мастер не будет делать ремонт, диагностику оплачивать?')))

    def preview(self,direction,initial,question):
        with tempfile.TemporaryDirectory()as temp,patch.dict(os.environ,
                LEADBOT_ASSISTANT_WORDING='reviewed',LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            app=Assistant(Store(str(Path(temp)/'db')))
            out,code=app.handle(dict(owner='diagnostic264',action='preview',wording_mode='reviewed',
                ctx=dict(convId='synthetic-diagnostic264',dir=direction,city='Чита',partner='7',channel='avito',
                    accountTitle='Георгий '+('КП'if direction=='kp'else'БТ'),
                    itemTitle='Компьютерная помощь'if direction=='kp'else'Ремонт стиральных машин',
                    origin='С1',messages=rows(initial,question))))
        self.assertEqual(code,200);self.assertFalse(out['auto_enabled'])
        return out

    def test_public_partner_kp_answer_uses_its_existing_fee_and_conditions(self):
        out=self.preview('kp','Word и Excel не открываются на ноутбуке.',
            'А выезд и диагностика сколько стоят, если ремонт делать не будем?')
        self.assertFalse(out['needs_operator'],out);self.assertEqual(out['validation'],[])
        self.assertIn('1000',out['reply']);self.assertIn('бесплат',out['reply'])
        self.assertNotRegex(out['reply'],'800|500|БСО|кассов')

    def test_voluntary_exception_does_not_move_kp1000_to_appliances(self):
        out=self.preview('bt','Стиральная машина не включается.',
            'Диагностика без разбора сколько стоит, если ремонт делать не будем?')
        self.assertFalse(out['needs_operator'],out);self.assertEqual(out['validation'],[])
        self.assertIn('800',out['reply']);self.assertNotIn('1000',out['reply'])

    def test_real_impossibility_still_has_no_automatically_approved_fee_reply(self):
        out=self.preview('kp','Word и Excel не открываются на ноутбуке.',
            'Если ремонт невозможен, диагностику оплачивать?')
        self.assertEqual(out['action'],'handoff');self.assertEqual(out['reply'],'')


if __name__=='__main__':unittest.main()
