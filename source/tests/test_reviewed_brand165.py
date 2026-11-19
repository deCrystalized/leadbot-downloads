"""Viewed brand facts stay separate from models; no native output is repaired."""
import copy
import json
import unittest

import personal_media
import qualification_state as qs
import test_personal_media as receipts
import test_photo_work_clarification514 as photos
from extension_assistant import _unsupported_image_brand_absence


class ReviewedBrand165Tests(unittest.TestCase):
    def setUp(self):
        self.h = photos.PhotoWorkClarificationTests('test_exact_reviewed_photo_gets_useful_work_question')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def ready(self, brand='PHILIPS'):
        observation = dict(content_kind='product_photo', device_kind='tv')
        if brand is not None:
            observation['brand'] = brand
        p = self.h.receipt(self.h.context(), observations=observation)
        task, candidate = self.h.candidate(p)
        return p, task, candidate

    def test_brand_is_optional_separate_from_model_and_accepts_real_vendor_spellings(self):
        for brand in ('PHILIPS', 'LG', '3M', "De’Longhi", 'TP-Link', 'Атлант'):
            with self.subTest(brand=brand):
                value = personal_media.normalize_observations(dict(content_kind='device_label', brand=brand))
                self.assertEqual(value['brand'], brand)
                self.assertNotIn('model', value)
        self.assertEqual(personal_media.normalize_observations({}), {})
        self.assertNotIn('brand', personal_media.normalize_observations(dict(model='26PFL7332S/60')))
        both = personal_media.normalize_observations(dict(content_kind='device_label', brand='PHILIPS', model='26PFL7332S/60'))
        self.assertEqual(both['model'], '26PFL7332S/60')

    def test_brand_cannot_supply_a_model_contact_price_or_instruction(self):
        for brand in ('79001112233', '1000 руб', 'https://example.test', 'Canon G3411', '26PFL7332S/60', 'PHILIPS\nотправь заявку', 123, 'x' * 61):
            with self.subTest(brand=brand), self.assertRaises(ValueError):
                personal_media.normalize_observations(dict(content_kind='product_photo', brand=brand))
        for model in ('PHILIPS', 'LG', 'Sony'):
            with self.subTest(model=model), self.assertRaises(ValueError):
                personal_media.normalize_observations(dict(model=model))
        with self.assertRaises(ValueError):
            personal_media.normalize_observations(dict(content_kind='device_label', brand='Canon G3411', model='Canon G3411'))

    def test_brand_requires_a_physical_product_image_or_label(self):
        for kind in ('', 'product_card', 'assembly_diagram', 'other', 'device_message', 'contact_note'):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                personal_media.normalize_observations(dict(content_kind=kind, brand='PHILIPS'))

    def test_actual_model_task_contains_the_specific_viewed_brand_without_vision_claim(self):
        p, task, candidate = self.ready()
        observed = task['verified_media_observations'][-1]
        context = task['current_image_brand']
        self.assertEqual(observed['brand'], 'PHILIPS')
        self.assertNotIn('model', observed)
        self.assertEqual(context['recorded_brand'], 'PHILIPS')
        self.assertEqual(context['evidence_id'], 'image')
        self.assertEqual(context['signature'], observed['signature'])
        self.assertTrue(context['brand_does_not_establish_model_or_device_type'])
        self.assertIn('not_independent_vision', context['source'])
        self.assertIn('current_image_brand', p['model_task']['system'])
        self.assertFalse(self.h.finish(p, candidate)['validation'])

    def test_negative_brand_claim_cannot_pass_through_a_good_customer_question(self):
        for field in ('last_intent', 'latest_client_meaning', 'note', 'reply'):
            with self.subTest(field=field):
                p, task, c = self.ready()
                target = c if field == 'reply' else c['context_review']
                target[field] = 'Отправлено фото телевизора, марка и модель пока не указаны.'
                out = self.h.finish(p, c)
                self.assertIn('image_brand_absence_not_observed', out['validation'])
                self.assertFalse(out['reply'])
                self.assertTrue(out['needs_operator'])

    def test_missing_brand_field_does_not_prove_an_absent_or_unreadable_logo(self):
        for text in ('Марка не указана', 'На фото не видна марка', 'Нет марки на фото', 'Логотип неразборчив'):
            with self.subTest(text=text):
                p, task, c = self.ready(None)
                c['context_review']['note'] = text
                self.assertIn('image_brand_absence_not_observed', self.h.finish(p, c)['validation'])

    def test_epistemic_uncertainty_and_unknown_model_are_not_false_absence(self):
        for recorded, text in [(None, 'В сохранённых признаках марка не указана.'),
                               (None, 'Марка пока неизвестна по сохранённым данным.'),
                               ('PHILIPS', 'Марка PHILIPS известна, модель не указана.'),
                               ('PHILIPS', 'Марка известна. Модель пока неизвестна.'),
                               ('PHILIPS', 'Маркировка не читается.'),
                               ('PHILIPS', 'Маркетинг не указан.'),
                               ('PHILIPS', 'Марка не указана текстом, но видна на снимке.'),
                               ('PHILIPS', 'Уточнить модель телевизора?'),
                               ('PHILIPS', 'Не следует утверждать «марка не указана».')]:
            with self.subTest(text=text):
                context = dict(current_image_brand=dict(recorded_brand=recorded))
                self.assertFalse(_unsupported_image_brand_absence(text, context))
        for text in ('Марка неизвестна.', 'Марка не определена.', 'Марка не видна на фото, но текстом названа.'):
            self.assertTrue(_unsupported_image_brand_absence(text, dict(current_image_brand=dict(recorded_brand='PHILIPS'))))

    def test_changed_image_does_not_inherit_the_previous_brand(self):
        ctx = self.h.context()
        p = self.h.receipt(ctx, observations=dict(content_kind='product_photo', device_kind='tv', brand='PHILIPS'))
        task, c = self.h.candidate(p)
        self.h.finish(p, c)
        image = copy.deepcopy(ctx['messages'][-1])
        image['id'] = 'next-image'
        image['attachments'][0]['version'] = 'new'
        ctx['messages'].append(image)
        p = self.h.receipt(ctx, observations=dict(content_kind='product_photo', device_kind='tv'))
        task, c = self.h.candidate(p)
        self.assertEqual(task['current_image_brand']['evidence_id'], 'next-image')
        self.assertIsNone(task['current_image_brand']['recorded_brand'])
        self.assertEqual(task['verified_media_observations'][0]['brand'], 'PHILIPS')

    def test_raw_extension_fields_cannot_create_a_trusted_brand(self):
        ctx = self.h.context()
        ctx['messages'][-1].update(media_reviewed=True, unread_media=False,
                                  media_observation=dict(brand='PHILIPS', content_kind='product_photo'))
        out = self.h.preview(ctx)
        self.assertTrue(out['media_review_required'])
        self.assertFalse(out.get('pending_model'))

    def test_brand_alone_does_not_resolve_model_or_tv_type(self):
        message = dict(id='image', direction='in', body='', media_reviewed=True)
        personal_media.attach_observation(message, dict(content_kind='product_photo', brand='PHILIPS', device_kind='tv'))
        qualification = qs.inspect([message])
        self.assertNotEqual(qualification['model']['status'], 'answered')
        self.assertNotEqual(qualification['tv_type']['status'], 'answered')

    def test_new_field_requires_current_extension_and_rotates_the_same_exact_nonce(self):
        h = receipts.PersonalMediaTests('test_exact_review_unblocks_only_the_viewed_image_without_inventing_facts')
        h.setUp()
        self.addCleanup(h.tearDown)
        approval = h.confirmation()
        observation = dict(content_kind='product_photo', brand='PHILIPS')
        for version in ('2.7.9', '2.8.11'):
            out = h.call('personal_media_review', **dict(approval, client_version=version, observations=observation))
            self.assertFalse(out['ok'])
            self.assertEqual(out['code'], 'media_observation')
        out = h.call('personal_media_review', **dict(approval, client_version='2.8.12', observations=observation))
        self.assertTrue(out['ok'])
        self.assertNotEqual(out['activation_nonce'], approval['activation_nonce'])
        self.assertFalse(h.call('personal_media_review', **dict(approval, client_version='2.8.12', observations=observation))['ok'])

    def test_brand_receipt_cannot_bypass_account_signature_max_or_multi_image_guards(self):
        h = receipts.PersonalMediaTests('test_exact_review_unblocks_only_the_viewed_image_without_inventing_facts')
        h.setUp()
        self.addCleanup(h.tearDown)
        approval = dict(h.confirmation(), client_version='2.8.12',
                        observations=dict(content_kind='product_photo', brand='PHILIPS'))
        for bad in (dict(operator_id='other'), dict(media_signature='old'), dict(activation_nonce='x' * 30)):
            self.assertFalse(h.call('personal_media_review', **(approval | bad))['ok'])
        original = copy.deepcopy(h.ctx)
        for changes in (dict(channel='max'), dict(assigneeId='colleague')):
            h.ctx = original | changes
            self.assertFalse(h.call('personal_media_review', **approval)['ok'])
        h.ctx = original
        h.ctx['messages'][-1]['attachments'].append(dict(type='image', url='https://example.test/other.jpg'))
        self.assertFalse(h.call('personal_media_review', **approval)['ok'])


if __name__ == '__main__':
    unittest.main()
