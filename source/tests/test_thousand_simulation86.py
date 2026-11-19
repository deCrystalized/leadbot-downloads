"""Protect the historical replay's causal inputs and source boundaries."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from simulate_manual_thousand86 import context, legacy_input


class ThousandSimulation86Tests(unittest.TestCase):
    def row(self):
        return dict(number=1, source=dict(city='chita', account_title='Иван КП', partner='7',
            channel='avito', origin='В1', item_title='Ремонт компьютеров',
            crm_at='2026-10-01T09:30:00Z', crm_request_id='historical-order',
            current_crm_phone='NEVER_USE_CURRENT_CARD', account='account'), messages=[
                dict(id='c1', direction='in', sender_type='client', text='Компьютер не включается',
                     ts='2026-10-01T09:00:00Z'),
                dict(id='note', direction='note', sender_type='operator', text='служебный текст',
                     ts='2026-10-01T09:01:00Z'),
                dict(id='c2', direction='in', sender_type='client', text='ДАЛЬНЕЙШИЙ ОТВЕТ',
                     ts='2026-10-01T12:00:00+02:00')])

    def test_future_answer_and_current_card_do_not_enter_a_prefix(self):
        ctx = context(self.row(), 1)
        self.assertEqual([m['id'] for m in ctx['messages']], ['c1'])
        self.assertNotIn('ДАЛЬНЕЙШИЙ ОТВЕТ', str(ctx))
        self.assertNotIn('NEVER_USE_CURRENT_CARD', str(ctx))
        self.assertFalse(ctx['crmRequestId'])

    def test_existing_order_link_requires_a_known_causal_time(self):
        row = self.row()
        self.assertEqual(context(row, 3)['crmRequestId'], 'historical-order')
        row['source']['crm_at'] = None
        self.assertFalse(context(row, 3)['crmRequestId'])

    def test_timezones_are_compared_as_instants(self):
        row = self.row()
        row['source']['crm_at'] = '2026-10-01T10:30:00+02:00'
        self.assertEqual(context(row, 1)['crmRequestId'], 'historical-order')

    def test_early_export_media_is_not_silently_discarded(self):
        row = self.row()
        row['messages'][0]['attachment_types'] = ['image']
        self.assertEqual(context(row, 1)['messages'][0]['attachments'], [dict(kind='image')])

    def test_common_legacy_contract_does_not_forge_notes_as_sent_messages(self):
        row = self.row()
        self.assertEqual(len(context(row, 3)['messages']), 3)
        native = legacy_input(context(row, 3, common=True))
        self.assertEqual([m['id'] for m in native['dialog']], ['c1', 'c2'])
        self.assertNotIn('служебный текст', str(native))
