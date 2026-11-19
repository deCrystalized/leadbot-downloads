"""Preserve explicit client quantity without treating quotations as work."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import qualification_state as state
from assistant_store import Store
from extension_assistant import Assistant


def client(text):
    return dict(id='one-client', direction='in', sender_type='client', body=text)


class ExplicitOne249Tests(unittest.TestCase):
    def test_one_mixer_is_known_work_scope(self):
        text='Нужно заменить один смеситель на кухне. Новый смеситель уже есть.'
        row=state.inspect([client(text)])['volume']
        self.assertEqual(row['status'],'answered')
        self.assertEqual(row['message_id'],'one-client')
        self.assertEqual(row['quote'],text)

    def test_other_explicit_single_items_keep_their_quantity(self):
        for item in ('выключатель','светильник','карниз','шкаф'):
            with self.subTest(item=item):
                row=state.inspect([client('Нужно установить один '+item+'.')])['volume']
                self.assertEqual(row['status'],'answered')

    def test_other_forms_and_numeric_counts_remain_known(self):
        for text in ('Нужно заменить одну розетку.','Нужно заменить 2 смесителя.'):
            with self.subTest(text=text):
                self.assertEqual(state.inspect([client(text)])['volume']['status'],'answered')

    def test_other_speaker_is_not_client_quantity(self):
        for role,direction in (('operator','out'),('system','system')):
            row=client('Нужно заменить один смеситель.');row.update(sender_type=role,direction=direction)
            self.assertEqual(state.inspect([row])['volume']['status'],'missing')

    def test_conditional_and_quoted_quantity_are_not_current_work(self):
        for text in ('Если понадобится заменить один смеситель, напишу.',
                     'Мастер сказал: «Нужно заменить один смеситель».'):
            with self.subTest(text=text):
                self.assertEqual(state.inspect([client(text)])['volume']['status'],'missing')

    def test_unknown_plural_still_requires_clarification(self):
        for text in ('Нужно заменить несколько смесителей.',
                     'Нужно заменить один смеситель или два.',
                     'Возможно, нужно заменить один смеситель.'):
            with self.subTest(text=text):
                self.assertEqual(state.inspect([client(text)])['volume']['status'],'missing')

    def test_past_self_work_or_negation_does_not_create_current_quantity(self):
        for text in ('Я сам решил заменить один смеситель.',
                     'Раньше нужно было заменить один смеситель.',
                     'Не нужно заменить один смеситель.'):
            with self.subTest(text=text):
                self.assertEqual(state.inspect([client(text)])['volume']['status'],'missing')

    def test_actual_price_preview_does_not_repeat_the_stated_quantity(self):
        text='Здравствуйте! Нужно заменить один смеситель на кухне. Новый смеситель уже есть. Сколько будет стоить?'
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            app=Assistant(Store(folder+'/db'))
            ctx=dict(convId='synthetic-one249',city='Чита',dir='mnc',channel='avito',partner='7',origin='С1',
                     accountTitle='Георгий МНЧ',itemTitle='Услуги сантехника',messages=[client(text)])
            value,code=app.handle(dict(owner='one249',action='preview',wording_mode='neural_review',ctx=ctx))
            self.assertEqual(code,200)
            self.assertTrue(value.get('pending_model'),value)
            task=json.loads(value['model_task']['task'])
            self.assertNotEqual((task['decision'].get('next_question') or {}).get('kind'),'volume')
            self.assertNotIn('Какой объём работ',task['proposed_reply'])
            self.assertFalse(value['auto_enabled'])

    def test_direct_price_question_retains_its_explicit_scope(self):
        for text in ('Сколько стоит заменить один смеситель на кухне?',
                     'Какая цена, чтобы установить один карниз?'):
            with self.subTest(text=text):
                row=state.inspect([client(text)])['volume']
                self.assertEqual(row['status'],'answered')
                self.assertEqual(row['message_id'],'one-client')

    def test_question_about_necessity_and_quoted_price_do_not_create_scope(self):
        for text in ('Нужно ли установить один смеситель?',
                     'Мастер сказал: «Сколько стоит заменить один смеситель?»',
                     'Сколько стоит заменить один смеситель или два?'):
            with self.subTest(text=text):
                self.assertEqual(state.inspect([client(text)])['volume']['status'],'missing')
