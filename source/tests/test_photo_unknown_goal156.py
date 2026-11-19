"""A useful question does not justify an invented goal behind an image."""
import json
import unittest

import assistant_policy as policy
import test_photo_work_clarification514 as fixture


class PhotoUnknownGoal156Tests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.PhotoWorkClarificationTests('test_exact_reviewed_photo_gets_useful_work_question')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def ready(self, body='', prior=None):
        p = self.h.receipt(self.h.context(body, prior=prior),
                           observations={'content_kind': 'product_photo', 'device_kind': 'wardrobe'})
        t, c = self.h.candidate(p)
        return p, t, c

    def denied_field(self, field, text):
        p, t, c = self.ready(); c['context_review'][field] = text
        o = self.h.finish(p, c)
        self.assertEqual(o['reply'], '')
        self.assertIn('photo_unstated_work_or_diagnosis', o['validation'])

    def test_actual_native_goal_claim_is_rejected(self):
        self.denied_field('last_intent', 'Отправить фото шкафа и сообщить о проблеме')

    def test_actual_native_probable_repair_meaning_is_rejected(self):
        for text in ['Клиент отправил фото шкафа, вероятно, чтобы сообщить о проблеме или заказать ремонт.',
                     'Клиент отправил фото шкафа для ремонта.', 'Прислал изображение для сборки шкафа.']:
            with self.subTest(text=text):
                self.denied_field('latest_client_meaning', text)

    def test_unsupported_repair_in_note_is_also_rejected(self):
        self.denied_field('note', 'Клиент хочет ремонт шкафа, поэтому уточняем детали.')

    def test_probable_assembly_is_not_an_order(self):
        for text in ['Вероятно, клиент хочет заказать сборку шкафа.', 'Сборка шкафа', 'Собрать шкаф']:
            with self.subTest(text=text):
                self.denied_field('last_intent', text)

    def test_possible_installation_is_not_an_order(self):
        self.denied_field('latest_client_meaning', 'Возможно, требуется установка шкафа.')

    def test_unknown_work_disclaimer_cannot_launder_following_guess(self):
        self.denied_field('note', 'Работа не указана, вероятно, клиент хочет ремонт.')

    def test_photo_is_not_a_request_to_diagnose(self):
        self.denied_field('last_intent', 'Определить неисправность шкафа по фото.')

    def test_unknown_operation_can_be_reported_without_a_guess(self):
        p, t, c = self.ready(); c['context_review']['last_intent'] = 'Требуемая работа пока не названа'
        c['context_review']['latest_client_meaning'] = 'Клиент прислал изображение шкафа без указания операции'
        c['context_review']['note'] = 'Нужен вопрос о требуемой помощи, фото не доказывает заказ ремонта.'
        o = self.h.finish(p, c); self.assertFalse(o['validation']); self.assertFalse(o['needs_operator'])

    def test_explicit_assembly_keeps_ordinary_admission(self):
        p = self.h.receipt(self.h.context('Нужно собрать шкаф, инструкция есть.'),
                           observations={'content_kind': 'product_photo', 'device_kind': 'wardrobe'})
        t = json.loads(p['model_task']['task'])
        self.assertNotIn('photo_work_clarification', t)
        self.assertNotEqual(t.get('client_goal_boundary', {}).get('source'), 'observed_photo_without_stated_work')

    def test_explicit_repair_is_not_erased_by_the_image(self):
        p = self.h.receipt(self.h.context('Нужно отремонтировать шкаф, дверь отвалилась.'),
                           observations={'content_kind': 'product_photo', 'device_kind': 'wardrobe'})
        if p.get('model_task'):
            self.assertNotIn('photo_work_clarification', json.loads(p['model_task']['task']))
        self.assertNotEqual(p.get('action'), 'refuse')

    def test_unreviewed_image_does_not_get_a_model_task(self):
        p = self.h.preview(self.h.context()); self.assertFalse(p.get('pending_model'))
        self.assertTrue(p['media_review_required'])

    def test_unspecified_native_proof_must_agree_with_free_prose(self):
        p, t, c = self.ready()
        self.assertEqual(c['context_review']['photo_work_review']['requested_action'], 'unspecified')
        c['context_review']['last_intent'] = 'Заказать ремонт шкафа'
        o = self.h.finish(p, c); self.assertIn('photo_unstated_work_or_diagnosis', o['validation'])

    def test_meaning_is_not_forced_to_a_template_to_hide_bad_understanding(self):
        p, t, c = self.ready()
        self.assertNotIn('fixed_latest_client_meaning', t['output_contract'])
        schema = p['model_task']['response_format']['schema']['properties']['context_review']['properties']
        self.assertNotIn('enum', schema['last_intent'])
        self.assertNotIn('enum', schema['latest_client_meaning'])
        self.assertEqual({d['context_review']['selected_step_fits'] for d in t['output_contract']['decision_states']}, {True, False})

    def test_first_photo_reply_keeps_server_greeting_and_useful_question(self):
        p, t, c = self.ready(); c['reply'] = 'Что требуется сделать?'
        o = self.h.finish(p, c); self.assertFalse(o['validation'])
        self.assertTrue(o['reply'].startswith('Здравствуйте!'))
        self.assertIn('Что требуется сделать?', o['reply'])

    def test_staff_repair_suggestion_does_not_become_client_goal(self):
        p, t, c = self.ready(prior='Можно починить шкаф.')
        c['context_review']['last_intent'] = 'Клиент хочет заказать ремонт шкафа'
        o = self.h.finish(p, c); self.assertIn('photo_unstated_work_or_diagnosis', o['validation'])

    def test_unknown_goal_boundary_is_observed_before_proposed_action(self):
        p, t, c = self.ready(); text = p['model_task']['task']
        self.assertLess(text.index('"photo_work_clarification"'), text.index('"proposed_reply"'))
        self.assertEqual(t['photo_work_clarification']['client_requested_action'], 'not_stated')
        schema = p['model_task']['response_format']['schema']['properties']['context_review']['properties']
        self.assertIn('Требуемая работа пока не названа клиентом', t['client_goal_boundary']['meaning'])
        self.assertLess(text.index('"client_goal_boundary"'), text.index('"proposed_reply"'))
        self.assertNotIn('description', schema['last_intent'])

