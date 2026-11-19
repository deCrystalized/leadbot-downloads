"""Keep written repair details when the client narrows a mixed furniture job."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from assistant_store import Store
from contact_facts import collect
from extension_assistant import Assistant


def msg(body, mid='client', direction='in', **extra):
    return dict(id=mid, body=body, direction=direction, **extra)


DETAIL = 'Добрый день у меня сломалась боковая доска кровати ножка. Хотела бы восстановить если сможете помочь.'


class WrittenBedTaskTests(unittest.TestCase):
    def test_written_sideboard_and_leg_remain_an_exact_client_quote(self):
        f = collect([msg(DETAIL)])
        note = next(n for n in f['task_notes'] if n.get('kind') == 'bed_part_damage')
        self.assertEqual(note['message_id'], 'client')
        self.assertEqual(note['quote'], DETAIL)
        self.assertTrue(note['written'])
        self.assertTrue(any(DETAIL in line for line in f['comment_lines']))

    def test_narrowing_to_repair_does_not_erase_prior_repair_details(self):
        f = collect([msg(DETAIL), msg('Нужно ещё разобрать мебель и перенести в новый дом', 'moving'),
                     msg('Хорошо хотя бы с ремонтом кровати помогите пожалуйста', 'scope')])
        self.assertEqual(f['active_service_scope']['message_id'], 'scope')
        self.assertTrue(any(DETAIL in line for line in f['comment_lines']))
        self.assertFalse(any('перенести' in n['quote'] for n in f['task_notes']))

    def test_staff_bot_and_system_cannot_supply_written_client_damage(self):
        for direction, sender in [('out', 'operator'), ('note', 'operator'), ('in', 'bot'),
                                  ('in', 'system'), ('in', 'operator'), ('in', 'assistant')]:
            with self.subTest(direction=direction, sender=sender):
                f = collect([msg(DETAIL, direction=direction, sender_type=sender)])
                self.assertFalse(any(n.get('kind') == 'bed_part_damage' for n in f['task_notes']))

    def test_plain_assembly_and_other_objects_do_not_invent_damage(self):
        for body in ['Собрать кровать, ножки в комплекте', 'Сломалась ножка у стола',
                     'Нужно поставить боковую доску кровати', 'Ленина 5, частный дом']:
            with self.subTest(body=body):
                self.assertFalse(any(n.get('kind') == 'bed_part_damage' for n in collect([msg(body)])['task_notes']))

    def test_transcript_is_not_relabelled_as_a_written_client_message(self):
        rows = [dict(id='voice', direction='in', voice_transcript=DETAIL,
                     attachments=[dict(kind='voice')])]
        out = self.form(rows)
        self.assertFalse(any(n.get('kind') == 'bed_part_damage' for n in out['facts']['task_notes']))

    def test_transcript_copied_into_body_is_still_not_written_evidence(self):
        out = self.form([dict(id='voice-copy', direction='in', body=DETAIL,
                              voice_transcript=DETAIL, attachments=[dict(kind='voice')])])
        self.assertFalse(any(n.get('kind') == 'bed_part_damage' for n in out['facts']['task_notes']))

    def test_normal_form_retains_written_evidence_alongside_later_transcript(self):
        rows = [msg(DETAIL, 'written'), dict(id='voice', direction='in', voice_transcript=DETAIL + ' Спинка.',
                                           attachments=[dict(kind='voice')]),
                msg('Хорошо хотя бы с ремонтом кровати помогите пожалуйста', 'scope')]
        out = self.form(rows)
        notes = [n for n in out['facts']['task_notes'] if n.get('kind') == 'bed_part_damage']
        self.assertEqual([n['message_id'] for n in notes], ['written'])
        self.assertEqual(notes[0]['quote'], DETAIL)
        self.assertNotIn('Спинка', notes[0]['quote'])

    def form(self, rows):
        ctx = dict(convId='synthetic-written-bed', city='Ярославль', dir='mnc', partner='7',
                   channel='avito', accountTitle='Анатолий МНЧ', itemTitle='Ремонт мебели',
                   origin='В80', messages=rows)
        with tempfile.TemporaryDirectory() as d:
            out, code = Assistant(Store(d + '/db')).handle(dict(owner='offline-written-bed', action='checklist', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(out['auto_enabled'])
        return out


if __name__ == '__main__':
    unittest.main()
