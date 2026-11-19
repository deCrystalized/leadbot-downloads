"""Perceptual cache metadata must not invent a manual Root/human inspection."""
import json
import tempfile
import unittest

from assistant_store import Store
import research_vision


class VisualProvenance252Tests(unittest.TestCase):
    def test_staging_does_not_invent_a_manual_acceptance_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory+'/db')
            payload=dict(chat_id='synthetic',revision='r1',policy_version='p1',
                known={'source_client_group':'group','account_id':'account'},messages=[
                    dict(id='m1',direction='in',sender_type='client',body='Нужно дособрать шкаф.',reviewable_image=True,media_signature='sig')])
            research_vision.stage(store,'scope',payload,{'visual_observation':{'images':[]}},'job')
            with store.connect() as db:
                value=json.loads(db.execute('SELECT body FROM research_visual_observations').fetchone()[0])
            self.assertNotIn('manual_root',value['provenance']['kind'])
            self.assertFalse(value['provenance']['human_media_review'])

    def test_diagram_projection_keeps_model_origin_without_claiming_manual_inspection(self):
        message=dict(id='m1',direction='in',sender_type='client',body='Нужно дособрать шкаф.',
                     media_signature='sig',media_model_reviewed=True,unread_media=False)
        observation=[dict(speaker_role='client',media_id='photo',sha256='a'*64,
                          attributes={'content_kind':'assembly_diagram'})]
        research_vision._qualification_projection(message,observation,[message],{'direction':'mnc'},{'job':'job'})
        projected=message['_model_qualification_observation']
        self.assertNotIn('ручной',projected['instructions'])
        self.assertFalse(projected['human_media_review'])
        self.assertTrue(projected['not_client_literal_statement'])
