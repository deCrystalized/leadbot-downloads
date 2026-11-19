"""Room for the full native media proof without lengthening customer replies."""
import json
import unittest

import test_photo_work_clarification514 as fixture


class PhotoOutputBudget157Tests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.PhotoWorkClarificationTests('test_exact_reviewed_photo_gets_useful_work_question')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def test_photo_only_proof_has_room_and_reply_limits_are_unchanged(self):
        p = self.h.receipt(self.h.context(), observations={'content_kind': 'product_photo', 'device_kind': 'wardrobe'})
        t, c = self.h.candidate(p)
        self.assertEqual(p['model_task']['max_tokens'], 1100)
        schema = p['model_task']['response_format']['schema']['properties']
        self.assertEqual(schema['reply']['maxLength'], 280)
        self.assertEqual(schema['context_review']['properties']['note']['maxLength'], 200)
        self.assertEqual(c['context_review']['photo_work_review']['requested_action'], 'unspecified')
        o = self.h.finish(p, c)
        self.assertFalse(o['validation']); self.assertIn('Что требуется сделать?', o['reply'])
        self.assertLessEqual(len(o['reply']), 280); self.assertFalse(o['auto_enabled'])

    def test_named_assembly_does_not_get_the_photo_only_budget(self):
        p = self.h.receipt(self.h.context('Нужно собрать шкаф, инструкция есть.'),
                           observations={'content_kind': 'product_photo', 'device_kind': 'wardrobe'})
        t = json.loads(p['model_task']['task'])
        self.assertNotIn('photo_work_clarification', t)
        self.assertEqual(p['model_task']['max_tokens'], 700)

