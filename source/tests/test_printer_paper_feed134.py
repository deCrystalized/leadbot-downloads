"""Paper-jam reports request physical repair, not invented host connection work."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_catalog as catalog
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant

KNOWN = dict(direction='kp', city='Саратов', channel='avito', partner='7',
             title='Ремонт принтеров', account_name='Учебный мастер')
JAM = 'Здравствуйте, нужна помощь. Принтер жуёт бумагу и скрипит...'


class PaperFeed134Tests(unittest.TestCase):
    def test_original_symptom_is_literal_with_exact_source_offsets(self):
        match = qs.printer_problem_match(JAM)
        self.assertIsNotNone(match)
        self.assertEqual(match.lastgroup, 'paper_feed')
        self.assertEqual(JAM[match.start():match.end()], 'жуёт бумагу')
        state = qs.inspect([dict(id='problem', direction='in', body=JAM)])['problem']
        self.assertEqual(state['value'], 'жуёт бумагу'); self.assertEqual(state['message_id'], 'problem')

    def test_ordinary_physical_repair_does_not_request_a_host(self):
        service = catalog.choose(JAM, KNOWN)
        self.assertEqual(service['status'], 'supported')
        self.assertEqual([item['id'] for item in service['items']], ['printer'])
        self.assertNotIn('printer_connection', service['items'][0]['questions'])

    def test_reported_paper_symptom_variants(self):
        for text in ['Принтер жует бумагу.', 'МФУ зажёвывает листы.',
                     'В принтере бумага застревает.', 'На принтере замятие бумаги.']:
            with self.subTest(text=text): self.assertEqual(qs.printer_problem_match(text).lastgroup, 'paper_feed')

    def test_negation_quote_hypothesis_third_party_and_past_are_not_new_faults(self):
        for text in ['Принтер не жуёт бумагу.', 'На принтере нет замятия бумаги.',
                     'Если принтер жуёт бумагу, что делать?',
                     'Мастер написал: «принтер жуёт бумагу».',
                     'Сосед говорит, его принтер жуёт бумагу.',
                     'Раньше на принтере было замятие бумаги. Сейчас всё нормально.']:
            with self.subTest(text=text): self.assertIsNone(qs.printer_problem_match(text))

    def test_independently_requested_setup_keeps_host_qualification(self):
        service = catalog.choose(JAM + ' Ещё нужно настроить подключение.', KNOWN)
        self.assertIn('printer_connection', service['items'][0]['questions'])

    def test_rejected_setup_is_not_independently_requested(self):
        service = catalog.choose(JAM + ' Подключать не надо, настройка не нужна.', KNOWN)
        self.assertNotIn('printer_connection', service['items'][0]['questions'])

    def test_explicit_special_printer_repair_still_requires_agreement(self):
        # Catalog marks special printers for qualification; the common policy
        # resolves the client's stated repair into an agreement handoff.
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner'):
            app = Assistant(Store(tmp + '/db'))
            out, code = app.handle(dict(owner='owner', action='preview', wording_mode='neural_review',
                ctx=dict(convId='synthetic-special-paper134', city='Саратов', dir='kp', channel='avito',
                    partner='7', accountTitle='Учебный мастер', itemTitle='Ремонт принтеров',
                    messages=[dict(id='problem', direction='in', body='3D принтер жуёт бумагу, требуется ремонт.')])) )
            self.assertEqual(code, 200); self.assertEqual(out['action'], 'handoff')
            self.assertIn('согласование', out['reason'])
            self.assertIn('DOC-L0184', out['rule_ids']); self.assertFalse(out.get('pending_model'))

    def test_native_after_known_model_does_not_invent_connection_or_cause(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner'):
            app = Assistant(Store(tmp + '/db'))
            data = [dict(id='problem', direction='in', body=JAM),
                    dict(id='question', direction='out', body='Марку и модель подскажите?'),
                    dict(id='model', direction='in', body='MG2540S canon pixma')]
            out, code = app.handle(dict(owner='owner', action='preview', wording_mode='neural_review',
                ctx=dict(convId='synthetic-paper134', city='Саратов', dir='kp', channel='avito',
                         partner='7', accountTitle='Учебный мастер', origin='С1', itemTitle='Ремонт принтеров', messages=data)))
            self.assertEqual(code, 200); self.assertTrue(out.get('pending_model'))
            task = json.loads(out['model_task']['task'])
            self.assertNotEqual(task['decision']['next_question']['kind'], 'printer_connection')
            self.assertNotRegex(task['proposed_reply'].lower(), 'подключ|ролик|головк|картридж')
            self.assertFalse(out['lead']['can_create_automatically']); self.assertFalse(out['auto_enabled'])
