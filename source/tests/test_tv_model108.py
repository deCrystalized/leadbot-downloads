"""Source962 and controls for manufacturer-code type inference, not a diagnosis."""
import unittest
import json
import os
import tempfile
from unittest.mock import patch

import qualification_state as qs
from test_history_intake106 import rows, known, assess
from assistant_store import Store
from extension_assistant import Assistant
from test_assistant import context, message


class TvModel108Tests(unittest.TestCase):
    def test_supplied_full_samsung_code_establishes_led_with_primary_provenance(self):
        state = qs.inspect(rows(('in', 'На Samsung UE48H5270 заменить подсветку сколько будет?')))['tv_type']
        self.assertEqual(state['value'], 'LED')
        self.assertEqual(state['model'], 'UE48H5270')
        self.assertEqual(state['message_id'], 'm1')
        self.assertEqual(state['evidence_source'], 'manufacturer_model_code')
        self.assertIn('samsung.com/', state['manufacturer_source_url'])
        self.assertNotIn('LED', state['quote'])

    def test_official_legacy_example_is_also_led(self):
        state = qs.inspect(rows(('in', 'Samsung UE55F8000AFXZ')))['tv_type']
        self.assertEqual(state['value'], 'LED')

    def test_known_model_does_not_ask_tv_type_again(self):
        out = assess(rows(('in', 'На Samsung UE48H5270 заменить подсветку сколько будет?')),
                     known('kp', 'Ремонт телевизоров с выездом'))
        self.assertNotEqual(out.get('next_question', {}).get('kind'), 'tv_type')
        self.assertNotEqual(out['action'], 'handoff')

    def test_partial_code_does_not_establish_type(self):
        for text in ('Samsung UE', 'Samsung UE48', 'Samsung UE48H', 'Samsung 5270'):
            with self.subTest(text=text):
                self.assertNotEqual(qs.inspect(rows(('in', text)))['tv_type']['status'], 'answered')

    def test_unknown_brand_does_not_borrow_samsung_code_legend(self):
        self.assertNotEqual(qs.inspect(rows(('in', 'UE48H5270')))['tv_type']['status'], 'answered')

    def test_staff_suggestion_and_system_note_do_not_establish_client_device(self):
        for row in (dict(id='staff', direction='out', body='Samsung UE48H5270'),
                    dict(id='system', direction='in', sender_type='system', body='Samsung UE48H5270')):
            self.assertNotEqual(qs.inspect([row])['tv_type']['status'], 'answered')

    def test_explicit_other_device_is_not_tv(self):
        self.assertIsNone(qs.manufacturer_tv_type(rows(('in', 'Монитор Samsung UE48H5270'))))

    def test_negated_brand_and_later_brand_correction_do_not_keep_old_inference(self):
        self.assertIsNone(qs.manufacturer_tv_type(rows(('in', 'Не Samsung UE48H5270'))))
        self.assertIsNone(qs.manufacturer_tv_type(rows(('in', 'Samsung UE48H5270'), ('in', 'Ошибся, это LG'))))

    def test_explicit_client_type_is_not_silently_overwritten(self):
        row = qs.inspect(rows(('in', 'Плазменный Samsung UE48H5270')))['tv_type']
        self.assertIn('Плазмен', row['value'])
        self.assertNotEqual(row.get('evidence_source'), 'manufacturer_model_code')

    def test_two_distinct_model_codes_remain_unresolved(self):
        self.assertIsNone(qs.manufacturer_tv_type(rows(('in', 'Samsung UE48H5270'), ('in', 'Samsung UE55F8000AFXZ'))))

    def test_bands_still_follow_owner_refusal(self):
        out = assess(rows(('in', 'Samsung UE48H5270, на экране полосы')),
                     known('kp', 'Ремонт телевизоров'))
        self.assertEqual(out['action'], 'refuse')

    def test_manufacturer_provenance_survives_common_brain_model_task(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner'):
            app = Assistant(Store(tmp + '/db'))
            ctx = context([message('На Samsung UE48H5270 заменить подсветку сколько будет?')],
                          dir='kp', city='Самара', partner='723', itemTitle='Ремонт телевизоров с выездом')
            out, status = app.handle(dict(owner='owner', action='preview', ctx=ctx, wording_mode='neural_review'))
        self.assertEqual(status, 200)
        task = json.loads(out['model_task']['task'])
        fact = task['verified_device_facts'][0]
        self.assertEqual(fact['value'], 'LED')
        self.assertTrue(fact['not_client_literal_statement'])
        self.assertTrue(fact['not_diagnosis'])
        self.assertTrue(fact['not_exact_product_verification'])


if __name__ == '__main__':
    unittest.main()
