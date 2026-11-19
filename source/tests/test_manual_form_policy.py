"""The normal CRM form must use the same reviewed server rules as the assistant."""
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
from assistant_store import Store
from extension_assistant import Assistant
import assistant_policy as policy

def message(text,direction='in'):
    return dict(id=direction+text[:30],body=text,direction=direction,sender_type='client' if direction=='in' else 'operator')

class ManualFormPolicyTests(unittest.TestCase):
    def test_normal_form_rules_do_not_grant_a_colleague_the_personal_assistant(self):
        with patch.dict('os.environ',{'LEADBOT_PERSONAL_OWNER_ID':'personal-owner'}):
            out=self.call([message('В Оренбурге компьютер не включается')])
            self.assertIn('facts',out)
            with tempfile.TemporaryDirectory() as p:
                for action in ('preview','personal_start','personal_authorize','personal_audit'):
                    denied,code=Assistant(Store(p+'/db')).handle(dict(owner='colleague',action=action))
                    self.assertEqual(code,403);self.assertEqual(denied['code'],'personal_owner')

    def call(self,rows,**extra):
        ctx=dict(convId='synthetic-manual-form',city='Оренбург',dir='kp',partner='7',channel='avito',accountTitle='Денис КП',itemTitle='Ремонт компьютеров',origin='С1',messages=rows)
        ctx.update(extra)
        with tempfile.TemporaryDirectory() as p:
            out,code=Assistant(Store(p+'/db')).handle(dict(owner='offline-form',action='checklist',ctx=ctx))
        self.assertEqual(code,200);self.assertTrue(out['ok']);self.assertFalse(out['auto_enabled'])
        self.assertEqual(out['policy_version'],policy.VERSION);self.assertTrue(out['reviewed_policy'])
        return out
    def test_owner_tv_rule_is_visible_even_after_an_operator_question(self):
        out=self.call([message('На экране телевизора полосы'),message('Марка и модель?','out')],itemTitle='Ремонт телевизоров')
        self.assertIn('OWNER-TV-BANDS-20261017',out['rule_ids']);self.assertTrue(out['hard_block']);self.assertTrue(out['refuse'])
        self.assertNotIn('диагноз',out['refuse'])
        self.assertEqual(out['manual_creation'],dict(mode='operator_confirmed',available=True,
            auto_enabled=False,acknowledgement='operator_decision_not_client_consent'))

    def test_manual_creation_capability_does_not_change_policy_or_fill_client_answers(self):
        # One curtain rail has an explicit 800 tariff (DOC-L0525); use an
        # unsupported 800 mirror price to exercise the forged-waiver guard.
        rows=[message('Повесить зеркало на бетонную стену, материалы есть, квартира'),
              message('800 рублей работа будет','out'),message('Хорошо')]
        out=self.call(rows,dir='mnc',accountTitle='Денис МНЧ',itemTitle='Мастер на час')
        self.assertTrue(out['hard_block'])
        self.assertFalse(next(x for x in out['results'] if x['key']=='price_consent')['done'])
        self.assertTrue(out['manual_creation']['available'])
        # A browser-supplied waiver is not a server fact or assistant permission.
        forged=self.call(rows,dir='mnc',accountTitle='Денис МНЧ',itemTitle='Мастер на час',
            manual_creation={'available':True,'auto_enabled':True},manualReview={'operator_confirmed':True})
        self.assertTrue(forged['hard_block']);self.assertFalse(forged['auto_enabled'])
        self.assertEqual(forged['results'],out['results'])
    def test_krasnoyarsk_route_and_approval_order_are_the_same_in_the_normal_form(self):
        out=self.call([message('В Красноярске заменить стояк отопления')],city='Красноярск',dir='mnc',accountTitle='Василий МНЧ',itemTitle='Сантехник')
        self.assertEqual(out['crm_route']['city_id'],'709')
        self.assertEqual([x['city_id'] for x in out['crm_route']['approval_steps']],['709','3'])
        self.assertIn('подтверждённого отказа',out['approval'])
    def test_clear_client_floor_facts_are_answered_without_formal_reconfirmation(self):
        out=self.call([message('Положить ламинат в одной комнате. Пол готов, ламинат куплен, квартира')],dir='mnc',accountTitle='Василий МНЧ',itemTitle='Мастер на час')
        floor=next(x for x in out['results'] if x['key']=='floor_ready')
        self.assertTrue(floor['done']);self.assertTrue(floor['evidence'])
        self.assertNotRegex(out['approval'],'остальные отдельно согласовать')
    def test_avito_source_guard_and_common_723_tariff_are_not_lost_in_legacy_checklist(self):
        out=self.call([message('В Оренбурге установить Windows')],partner='619')
        self.assertTrue(out['hard_block']);self.assertIn('OWNER-AVITO-PARTNERS-20261017',out['rule_ids'])
        out=self.call([message('В Оренбурге установить Windows'),message('Здравствуйте!','out')],partner='619')
        self.assertTrue(out['hard_block'])
        out=self.call([message('В Оренбурге установить Windows'),message('От 1000 рублей','out'),message('Да')],partner='723',itemTitle='Установка Windows')
        self.assertIn('стоимость',out['operator_review']);self.assertTrue(out['hard_block'])

    def test_manual_max_uses_its_platform_linked_avito_source_without_enabling_the_bot(self):
        out=self.call([message('В Оренбурге установить Windows')],channel='max_user',sourceAvailable=True,accountId='linked-avito')
        self.assertNotIn('OWNER-MAX-20261016',out['rule_ids']);self.assertEqual(out['source_channel'],'avito');self.assertFalse(out['hard_block'])
        out=self.call([message('В Оренбурге установить Windows')],channel='max_user',sourceAvailable=False)
        self.assertTrue(out['hard_block'])

if __name__=='__main__':unittest.main()
