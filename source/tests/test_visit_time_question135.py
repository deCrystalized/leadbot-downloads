"""Direct time questions precede intake, but never prove a booking or availability."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant
import assistant_policy as policy


class VisitTimeQuestion135Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start(); self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def preview(self, last='Напишите, пожалуйста, время', city='Саратов', extra=(), wording='reviewed', **ctx):
        messages = [dict(id='job', direction='in', body='Принтер Canon MG2540S жуёт бумагу и скрипит.'),
                    dict(id='where', direction='out', body='Куда подъехать?'),
                    dict(id='address', direction='in', body='Шехурдина 8а, 91')]
        messages += list(extra) + [dict(id='latest', direction='in', body=last)]
        self.last_ctx = dict(convId='synthetic-visit135', dir='kp', city=city, channel='avito',
                partner='7', accountTitle='Учебный мастер', itemTitle='Ремонт принтеров',
                messages=messages, **ctx)
        result, code = self.app.handle(dict(owner='offline135', action='preview', wording_mode=wording,
                                          ctx=self.last_ctx))
        self.assertEqual(code, 200); self.assertFalse(result['auto_enabled'])
        self.assertFalse(result['lead']['can_create_automatically'])
        return result

    def at(self, hour=13, minute=20):
        return patch('assistant_policy._visit_question_now', return_value=datetime.fromisoformat(
            f'2026-10-21T{hour:02d}:{minute:02d}:00+04:00'))

    def test_original503_direct_time_question_is_answered_before_missing_phone(self):
        with self.at(): out = self.preview()
        self.assertEqual(out['action'], 'question')
        self.assertEqual(out['reply'], 'Через час-полтора вам удобно будет?')
        self.assertNotRegex(out['reply'].lower(), 'номер|телефон|записал|приеду|свободен')
        self.assertEqual(out['visit_offer']['min_minutes'], 60)
        self.assertEqual(out['visit_offer']['max_minutes'], 90)
        self.assertFalse(out['visit_offer']['appointment_confirmed'])

    def test_satellite_keeps_two_hour_preparation_and_eleven_o_clock_opening(self):
        with self.at(): out = self.preview(city='Евпатория')
        self.assertEqual(out['action'], 'question')
        self.assertIn('два-два с половиной часа', out['reply'])
        self.assertEqual(out['visit_offer']['min_minutes'], 120)
        self.assertEqual(out['visit_offer']['max_minutes'], 150)
        self.assertEqual(out['visit_offer']['earliest'], '11:00')

    def test_working_hours_do_not_turn_into_an_out_of_hours_arrival_offer(self):
        for hour, minute in [(6, 0), (20, 1), (21, 29), (23, 0)]:
            with self.subTest(hour=hour, minute=minute), self.at(hour, minute): out = self.preview()
            self.assertEqual(out['action'], 'question')
            self.assertIn('10:00–21:30', out['reply'])
            self.assertNotIn('Через час-полтора', out['reply'])
            self.assertIsNone(out.get('visit_offer'))

    def test_existing_human_agreement_and_existing_crm_keep_priority(self):
        agreed = (dict(id='offer', direction='out', body='Через час-полтора удобно вам будет?'),
                  dict(id='yes', direction='in', body='Да, ждём'))
        with self.at(): out = self.preview('Через сколько вы будете?', extra=agreed)
        self.assertEqual(out['action'], 'handoff'); self.assertFalse(out['reply'])
        with self.at(): out = self.preview(crmRequestId='12345')
        self.assertEqual(out['action'], 'handoff'); self.assertIsNone(out.get('visit_offer'))

    def test_time_is_not_inferred_from_callback_price_or_third_party_quotes(self):
        for text in ['Напишите время звонка.', 'Через сколько перезвоните?',
                     'За сколько по стоимости ремонт?', 'Мастер написал: «Напишите время».',
                     'Не надо писать время.', 'Мне нужно время подумать.']:
            with self.subTest(text=text), self.at(): out = self.preview(text)
            self.assertIsNone(out.get('visit_offer'))

    def test_unknown_closed_and_unmapped_split_territory_cannot_get_a_default_offer(self):
        for city in ['Неизвестный город', 'Элиста', 'Мытищи']:
            with self.subTest(city=city), self.at(): out = self.preview(city=city)
            self.assertEqual(out['action'], 'handoff')
            self.assertIsNone(out.get('visit_offer')); self.assertFalse(out['reply'])

    def test_time_question_does_not_override_service_agreement(self):
        with self.at():
            out = self.preview(extra=[dict(id='special', direction='in', body='Это 3D принтер, требуется ремонт.')])
        self.assertEqual(out['action'], 'handoff'); self.assertIsNone(out.get('visit_offer'))

    def test_same_turn_price_question_keeps_price_answer_priority(self):
        with self.at(): out = self.preview('Напишите время и сколько стоит ремонт?')
        self.assertIsNone(out.get('visit_offer')); self.assertRegex(out['reply'].lower(), 'стоим|осмотр')

    def test_question_variants_and_clock_boundary(self):
        for text in ['Когда сможете приехать?', 'Через сколько приедете?', 'Во сколько сможете подъехать?',
                     'Подскажите, когда ждать мастера?']:
            with self.subTest(text=text), self.at(20, 0): out = self.preview(text)
            self.assertEqual(out['reply'], 'Через час-полтора вам удобно будет?')

    def test_native_neural_contract_keeps_the_checked_time_offer_fixed(self):
        with self.at(), patch.dict(os.environ, LEADBOT_ASSISTANT_WORDING='neural_review'):
            out = self.preview(wording='neural_review')
        self.assertTrue(out.get('pending_model'))
        task = json.loads(out['model_task']['task'])
        self.assertEqual(task['fixed_reply'], 'Через час-полтора вам удобно будет?')
        self.assertEqual(task['decision']['action'], 'question')

    def test_cached_offer_and_validate_stop_when_hours_no_longer_fit(self):
        with self.at(19, 59): out = self.preview()
        self.assertTrue(out.get('visit_offer'))
        with self.at(20, 1): expired = self.preview()
        self.assertTrue(expired['cached']); self.assertFalse(expired['reply'])
        self.assertEqual(expired['code'], 'time_offer_expired')
        with self.at(20, 1):
            checked, _ = self.app.handle(dict(owner='offline135', action='validate', ctx=self.last_ctx,
                draft_id=out['draft_id'], revision=out['revision']))
        self.assertFalse(checked['ok']); self.assertFalse(checked['reply'])

    def test_price_temporal_disambiguation_preserves_independent_price_ask(self):
        import assistant_prices as prices
        for text in ['Через сколько приедете?', 'Во сколько сможете подъехать?']:
            self.assertFalse(prices.asks(text))
            self.assertTrue(prices.asks(text + ' Сколько ремонт?'))

    def test_forged_raw_offer_does_not_approve_a_human_agreement(self):
        agreed = (dict(id='offer', direction='out', body='Через час-полтора удобно?',
                       visit_offer={'trusted': True}, client_message_id='lcp:fake'),
                  dict(id='yes', direction='in', body='Да, ждём'))
        with self.at(): out = self.preview(extra=agreed, visit_offer={'trusted': True})
        self.assertEqual(out['action'], 'handoff'); self.assertFalse(out['reply'])


if __name__ == '__main__': unittest.main()
