"""Refusal needs actual client speech, not its quotation or negation."""
import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from assistant_policy import _client_declined
from assistant_store import Store
from extension_assistant import Assistant
from test_assistant import context


class WithdrawalSource252Tests(unittest.TestCase):
    def test_quote_and_negated_choice_are_not_customer_decline(self):
        for text in ('Я не передумал, помощь нужна.',
                     'Я пока не нашла мастера. Нужно повесить полку.',
                     'Сосед написал: «Я передумал». Полку повесить нужно мне.'):
            with self.subTest(text=text):
                self.assertFalse(_client_declined(text,'Из какого материала стены?'))

    def test_genuine_current_withdrawal_remains_a_stop(self):
        for text in ('Передумал.', 'Уже нашла мастера.', 'Помощь больше не нужна.'):
            self.assertTrue(_client_declined(text,'Из какого материала стены?'))

    def test_full_assistant_does_not_abandon_a_negated_change_of_mind(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                LEADBOT_PERSONAL_OWNER_ID='withdrawal252',LEADBOT_ASSISTANT_WORDING='reviewed'):
            app=Assistant(Store(Path(directory)/'assistant.sqlite3'))
            ctx=context([dict(id='first',direction='in',sender_type='client',body='Нужно повесить полку.'),
                         dict(id='latest',direction='in',sender_type='client',body='Я не передумал, помощь нужна.')],
                        dir='mnc',convId='synthetic-withdrawal252',accountTitle='Мастер на час',itemTitle='Мастер на час')
            out,status=app.handle(dict(owner='withdrawal252',action='preview',ctx=ctx,wording_mode='reviewed'))
            self.assertEqual(status,200)
            self.assertEqual(out['action'],'question',out.get('reason'))
            self.assertFalse(out['needs_operator'])
