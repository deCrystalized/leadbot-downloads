"""Preserve semantic protection while removing a redundant wire annotation."""
import copy
import json
import unittest
import extension_assistant as ext
import test_photo_work_clarification514 as fixture

class PhotoSchema158Tests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.PhotoWorkClarificationTests('test_exact_reviewed_photo_gets_useful_work_question')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def prepared(self):
        return self.h.receipt(self.h.context(), observations={'content_kind':'product_photo','device_kind':'wardrobe'})

    def test_wire_annotation_removed_but_original_boundary_and_proof_retained(self):
        p=self.prepared();task,c=self.h.candidate(p)
        schema=p['model_task']['response_format']['schema']['properties']['context_review']
        self.assertNotIn('description',schema['properties']['last_intent'])
        self.assertIn('Требуемая работа пока не названа',task['client_goal_boundary']['meaning'])
        proof=schema['properties']['photo_work_review']
        self.assertFalse(proof['additionalProperties'])
        self.assertEqual(set(proof['required']),set(task['photo_work_clarification']['required_review']))
        self.assertEqual(p['model_task']['max_tokens'],1100)
        self.assertFalse(self.h.finish(p,c)['validation'])

    def test_free_description_does_not_let_wrong_goal_or_wrong_proof_pass(self):
        p=self.prepared();task,c=self.h.candidate(p)
        for field,text in [('last_intent','Заказать ремонт шкафа'),('latest_client_meaning','Клиент, вероятно, сообщает о поломке шкафа.')]:
            bad=copy.deepcopy(c);bad['context_review'][field]=text
            with self.subTest(field=field):
                self.assertIn('photo_unstated_work_or_diagnosis',ext._context_review(bad,task)[2])
        bad=copy.deepcopy(c);bad['context_review']['photo_work_review']['future_messages_used']=True
        self.assertIn('photo_work_review_mismatch',ext._context_review(bad,task)[2])
