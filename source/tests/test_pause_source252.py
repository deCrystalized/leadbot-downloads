"""A future-contact phrase needs the client's positive, unquoted assertion."""
import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from assistant_policy import _client_deferred
from assistant_store import Store
from extension_assistant import Assistant
from test_assistant import context


class PauseSource252Tests(unittest.TestCase):
    def test_full_assistant_continues_the_clients_job_despite_quote_or_negation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                LEADBOT_PERSONAL_OWNER_ID='pause-source252',LEADBOT_ASSISTANT_WORDING='reviewed'):
            app=Assistant(Store(Path(directory)/'assistant.sqlite3'))
            for index,body in enumerate((
                    'Сосед написал: «Я позвоню завтра». Полку повесить нужно мне.',
                    'Я не позвоню завтра, помощь нужна сейчас.')):
                ctx=context([dict(id='first',direction='in',sender_type='client',body='Нужно повесить полку.'),
                             dict(id='latest',direction='in',sender_type='client',body=body)],
                            dir='mnc',convId='synthetic-pause-source-'+str(index),
                            accountTitle='Мастер на час',itemTitle='Мастер на час')
                out,status=app.handle(dict(owner='pause-source252',action='preview',ctx=ctx,wording_mode='reviewed'))
                self.assertEqual(status,200)
                self.assertEqual(out['action'],'question',out.get('reason'))
                self.assertFalse(out['needs_operator'])

    def test_quote_or_negated_contact_cannot_establish_a_pause(self):
        for body in (
            'Сосед написал: «Я позвоню завтра». Полку повесить нужно мне.',
            'Мне прислали "Я напишу завтра". Сейчас хочу обсудить сборку.',
            'Я не напишу завтра. Сейчас обсудим сборку.',
            'Я не позвоню завтра, помощь нужна сейчас.',
            'Мы не спишемся.',
        ):
            with self.subTest(body=body):
                self.assertFalse(_client_deferred(['Нужно повесить полку.',body]))

    def test_real_pause_survives_quote_and_negated_alternative(self):
        for body in (
            'Я напишу завтра.',
            'Сосед написал: «Я позвоню завтра». Я напишу вечером.',
            'Я не позвоню завтра, напишу вечером.',
            'Спишемся.',
        ):
            with self.subTest(body=body):
                self.assertTrue(_client_deferred(['Нужно повесить полку.',body]))
        self.assertFalse(_client_deferred(['Я напишу завтра, а сколько стоит сборка?']))
