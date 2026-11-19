"""Presence volunteered after a data-safety answer that deferred qualification."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))

from assistant_store import Store, digest
from extension_assistant import Assistant
import qualification_state as qualifications


ASR = ('Уточнил: Word и Excel открываются, ошибка появляется, когда сохраняем документ. '
       'Это домашний ноутбук в Чите, Windows 11. Я сам решаю, оплачиваю обычным переводом '
       'и буду дома. Резервной копии нет, файлы удалять нельзя.')


class HomePresenceTests(unittest.TestCase):
    def test_ready_asr_after_answer_only_asks_the_next_unknown(self):
        messages = [
            dict(id='c1', direction='in', sender_type='client', body=(
                'Здравствуйте. На ноутбуке с Windows 11 перестали открываться Word и Excel: '
                'пишут, что не удалось запустить приложение. Документы важные, удалять их нельзя. '
                'Это можно исправить без потери файлов?')),
            dict(id='out-0', direction='out', sender_type='operator', delivery_status='delivered', body=(
                'Здравствуйте! Сохранность файлов заранее гарантировать не могу. '
                'Перед работой нужно проверить причину сбоя и согласовать действия с данными.')),
            dict(id='c2', direction='in', sender_type='client', body='Секунду, уточню у жены, что именно происходит.'),
            dict(id='s1', direction='system', sender_type='system', body='Статус диалога обновлён.'),
            dict(id='c3', direction='in', sender_type='client', delivery_status='delivered',
                 body='', voice_transcript=ASR, voice_transcript_status='done'),
        ]
        context = dict(convId='synthetic-home-presence268', messages=messages,
                       dir='kp', partner='7', city='Чита', channel='avito',
                       accountTitle='Георгий КП', itemTitle='Компьютерная помощь', origin='С1')
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            app = Assistant(Store(Path(tmp) / 'assistant.sqlite3'))
            out, status = app.handle(dict(owner='home-presence268', action='preview',
                                          ctx=context, wording_mode='neural_review'))
            self.assertEqual(status, 200)
            self.assertTrue(out['pending_model'])
            _, payload = app.store.request('assistant:' + digest('home-presence268'), out['request_id'])
            question = payload['decision_internal']['next_question']
            self.assertEqual(question['kind'], 'client_name')
            task = json.loads(payload['model_task']['task'])
            self.assertNotIn('Вы будете на месте', task['proposed_reply'])
            presence = payload['qualification']['decision_maker']['components']['presence']
            self.assertEqual(presence['message_id'], 'c3')
            self.assertEqual(presence['source'], 'client_literal_component')

    def test_home_mention_cannot_supply_unrelated_or_tentative_presence(self):
        for text in (
            'Это домашний ноутбук. Я сам решаю и оплачиваю. Завтра буду дома.',
            'Это домашний ноутбук, но настройка в офисе. Я сам решаю, оплачиваю и буду дома.',
            'Это домашний ноутбук, ремонт в сервисном центре. Я сам решаю, оплачиваю и буду дома.',
            'Это домашний ноутбук. Я сам решаю, оплачиваю и буду дома после визита.',
            'Это домашний ноутбук. Я сам решаю, оплачиваю и, возможно, буду дома.',
            'Это домашний ноутбук. Я сам решаю, оплачиваю, а жена будет дома.',
            'Это домашний ноутбук. Я решаю, какой принтер купить, оплачиваю покупку и буду дома.',
        ):
            with self.subTest(text=text):
                state = qualifications.inspect([dict(id='c3', direction='in', sender_type='client', body=text)])
                self.assertIn('presence', state['decision_maker']['missing_components'])
