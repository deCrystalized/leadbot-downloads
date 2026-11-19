"""Explicit ready ASR takes the same complete-text route as done/completed."""
import unittest
import test_research_media204 as fixtures
from research_media import image_inputs
from extension_assistant import _parse


class ReadyASR252Tests(unittest.TestCase):
    def test_full_assistant_ready_voice_resumes_without_unread_audio_handoff(self):
        out=fixtures.MediaTests.voice_preview(self,status='ready',transcript='Нужно повесить полку.')
        self.assertEqual(out['action'],'question')
        self.assertFalse(out['needs_operator'])
        self.assertIn('стен',out['reply'].lower())

    def test_ingress_ready_preserves_existing_ASR_text_and_source_identity(self):
        row=dict(id='voice-source',direction='in',sender_type='client',body='Уточнение.',
                 voice_transcript='Нужно повесить полку.',voice_transcript_status='ready',
                 attachments=[dict(kind='voice',id='audio-source')])
        _,rows,_,_=_parse(dict(convId='synthetic-ready',messages=[row]))
        self.assertEqual(rows[0]['body'],'Уточнение.\nНужно повесить полку.')
        self.assertEqual(rows[0]['written_body'],'Уточнение.')
        self.assertEqual(rows[0]['id'],'voice-source')
        self.assertFalse(rows[0]['unread_media'])

    def test_ready_empty_voice_cannot_become_completed_content(self):
        out=fixtures.MediaTests.voice_preview(self,status='ready',transcript='')
        self.assertEqual(out['action'],'handoff')
        self.assertTrue(out['needs_operator'])

    def test_ready_voice_attachment_reaches_both_stage_inputs_as_existing_text(self):
        f=fixtures.MediaTests();f.setUp()
        f.ctx['messages'][0].update(attachments=[dict(id='audio',type='voice')],voice_transcript_status='ready')
        f.current['messages'][0].update(voice_transcript='Секунду, уточню адрес.',speaker_role='client')
        f.current['media']=f.prepared()
        self.assertEqual(f.current['media']['voices'][0]['transcript_status'],'ready')
        self.assertEqual(image_inputs(f.current,f.resolver),[])
        self.assertFalse(f.current['media']['raw_audio_listened'])
        self.assertEqual(f.calls,[])

    def test_ready_marker_only_voice_preserves_author_and_does_not_wait_forever(self):
        f=fixtures.MediaTests();f.setUp()
        f.ctx['messages'][0].update(attachments=[],voice=True,voice_transcript_status='ready')
        f.current['messages'][0].update(attachment_count=0,voice_transcript='Адрес уточню.',speaker_role='staff')
        f.current['media']=f.prepared()
        self.assertEqual(f.current['media']['voices'][0]['speaker_role'],'staff')
        self.assertEqual(f.current['media']['voices'][0]['transcript_status'],'ready')
        self.assertEqual(image_inputs(f.current,f.resolver),[])
        self.assertEqual(f.calls,[])
