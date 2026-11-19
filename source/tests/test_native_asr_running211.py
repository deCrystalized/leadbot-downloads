"""Actual LeadChat ASR statuses, full Assistant path; no audio/API calls."""
import unittest

import test_research_media204 as fixture
from extension_assistant import _parse
from personal_media import awaiting_voice


class NativeVoiceTests(unittest.TestCase):
    voice_preview = fixture.MediaTests.voice_preview

    def test_native_running_waits_with_or_without_attachment(self):
        for attachments in ([], [dict(kind='voice')]):
            out = self.voice_preview(status='running', attachments=attachments)
            self.assertEqual(out['action'], 'wait')
            self.assertFalse(out['needs_operator'])
            self.assertEqual(out['reply'], '')
            self.assertNotIn('model_task', out)

    def test_native_partial_running_does_not_turn_into_complaint_or_contact(self):
        text = 'Мастер сломал шкаф, верните деньги. Телефон 79990000001.'
        out = self.voice_preview(status='running', transcript=text)
        self.assertEqual(out['action'], 'wait')
        self.assertFalse(out['needs_operator'])
        _, rows, _, _ = _parse(dict(convId='voice', messages=[dict(id='v', direction='in',
            sender_type='client', body=text, voice_transcript=text,
            voice_transcript_status='running', attachments=[dict(kind='voice')])]))
        self.assertEqual(rows[0]['body'], '')
        self.assertTrue(rows[0]['awaiting_voice_transcript'])

    def test_native_done_resumes_current_request(self):
        out = self.voice_preview(status='done')
        self.assertEqual(out['action'], 'question')
        self.assertIn('стен', out['reply'].lower())

    def test_native_empty_terminal_or_unknown_is_not_a_wait(self):
        for status in ('failed', 'too_long', '', 'future_status'):
            out = self.voice_preview(status=status, transcript='')
            self.assertEqual(out['action'], 'handoff')
            self.assertTrue(out['needs_operator'])

    def test_native_running_does_not_acknowledge_unread_photo(self):
        out = self.voice_preview(status='running', attachments=[
            dict(kind='voice'), dict(kind='image', id='photo')])
        self.assertEqual(out['action'], 'handoff')
        self.assertTrue(out['needs_operator'])

    def test_existing_order_has_priority_over_native_voice_wait(self):
        out = self.voice_preview(status='running', crmRequestId='1234567')
        self.assertEqual(out['lifecycle']['disposition'], 'operator_review')
        self.assertIsNone(out['lifecycle']['crm_preparation'])

    def test_completion_and_late_edit_with_same_native_id_change_revision(self):
        row = dict(id='v', direction='in', sender_type='client', body='',
            voice_transcript='Улица Первая.', voice_transcript_status='running',
            attachments=[dict(kind='voice')])
        ctx = dict(convId='voice', messages=[row])
        first = _parse(ctx)
        row['voice_transcript_status'] = 'done'
        second = _parse(ctx)
        self.assertNotEqual(first[3], second[3])
        self.assertTrue(first[1][0]['unread_media'])
        self.assertFalse(second[1][0]['unread_media'])
        row['voice_transcript'] = 'Улица Вторая.'
        self.assertNotEqual(second[3], _parse(ctx)[3])

    def test_native_pending_is_not_image_or_completed_audio_review(self):
        self.assertTrue(awaiting_voice(dict(voice_transcript_status='running')))
        for attachment in (dict(kind='image'), dict(kind='video'),
                           dict(kind='voice', type='image')):
            self.assertFalse(awaiting_voice(dict(voice_transcript_status='running',
                                                attachments=[attachment])))


if __name__ == '__main__':
    unittest.main()
