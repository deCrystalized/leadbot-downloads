"""Native output must cite real evidence, not a visible row's ordinal number."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant


class EvidenceSchema133Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner')
        env.start(); self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))

    def prepare(self, system_rows=0, duplicate=False):
        messages = [dict(id='request', direction='in', body='Сколько стоит собрать шкаф?')]
        messages += [dict(id='service-' + str(i), direction='system', sender_type='system',
                          body='Служебная запись') for i in range(system_rows)]
        messages += [dict(id='quoted-price', direction='out', body='Сборка от 1500 рублей, точно после осмотра'),
                     dict(id='latest' if not duplicate else 'request', direction='in', body='А точнее можно?')]
        ctx = dict(convId='synthetic-evidence133', city='Уфа', dir='mnc', channel='avito',
                   partner='7', accountTitle='Учебный мастер МНЧ', origin='С1', itemTitle='Сборка мебели',
                   messages=messages)
        out, code = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review', ctx=ctx))
        self.assertEqual(code, 200); self.assertTrue(out.get('pending_model'), out.get('reason'))
        task = json.loads(out['model_task']['task'])
        items = out['model_task']['response_format']['schema']['properties']['context_review']['properties']['evidence_ids']['items']
        return out, task, items

    def test_wire_restricts_the_original_invented_ordinal(self):
        _, task, items = self.prepare()
        self.assertNotIn('10', items['enum'])
        self.assertIn('quoted-price', items['enum'])
        self.assertIn('latest', items['enum'])
        self.assertEqual(items['enum'], task['output_contract']['allowed_evidence_ids'])

    def test_full_history_remains_while_wire_enum_is_bounded(self):
        out, task, items = self.prepare(system_rows=100)
        self.assertEqual(len(task['conversation']), 103)
        self.assertFalse(task['history_coverage']['truncated'])
        self.assertLessEqual(len(items['enum']), 8)
        self.assertIn('latest', items['enum'])
        self.assertLess(len(json.dumps(out['model_task']['response_format'], ensure_ascii=False)), 24000)

    def test_duplicate_ids_use_unambiguous_position_references(self):
        _, task, items = self.prepare(duplicate=True)
        self.assertNotIn('request', items['enum'])
        self.assertIn(task['latest_client_message']['evidence_id'], items['enum'])
        self.assertIn('context-position:2', items['enum'])

    def test_local_guard_still_rejects_invalid_reference_before_reply(self):
        out, task, _ = self.prepare()
        candidate = dict(reply=task['fixed_reply'], needs_operator=False, context_review=dict(
            last_intent='Узнать цену сборки шкафа', latest_client_meaning='Клиент просит точную цену',
            selected_step_fits=True, evidence_ids=['latest', '10'], note='Уточняется минимум стоимости.'))
        result, code = self.app.handle(dict(owner='owner', action='finalize',
            request_id=out['request_id'], revision=out['revision'], candidate=candidate))
        self.assertEqual(code, 200); self.assertFalse(result['auto_enabled'])
        self.assertFalse(result['reply']); self.assertIn('invalid_context_review', result['validation'])
