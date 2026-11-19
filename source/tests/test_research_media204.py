import copy
import hashlib
import json
import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from api_costs import UsageLedger
from extension_assistant import Assistant, _parse, _unread_media
from assistant_store import Store
from test_assistant import context as assistant_context
from research_media import prepare, image_inputs, MediaError, MAX_IMAGE_BYTES
from research_openai import ResponsesTransport
from research_pipeline import pack_context
from test_research_pipeline218 import context


# A fixed synthetic 1px PNG tests transport/provenance, never vision quality.
import base64
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1cAAAAASUVORK5CYII=')


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.raw = PNG
        self.current = context()
        self.current.update(facts=[], open_questions=[])
        row = dict(id='m1', source_message_id='m1', position=0, direction='in', sender_type='client',
                   speaker_role='client', body='Вот фото.', voice_transcript='', attachment_count=1)
        self.current['messages'] = [row]
        self.ctx = dict(messages=[dict(id='m1', attachments=[dict(id='photo', type='image', url='https://untrusted.invalid/private')])])
        self.calls = []

    def resolver(self, scope, descriptor):
        self.calls.append((scope, descriptor))
        return dict(scope, message_id=descriptor['message_id'], media_id=descriptor['media_id'],
                    attachment_hash=descriptor['attachment_hash'], data=self.raw,
                    mime='image/png', sha256=hashlib.sha256(self.raw).hexdigest())

    def prepared(self, resolver=None):
        return prepare(self.ctx, self.current['messages'], owner=self.current['owner_id'],
                       chat=self.current['dialogue_id'], revision=self.current['revision'],
                       resolver=resolver or self.resolver)

    def test_no_original_resolver_stops_instead_of_caption_or_arbitrary_url_fetch(self):
        with self.assertRaises(MediaError):
            prepare(self.ctx, self.current['messages'], owner='o', chat='c', revision='r')
        self.assertEqual(self.calls, [])

    def test_original_is_pixel_block_with_current_message_role_and_digest(self):
        self.current['media'] = self.prepared()
        blocks = image_inputs(self.current, self.resolver)
        self.assertEqual([b['type'] for b in blocks], ['input_text', 'input_image'])
        self.assertIn('message_id=m1', blocks[0]['text'])
        self.assertIn('speaker_role=client', blocks[0]['text'])
        self.assertEqual(base64.b64decode(blocks[1]['image_url'].split(',')[1]), PNG)
        self.assertNotIn('untrusted.invalid', json.dumps(self.current['media']))
        self.assertFalse(self.current['media']['human_media_review'])
        self.assertFalse(self.current['media']['native_vision_verified'])

    def test_resolver_wrong_owner_conversation_revision_message_attachment_digest_mime_rejected(self):
        for field in ('owner_id', 'dialogue_id', 'revision', 'message_id', 'media_id', 'attachment_hash', 'sha256', 'mime'):
            def bad(scope, item):
                value = self.resolver(scope, item);value[field] = 'different';return value
            with self.subTest(field=field), self.assertRaises(MediaError):
                self.prepared(bad)

    def test_changed_pixels_after_admission_and_duplicate_image_not_reused(self):
        self.current['media'] = self.prepared()
        self.raw = PNG + b'changed'
        with self.assertRaises(MediaError):image_inputs(self.current, self.resolver)
        self.raw = PNG
        self.current['media']['images'] *= 2
        with self.assertRaises(MediaError):image_inputs(self.current, self.resolver)

    def test_unknown_svg_raw_audio_and_missing_or_oversized_media_do_not_silently_drop(self):
        for raw in (b'<svg/>', b'RIFFnot-a-webp', b'', PNG + b'x' * MAX_IMAGE_BYTES):
            self.raw = raw
            with self.subTest(length=len(raw)), self.assertRaises(MediaError):self.prepared()
        self.raw = PNG
        for kind in ('video', 'file', 'conflicting_types'):
            self.ctx['messages'][0]['attachments'][0]['type'] = kind
            with self.subTest(kind=kind), self.assertRaises(MediaError):self.prepared()

    def test_all_originals_and_total_count_are_bounded_no_first_image_only(self):
        self.ctx['messages'][0]['attachments'] *= 9
        self.current['messages'][0]['attachment_count'] = 9
        with self.assertRaises(MediaError):self.prepared()

    def test_pending_failed_unknown_voice_status_and_missing_text_wait(self):
        self.ctx['messages'][0]['attachments'] = [dict(id='audio', type='voice')]
        self.current['messages'][0]['voice_transcript'] = 'Адрес пока не указан.'
        for status in ('pending', 'processing', 'failed', 'too_long', 'unknown'):
            self.ctx['messages'][0]['voice_transcript_status'] = status
            with self.subTest(status=status), self.assertRaises(MediaError):self.prepared()
        self.ctx['messages'][0]['voice_transcript_status'] = 'done'
        self.current['messages'][0]['voice_transcript'] = ''
        with self.assertRaises(MediaError):self.prepared()

    def test_existing_voice_text_role_is_bound_no_new_asr_or_tone_claim(self):
        self.ctx['messages'][0].update(attachments=[dict(id='audio', type='voice')], voice_transcript_status='done')
        self.current['messages'][0].update(voice_transcript='Нужно подождать минуту.', speaker_role='staff')
        media = self.prepared()
        self.assertEqual(media['voices'][0]['speaker_role'], 'staff')
        self.assertEqual(media['voices'][0]['transcript_status'], 'done')
        self.assertFalse(media['raw_audio_listened'])
        self.assertEqual(self.calls, [])

    def test_same_id_transcript_and_completion_status_change_revision_and_unknown_media(self):
        ctx = dict(convId='voice-chat', messages=[dict(id='m', direction='in', sender_type='client', body='',
            voice_transcript='Улица Первая.', voice_transcript_status='pending', attachments=[dict(type='voice')])])
        _, pending, _, rev1 = _parse(ctx)
        self.assertTrue(pending[0]['unread_media'])
        ctx['messages'][0]['voice_transcript_status'] = 'done'
        _, ready, _, rev2 = _parse(ctx)
        self.assertNotEqual(rev1, rev2);self.assertFalse(ready[0]['unread_media'])
        ctx['messages'][0]['voice_transcript'] = 'Улица Вторая.'
        self.assertNotEqual(rev2, _parse(ctx)[3])

    def test_two_model_stages_receive_same_pixels_without_key_header_or_hidden_audio(self):
        self.current['media'] = self.prepared()
        payloads = [];ledger = UsageLedger()
        def request(payload, timeout):
            payloads.append(payload)
            role = json.loads(payload['instructions'])['role']
            output = dict(kind='review', approved=True, violations=[], checked_claims=[], basis=['current:m1']) if role=='review' else dict(kind='draft', reply='Посмотрю фото.', evidence_ids=['m1'], basis=['current:m1'], claims=[])
            return dict(id='resp-'+role, model='gpt-6.1-sol', status='completed', usage=None, service_tier='default',
                output=[dict(type='message', role='assistant', status='completed', content=[dict(type='output_text', text=json.dumps(output))])])
        transport = ResponsesTransport(request, ledger, media_resolver=self.resolver)
        for role in ('research', 'review'):
            transport(role, pack_context(role, self.current), ())
        images = [[b for row in p['input'] for b in row['content'] if b['type']=='input_image'] for p in payloads]
        self.assertEqual(images[0], images[1]);self.assertEqual(len(images[0]), 1)
        self.assertNotIn('Authorization', json.dumps(payloads))

    def test_missing_original_is_preflight_not_billable_unknown_attempt(self):
        self.current['media'] = self.prepared()
        ledger = UsageLedger();calls = []
        transport = ResponsesTransport(lambda *a: calls.append(a), ledger)
        with self.assertRaises(MediaError):transport('research', pack_context('research', self.current), ())
        self.assertEqual(calls, []);self.assertEqual(ledger.summary()['calls'], 0)

    def test_missing_message_or_changed_metadata_does_not_borrow_other_original(self):
        self.ctx['messages'][0]['id'] = 'other'
        with self.assertRaises(MediaError):self.prepared()

    def test_voice_without_attachment_uses_asr_text_and_late_edit_blocks_transport(self):
        self.ctx['messages'][0].update(attachments=[], voice=True, voice_transcript_status='done')
        self.current['messages'][0].update(attachment_count=0, voice_transcript='Секунду, сейчас отвечу.')
        self.current['media'] = self.prepared()
        self.assertEqual(len(self.current['media']['voices']), 1)
        self.assertEqual(image_inputs(self.current, None), [])
        self.current['messages'][0]['voice_transcript'] = 'Подождите две минуты.'
        with self.assertRaises(MediaError):image_inputs(self.current, None)

    def test_voice_marker_pending_without_attachment_is_not_a_completed_text_message(self):
        self.ctx['messages'][0].update(attachments=[], voice=True, voice_transcript_status='pending')
        self.current['messages'][0]['attachment_count'] = 0
        with self.assertRaises(MediaError):self.prepared()
        self.assertTrue(_unread_media(self.ctx['messages'][0]))

    def test_copied_asr_is_explicitly_labelled_not_a_typed_client_quote(self):
        ctx = assistant_context([dict(id='m', direction='in', sender_type='client', body='Нужно повесить полку.',
            voice_transcript='Нужно повесить полку.', voice_transcript_status='done', attachments=[dict(type='voice')])],
            dir='mnc', accountTitle='Мастер на час', itemTitle='Мастер на час')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='media-test'):
            out, code = Assistant(Store(Path(directory)/'assistant.sqlite3')).handle(
                dict(owner='media-test', action='preview', ctx=ctx, wording_mode='neural_review'))
        self.assertEqual(code, 200);self.assertTrue(out['pending_model'])
        task = json.loads(out['model_task']['task'])
        self.assertEqual(task['conversation'][0]['body_origin'], 'ASR_copy')
        self.assertEqual(task['conversation'][0]['voice_transcript_status'], 'done')

    def voice_preview(self, *, status='pending', attachments=None, transcript=None, **extra):
        ctx = assistant_context([dict(id='voice', direction='in', sender_type='client', voice=True,
            body='', voice_transcript=transcript if transcript is not None else 'Нужно повесить полку.' if status=='done' else '', voice_transcript_status=status,
            attachments=[dict(type='voice')] if attachments is None else attachments)],
            dir='mnc', itemTitle='Мастер на час', accountTitle='Мастер на час', assigneeId='operator',
            assignmentKnown=True, channelAssigned=True, conversationStatus='in_progress',
            botActive=False, hasTransfer=False, **extra)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                LEADBOT_PERSONAL_OWNER_ID='media-test', LEADBOT_PERSONAL_OPERATOR_ID='operator',
                LEADBOT_ASSISTANT_WORDING='reviewed'):
            app = Assistant(Store(Path(directory)/'assistant.sqlite3'))
            out, code = app.handle(dict(owner='media-test', action='preview', ctx=ctx, wording_mode='reviewed'))
        self.assertEqual(code, 200)
        return out

    def test_causal_pending_voice_waits_without_human_escalation_or_question(self):
        for attachments in ([], [dict(type='voice')]):
            out = self.voice_preview(attachments=attachments)
            self.assertEqual(out['action'], 'wait')
            self.assertFalse(out['needs_operator']);self.assertEqual(out['reply'], '')
            self.assertEqual(out['lifecycle']['disposition'], 'wait')
            self.assertNotIn('model_task', out)

    def test_causal_completed_voice_resumes_normal_qualification(self):
        out = self.voice_preview(status='done')
        self.assertEqual(out['action'], 'question')
        self.assertIn('стен', out['reply'].lower())

    def test_causal_failed_voice_or_unread_image_still_needs_review(self):
        for kwargs in (dict(status='failed'), dict(attachments=[dict(type='voice'), dict(type='image', id='p')])):
            out = self.voice_preview(**kwargs)
            self.assertEqual(out['action'], 'handoff');self.assertTrue(out['needs_operator'])

    def test_causal_existing_order_is_not_taken_while_waiting_for_voice(self):
        out = self.voice_preview(crmRequestId='1234567')
        self.assertEqual(out['lifecycle']['disposition'], 'operator_review')
        self.assertIsNone(out['lifecycle']['crm_preparation'])

    def test_partial_asr_is_not_a_completed_complaint_or_client_fact(self):
        text = 'Мастер приезжал и сломал шкаф. Верните деньги.'
        out = self.voice_preview(transcript=text)
        self.assertEqual(out['action'], 'wait');self.assertFalse(out['needs_operator'])
        row = dict(id='m', direction='in', sender_type='client', voice=True, body=text,
                   voice_transcript=text, voice_transcript_status='pending', attachments=[dict(type='voice')])
        _, parsed, _, _ = _parse(dict(convId='asr', messages=[row]))
        self.assertEqual(parsed[0]['body'], '')

    def test_unknown_asr_status_does_not_claim_transcription_is_running(self):
        for attachments in ([], [dict(type='voice')]):
            out = self.voice_preview(status='', attachments=attachments)
            self.assertEqual(out['action'], 'handoff');self.assertTrue(out['needs_operator'])


if __name__ == '__main__':
    unittest.main()
