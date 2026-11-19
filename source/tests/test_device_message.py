"""Viewed error codes are evidence of a message, never a diagnosis or contact."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import personal_media
import assistant_policy as policy
import contact_facts
import qualification_state as qs


class DeviceMessageTests(unittest.TestCase):
    def observation(self):return dict(content_kind='device_message',error_system='xbox_live',error_code='80154058')

    def test_bounded_code_and_system_are_normalized(self):
        self.assertEqual(personal_media.normalize_observations(self.observation()),self.observation())

    def test_code_requires_message_kind_and_matching_system(self):
        for change in [dict(content_kind='product_photo'),dict(error_system='bank'),dict(error_code=''),dict(error_system=''),dict(error_code='https://example.test'),dict(error_code='79001112233')]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                personal_media.normalize_observations(dict(self.observation(),**change))

    def test_reviewed_code_gets_activity_question_without_cause_or_numeric_price(self):
        m=[dict(id='1',direction='in',body='У меня проблема в Xbox'),dict(id='2',direction='out',body='Пришлите фото'),dict(id='3',direction='in',body='',media_reviewed=True)]
        personal_media.attach_observation(m[-1],self.observation(),source='offline_reviewed_image')
        k=dict(direction='kp',direction_source='context',city='Оренбург',partner='7',channel='avito',title='Настройка приставок',account_name='Иван КП')
        facts=contact_facts.collect(m,k);out=policy.assess(m,k,facts)
        self.assertEqual(out['next_question']['kind'],'error_context')
        self.assertEqual(qs.inspect(m)['problem']['status'],'answered')
        self.assertFalse(facts['phone_values'])
        self.assertTrue(any('80154058' in line for line in contact_facts.crm_comment_lines(facts)))

    def test_activity_already_stated_is_not_asked_again(self):
        m=[dict(id='1',direction='in',body='Ошибка при входе в Xbox Live'),dict(id='2',direction='in',body='',media_reviewed=True)]
        personal_media.attach_observation(m[-1],self.observation(),source='offline_reviewed_image')
        self.assertEqual(qs.inspect(m)['error_context']['status'],'answered')

    def test_activity_clarification_cannot_loop_after_two_attempts(self):
        m=[dict(id='1',direction='in',body='У меня проблема в Xbox'),dict(id='2',direction='in',body='',media_reviewed=True)]
        personal_media.attach_observation(m[-1],self.observation(),source='offline_reviewed_image')
        for direction,body in [('out','При каком действии появляется ошибка?'),('in','Не понял'),('out','При каком действии появляется ошибка?'),('in','Не знаю')]:
            m.append(dict(id=str(len(m)+1),direction=direction,body=body))
        k=dict(direction='kp',direction_source='context',city='Оренбург',partner='7',channel='avito',title='Настройка приставок',account_name='Иван КП')
        out=policy.assess(m,k,contact_facts.collect(m,k));self.assertEqual(out['action'],'handoff')

    def test_old_code_does_not_ask_error_context_for_an_explicit_new_request(self):
        m=[dict(id='1',direction='in',body='У меня проблема в Xbox'),dict(id='2',direction='in',body='',media_reviewed=True),dict(id='3',direction='in',body='Теперь нужно собрать шкаф')]
        personal_media.attach_observation(m[1],self.observation(),source='offline_reviewed_image')
        k=dict(direction='mnc',direction_source='context',city='Оренбург',partner='7',channel='avito',title='Сборка мебели',account_name='Иван МНЧ')
        out=policy.assess(m,k,contact_facts.collect(m,k));self.assertNotEqual(out.get('next_question',{}).get('kind'),'error_context')


if __name__=='__main__':unittest.main()
