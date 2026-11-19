"""Rule scope from primary DOC372/452–453, KP474–494, TG1-664."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import assistant_catalog as catalog
import assistant_prices as prices
from test_manual_batch9_intent import history
import test_manual_batch9_intent as intent_tests


class ManualBatch9RuleTests(unittest.TestCase):
    def test_window_glass_is_installation_not_oven_or_routine_adjustment(self):
        known=dict(direction='mnc',title='Мастер на час')
        for text in ('Можете вставить стекло в окно?', 'Заменить стеклопакет в окне',
                     'Меняете личину в замке и можете вставить стекло в окно?\nВставить окно вместо пластиковой панели'):
            r=catalog.choose(text,known)
            self.assertNotEqual(r['status'],'supported')
            self.assertIn('DOC-L0372',r['rules'])
            self.assertNotIn('DOC-L0399',r['rules'])
        for text in ('Поменять резинки на двух пластиковых окнах', 'Отрегулировать окно',
                     'Помыть стекло в окне'):
            r=catalog.choose(text,known)
            self.assertNotIn('window-glass',[x['id'] for x in r.get('items',[])])

    def test_weekly_work_contract_requires_review_but_ordinary_org_does_not(self):
        r=intent_tests.ManualBatch9IntentTests().assess(('in','Большой объём кабеля и коробок'),('out','Оплата как у вас?'),
            ('in','500 руб м2 как физ лицо, 570 как ИП, 620 если ООО с НДС. Раз в неделю стараемся.'))
        self.assertEqual(r['action'],'handoff');self.assertIn('DOC-L0452',r['rule_ids'])
        ordinary=intent_tests.ManualBatch9IntentTests().assess(('in','Заменить смеситель в офисе, оплата наличными физ лицу'))
        self.assertNotRegex(ordinary['reason'],'еженедельн|подряд|договора')

    def test_backlight_general_price_stages_never_become_a_fixed_tariff(self):
        known=dict(direction='kp',partner='7');text='Замена подсветки телевизора Xiaomi L50M5-5ARU'
        messages=history(('in','Сколько стоит '+text+'?'))
        first=prices.answer(messages,known,text)
        self.assertIn('после осмотра',first['reply']);self.assertFalse(first['amounts'])
        messages+=history(('out',first['reply']),('in','А примерно какая цена?'))
        second=prices.answer(messages,known,text);self.assertEqual(second['amounts'],[500]);self.assertIn('от 500',second['reply'])
        messages+=history(('out',second['reply']),('in','А какая точная стоимость?'))
        third=prices.answer(messages,known,text);self.assertFalse(third['amounts']);self.assertIn('TG1-664',third['rules'])
        self.assertNotRegex(third['reply'],r'\d|гарантир|точно\s+стоит')

    def test_unanswered_price_question_does_not_unlock_the_numeric_stage(self):
        messages=history(('in','Сколько стоит замена подсветки телевизора?'),
                         ('out','Телевизор не били?'),('in','Нет. А стоимость?'),
                         ('out','Когда удобно?'),('in','Сколько стоит?'))
        for cut in (3,5):
            out=prices.answer(messages[:cut],dict(direction='kp',partner='7'),'Замена подсветки телевизора')
            self.assertFalse(out['amounts']);self.assertIn('после осмотра',out['reply'])


if __name__=='__main__':unittest.main()
