"""Synthetic neighbors: an unknown photo cannot acquire an unrelated subject.

These are new complete candidates, never reconstructed native provider output.
"""
import copy
import json
import unittest

import test_photo_work_clarification514 as fixture


class PhotoSubject162Tests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.PhotoWorkClarificationTests('test_exact_reviewed_photo_gets_useful_work_question')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def ready(self, body='', prior=None, observation=None):
        p = self.h.receipt(self.h.context(body, prior=prior),
                           observations=observation or {'content_kind': 'other'})
        t, c = self.h.candidate(p)
        return p, t, c

    def test_complete_synthetic_wrong_wardrobe_cannot_pass_review_or_customer_reply(self):
        for field in ('last_intent', 'latest_client_meaning', 'note', 'reply'):
            with self.subTest(field=field):
                p, t, c = self.ready()
                if field == 'reply':
                    c[field] = 'Спасибо за фото шкафа. Что требуется сделать?'
                else:
                    c['context_review'][field] = 'Клиент прислал фото шкафа, требуемая работа не названа.'
                o = self.h.finish(p, c)
                self.assertIn('photo_subject_not_observed', o['validation'])
                self.assertEqual(o['reply'], '')
                self.assertTrue(o['needs_operator'])

    def test_other_unrecorded_subjects_do_not_sneak_through_a_correct_question(self):
        for noun in ('кровать', 'комод', 'духовка', 'телевизор', 'монитор',
                     'компьютер', 'видеокарта', 'витая пара', 'проводка'):
            with self.subTest(noun=noun):
                p, t, c = self.ready()
                c['context_review']['note'] = 'На изображении ' + noun + ', работа пока не названа.'
                self.assertIn('photo_subject_not_observed', self.h.finish(p, c)['validation'])

    def test_unknown_subject_keeps_a_free_meaning_and_a_useful_question(self):
        p, t, c = self.ready()
        o = self.h.finish(p, c)
        self.assertFalse(o['validation'])
        subject = t['photo_work_clarification']['observed_subject']
        self.assertEqual(subject['content_kind'], 'other')
        self.assertIsNone(subject['device_kind'])
        self.assertEqual(subject['evidence_id'], 'image')
        self.assertNotIn('fixed_latest_client_meaning', t['output_contract'])
        schema = p['model_task']['response_format']['schema']['properties']['context_review']['properties']
        self.assertNotIn('enum', schema['last_intent'])
        self.assertNotIn('enum', schema['latest_client_meaning'])
        self.assertEqual(len(schema['photo_work_review']['required']), 6)
        self.assertEqual(p['model_task']['max_tokens'], 1100)

    def test_a_truly_recorded_wardrobe_is_still_a_valid_subject(self):
        p, t, c = self.ready(observation={'content_kind': 'product_photo', 'device_kind': 'wardrobe'})
        c['context_review']['latest_client_meaning'] = 'Клиент прислал изображение шкафа без указания операции.'
        o = self.h.finish(p, c)
        self.assertFalse(o['validation'])
        self.assertEqual(t['photo_work_clarification']['observed_subject']['device_kind'], 'wardrobe')
        self.assertFalse(o['lead']['can_create_automatically'])

    def test_literal_client_subject_is_kept_without_inventing_an_operation(self):
        p, t, c = self.ready('Проводка')
        c['context_review']['latest_client_meaning'] = 'Клиент назвал проводку и прислал фото, работу не назвал.'
        o = self.h.finish(p, c)
        self.assertFalse(o['validation'])
        self.assertIn('Проводка', t['photo_work_clarification']['client_literal_subject_context'])
        self.assertEqual(t['photo_work_clarification']['required_review']['requested_action'], 'unspecified')

    def test_staff_or_advertisement_is_not_evidence_of_the_image_subject(self):
        for source in ('staff', 'advertisement'):
            with self.subTest(source=source):
                ctx = self.h.context(prior='На фото шкаф' if source == 'staff' else None)
                ctx['itemTitle'] = 'Сборка шкафов'
                p = self.h.receipt(ctx, observations={'content_kind': 'other'})
                t, c = self.h.candidate(p)
                c['context_review']['latest_client_meaning'] = 'Клиент прислал фото шкафа без указания работы.'
                self.assertIn('photo_subject_not_observed', self.h.finish(p, c)['validation'])

    def test_an_older_wardrobe_does_not_describe_the_next_unknown_image(self):
        ctx = self.h.context()
        first = self.h.receipt(ctx, observations={'content_kind': 'product_photo', 'device_kind': 'wardrobe'})
        t, c = self.h.candidate(first)
        self.assertFalse(self.h.finish(first, c)['validation'])
        image = copy.deepcopy(ctx['messages'][-1])
        image['id'] = 'image-new'
        image['attachments'][0]['id'] = 'synthetic-new-photo'
        ctx['messages'].append(image)
        p = self.h.receipt(ctx, observations={'content_kind': 'other'})
        t, c = self.h.candidate(p)
        c['context_review']['evidence_ids'] = ['image-new']
        c['context_review']['latest_client_meaning'] = 'Последнее фото показывает шкаф, работа не названа.'
        self.assertIn('photo_subject_not_observed', self.h.finish(p, c)['validation'])
        self.assertEqual(t['photo_work_clarification']['observed_subject']['evidence_id'], 'image-new')

    def test_raw_extension_observation_still_cannot_grant_photo_access(self):
        ctx = self.h.context()
        ctx['messages'][-1].update(media_reviewed=True, unread_media=False,
                                  media_observation={'content_kind': 'product_photo', 'device_kind': 'wardrobe'})
        p = self.h.preview(ctx)
        self.assertFalse(p.get('pending_model'))
        self.assertTrue(p['media_review_required'])


if __name__ == '__main__':
    unittest.main()
