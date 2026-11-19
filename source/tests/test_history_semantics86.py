"""Answer the client's question without inheriting a third-party diagnosis."""
import os
import tempfile
import unittest
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant


class DiagnosisQuestion86Tests(unittest.TestCase):
    def preview(self, text):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,
                LEADBOT_ASSISTANT_WORDING='reviewed', LEADBOT_PERSONAL_OWNER_ID='offline-86'):
            ctx = dict(convId='synthetic-diagnosis86', city='Великий Новгород', dir='bt', partner='748',
                accountTitle='Андрей БТ', itemTitle='Ремонт холодильников', channel='avito',
                messages=[dict(id='c1', direction='in', body=text)])
            out, status = Assistant(Store(temp+'/db')).handle(dict(owner='offline-86', action='preview', ctx=ctx))
            self.assertEqual(status, 200)
            return out

    def test_other_technicians_conclusion_is_not_confirmed_or_ignored(self):
        out = self.preview('Здравствуйте! Другой мастер сказал, что холодильник неремонтопригоден. Это так?')
        self.assertEqual(out['action'], 'question')
        self.assertIn('Без осмотра подтвердить', out['reply'])
        self.assertIn('нельзя', out['reply'])
        self.assertIn('модель', out['reply'])
        self.assertEqual(out['validation'], [])
        self.assertLessEqual(len(out['reply']), 280)

    def test_ordinary_fridge_symptom_does_not_get_an_unasked_diagnosis_faq(self):
        out = self.preview('Холодильник не морозит, можете помочь?')
        self.assertNotIn('не подлежит ремонту', out['reply'])

    def test_complaint_about_our_visit_still_goes_to_operator(self):
        out = self.preview('Ваш мастер приезжал и сказал, что холодильник неремонтопригоден. Это так? Хочу оформить претензию.')
        self.assertEqual(out['action'], 'handoff')
        self.assertEqual(out['reply'], '')

    def test_explicit_refusal_is_not_reopened_by_a_diagnostic_question(self):
        out = self.preview('Другой мастер сказал, что холодильник неремонтопригоден. Это так? Но помощь уже не нужна, отказываюсь.')
        self.assertIn(out['action'], ('wait', 'handoff'))
        self.assertEqual(out['reply'], '')
