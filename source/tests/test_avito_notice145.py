"""An exported Avito envelope can be mislabeled as incoming client speech."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from extension_assistant import Assistant, _embedded_avito_notice, _parse
from assistant_store import Store

NOTICE = ('[Системное сообщение] 🪄 Ассистент Авито ответил:\n\n'
          '"Здравствуйте👋\nИсполнитель работает с гарантией и по договору. '
          'Опыт в сфере - 10 лет и больше.\nХотите записаться на консультацию?"\n\n'
          '💡 Ассистент помогает собирать контакты тех, кто действительно заинтересован в ваших услугах.')


def message(text, mid='notice', **extra):
    return dict(id=mid, body=text, direction='in', sender_type='client', **extra)


class ExportedAvitoNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'LEADBOT_PERSONAL_OWNER_ID': 'notice-test',
                                         'LEADBOT_PERSONAL_AUTO_AVAILABLE': '0'})
        self.env.start()
        self.app = Assistant(Store(str(Path(self.tmp.name) / 'store')))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def ctx(self, messages):
        return dict(convId='synthetic-exported-notice', city='Тюмень', dir='mnc', partner='7',
                    channel='avito', accountTitle='Тест МНЧ', itemTitle='Сборка и ремонт мебели',
                    messages=messages)

    def preview(self, ctx):
        result, status = self.app.handle(dict(owner='notice-test', action='preview',
                                              wording_mode='neural_review', ctx=ctx))
        self.assertEqual(status, 200)
        self.assertFalse(result['auto_enabled'])
        return result

    def test_mislabeled_notice_does_not_turn_assembly_into_warranty_claim(self):
        ctx = self.ctx([message('Нужно собрать кровать, инструкция есть.', 'client-1'), message(NOTICE)])
        original = copy.deepcopy(ctx)
        out = self.preview(ctx)
        self.assertNotEqual(out.get('action'), 'handoff')
        self.assertTrue(out.get('model_task'))
        task = json.loads(out['model_task']['task'])
        self.assertEqual(task['latest_client_message']['id'], 'client-1')
        self.assertEqual(task['conversation'][1]['speaker_role'], 'service')
        self.assertEqual(task['conversation'][1]['direction'], 'in')
        self.assertEqual(task['conversation'][1]['sender_type'], 'client')
        self.assertEqual(task['conversation'][1]['body'], NOTICE)
        self.assertEqual(task['history_coverage']['provided_messages'], 2)
        self.assertFalse(task['history_coverage']['prior_staff_speech_exists'])
        self.assertEqual(ctx, original)

    def test_service_only_update_reuses_same_pending_request_without_new_generation(self):
        ctx = self.ctx([message('Нужно собрать кровать, инструкция есть.', 'client-1')])
        first = self.preview(ctx)
        ctx['messages'].append(message(NOTICE))
        second = self.preview(ctx)
        self.assertEqual(second['revision'], first['revision'])
        self.assertEqual(second['request_id'], first['request_id'])
        self.assertEqual(second['code'], 'pending')
        self.assertNotIn('model_task', second)

    def test_real_client_question_after_notice_is_preserved(self):
        ctx = self.ctx([message(NOTICE + '\nНо у меня гарантийный ремонт, мастер уже приезжал.')])
        parsed = _parse(ctx)[1]
        self.assertEqual(len(parsed), 1)
        self.assertIn('мастер уже приезжал', parsed[0]['body'])

    def test_quoted_notice_with_client_intro_is_preserved(self):
        self.assertFalse(_embedded_avito_notice(message('Мне прислали такой ответ:\n' + NOTICE)))

    def test_incomplete_envelope_does_not_hide_client_speech(self):
        self.assertFalse(_embedded_avito_notice(message('[Системное сообщение] Ассистент Авито ответил: "гарантия?"')))

    def test_unrelated_system_label_is_not_a_service_notice(self):
        self.assertFalse(_embedded_avito_notice(message('[Системное сообщение] Я хочу ремонт по гарантии.')))

    def test_notice_with_original_media_keeps_unread_media_gate(self):
        self.assertFalse(_embedded_avito_notice(message(NOTICE, attachments=[{'type': 'image', 'url': '/photo.jpg'}])))

    def test_notice_with_separate_voice_answer_is_not_discarded(self):
        self.assertFalse(_embedded_avito_notice(message(NOTICE, voice_transcript='Нужен ремонт по гарантии')))

    def test_genuine_warranty_request_after_notice_remains_client_intent(self):
        ctx = self.ctx([message(NOTICE), message('Мастер уже приезжал, нужна гарантия.', 'client-2')])
        out = self.preview(ctx)
        self.assertEqual(out['action'], 'handoff')
        self.assertEqual([row['id'] for row in _parse(ctx)[1]], ['client-2'])

    def test_outgoing_operator_quoting_notice_remains_observed_staff_speech(self):
        row = dict(message(NOTICE), direction='out', sender_type='operator')
        self.assertEqual(len(_parse(self.ctx([row]))[1]), 1)


if __name__ == '__main__':
    unittest.main()
