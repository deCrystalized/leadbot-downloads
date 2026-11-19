"""A delivered natural follow-up starts the second KP silence timer."""
from datetime import datetime, timedelta, timezone
import unittest

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import dialogue_lifecycle as lifecycle


class NaturalFollowup121Tests(unittest.TestCase):
    def setUp(self):
        self.zero=datetime(2026,10,20,12,0,tzinfo=timezone.utc)

    def message(self,mid,direction,body,seconds=0,**extra):
        return dict(id=mid,direction=direction,body=body,
                    sender_type='client' if direction=='in' else 'operator',
                    delivery_status='delivered',created_at=(self.zero+timedelta(seconds=seconds)).isoformat(),**extra)

    def history(self,followup='Помощь по вашему запросу ещё актуальна?'):
        return [self.message('client','in','Нужна помощь с ноутбуком'),
                self.message('first','out','Что у вас случилось?'),
                self.message('followup','out',followup,300)]

    def timer(self,ms,seconds):
        return lifecycle.silence_timer(ms,{'direction':'kp'},now=self.zero+timedelta(seconds=seconds))

    def test_natural_and_observed_historical_short_followup_wait_then_close(self):
        for text in ['Помощь по вашему запросу ещё актуальна?','Вам ещё нужна помощь?',
                     'Подскажите, пожалуйста, вопрос ещё актуален?','Актуально?','Ещё актуально?']:
            with self.subTest(text=text):
                self.assertEqual(self.timer(self.history(text),899)['status'],'waiting')
                t=self.timer(self.history(text),900)
                self.assertEqual(t['status'],'elapsed')
                self.assertEqual(t['followup_message_id'],'followup')

    def test_real_delivery_not_queue_time_starts_the_ten_minutes(self):
        ms=self.history();ms[-1].update(delivery_clock_unverified=True,
            delivery_confirmed_at=(self.zero+timedelta(seconds=720)).isoformat(),
            delivery_clock_source='server_first_confirmed_observation')
        self.assertEqual(self.timer(ms,1319)['status'],'waiting')
        self.assertEqual(self.timer(ms,1320)['status'],'elapsed')

    def test_no_new_followup_delivery_no_close_deadline(self):
        for status in ['pending','failed']:
            ms=self.history();ms[-1]['delivery_status']=status
            self.assertNotEqual(self.timer(ms,2000)['status'],'elapsed')
        for actor in ['system','bot']:
            ms=self.history();ms[-1]['sender_type']=actor
            self.assertNotEqual(self.timer(ms,2000)['status'],'elapsed')

    def test_price_repair_quotation_and_extra_claim_are_not_followup(self):
        for text in ['Цена ещё актуальна?','Унитаз обычный или инсталляция?',
                     '«Помощь ещё актуальна?»','Актуально? Я уже выехал.']:
            self.assertNotEqual(self.timer(self.history(text),2000)['status'],'elapsed',text)

    def test_client_response_cancels_the_second_phase(self):
        ms=self.history()+[self.message('reply','in','Да, помощь нужна',600)]
        self.assertEqual(self.timer(ms,1000)['status'],'cancelled_by_incoming')


if __name__=='__main__':unittest.main()
