"""A manually reviewed document image is not a hardware photograph or OCR truth."""
import copy
import json
import unittest

import personal_media
import test_personal_media as receipts
import test_photo_work_clarification514 as photos


class DocumentMedia166Tests(unittest.TestCase):
    def setUp(self):
        self.h = photos.PhotoWorkClarificationTests('test_exact_reviewed_photo_gets_useful_work_question')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def ready(self):
        ctx = self.h.context()
        ctx['dir'] = 'kp'
        ctx['accountTitle'] = 'Учебный КП'
        ctx['itemTitle'] = 'Ремонт принтеров'
        ctx['origin'] = 'В89'
        ctx['messages'][0]['body'] = 'Здравствуйте, ремонтируете принтер Kyocera 5003i?'
        p = self.h.receipt(ctx, observations=dict(content_kind='document_image'))
        self.assertTrue(p.get('pending_model'), p.get('reason'))
        task = json.loads(p['model_task']['task'])
        c = dict(reply=task['proposed_reply'], needs_operator=False, context_review=dict(
            last_intent='Клиент спрашивает о ремонте принтера',
            latest_client_meaning='Клиент прислал скриншот документа, подробности проблемы ещё не описал',
            selected_step_fits=True, evidence_ids=['image'], note='Достаточно уточнить описанную клиентом проблему, не ставя диагноз по документу.'))
        if task.get('item_fitment_context'):
            c['context_review']['item_fitment_review'] = copy.deepcopy(
                task['item_fitment_context']['required_review'])
        return ctx, p, task, c

    def test_document_type_reaches_actual_model_task_without_device_or_logo_inference(self):
        ctx, p, task, c = self.ready()
        observation = task['verified_media_observations'][-1]
        self.assertEqual(observation['content_kind'], 'document_image')
        self.assertNotIn('model', observation)
        self.assertNotIn('brand', observation)
        self.assertNotIn('current_image_brand', task)
        self.assertEqual(task['current_document_image']['evidence_id'], 'image')
        self.assertEqual(task['current_document_image']['signature'], observation['signature'])
        self.assertIn('not_independent_vision', task['current_document_image']['source'])
        self.assertIn('diagnosis', task['current_document_image']['does_not_establish'])
        self.assertIn('current_document_image', p['model_task']['system'])
        self.assertFalse(self.h.finish(p, c)['validation'])

    def test_document_cannot_supply_a_model_brand_device_contact_error_or_diagnosis(self):
        for extra in (dict(model='Kyocera 5003i'), dict(brand='RESO'), dict(device_kind='pc'),
                      dict(contact_phone='79001112233', contact_role='customer'), dict(diagnosis='тонер пуст'),
                      dict(error_system='printer', error_code='E100')):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                personal_media.normalize_observations(dict(content_kind='document_image', **extra))

    def test_false_device_photo_is_rejected_in_the_reply_and_all_review_prose(self):
        for field in ('last_intent', 'latest_client_meaning', 'note', 'reply'):
            with self.subTest(field=field):
                ctx, p, task, c = self.ready()
                target = c if field == 'reply' else c['context_review']
                target[field] = 'Клиент прислал фото принтера.'
                out = self.h.finish(p, c)
                self.assertIn('document_image_as_device_photo', out['validation'])
                self.assertFalse(out['reply'])
                self.assertTrue(out['needs_operator'])

    def test_print_results_negation_and_request_for_a_future_device_photo_remain_distinct(self):
        for text in ('Клиент прислал фото результатов печати принтера.',
                     'Это не фото принтера, а скриншот документа.',
                     'Фото принтера не предоставлено.', 'Нет фото принтера.',
                     'Фото принтера отсутствует.', 'Фото принтера пока нет.',
                     'Пришлите фото принтера.', 'Нужно фото принтера, пока получен только документ.',
                     'Клиент сообщил, что внизу листа бледная печать.'):
            with self.subTest(text=text):
                ctx, p, task, c = self.ready()
                c['context_review']['note'] = text
                self.assertFalse(self.h.finish(p, c)['validation'])

    def test_another_image_does_not_inherit_document_kind_or_acknowledgement(self):
        ctx, p, task, c = self.ready()
        self.h.finish(p, c)
        next_image = copy.deepcopy(ctx['messages'][-1])
        next_image['id'] = 'new-image'
        next_image['attachments'][0]['version'] = 'new'
        ctx['messages'].append(next_image)
        pending = self.h.preview(ctx)
        self.assertTrue(pending['media_review_required'])
        self.assertFalse(pending.get('pending_model'))
        p = self.h.receipt(ctx, observations=dict(content_kind='device_label', model='Canon G3411'))
        task = json.loads(p['model_task']['task'])
        self.assertNotIn('current_document_image', task)
        self.assertEqual(task['current_image_brand']['evidence_id'], 'new-image')

    def test_raw_document_flags_do_not_bypass_receipt(self):
        ctx = self.h.context()
        ctx['messages'][-1].update(media_reviewed=True, unread_media=False, media_observation=dict(content_kind='document_image'))
        out = self.h.preview(ctx)
        self.assertTrue(out['media_review_required'])
        self.assertFalse(out.get('pending_model'))

    def test_document_requires_current_client_and_retains_nonce_signature_and_role_guards(self):
        h = receipts.PersonalMediaTests('test_exact_review_unblocks_only_the_viewed_image_without_inventing_facts')
        h.setUp()
        self.addCleanup(h.tearDown)
        approval = dict(h.confirmation(), observations=dict(content_kind='document_image'))
        for version in ('2.7.9', '2.8.12'):
            self.assertFalse(h.call('personal_media_review', **dict(approval, client_version=version))['ok'])
        valid = dict(approval, client_version='2.8.13')
        for changes in (dict(operator_id='other'), dict(media_signature='wrong'), dict(activation_nonce='x'*30)):
            self.assertFalse(h.call('personal_media_review', **(valid | changes))['ok'])
        out = h.call('personal_media_review', **valid)
        self.assertTrue(out['ok'])
        self.assertNotEqual(out['activation_nonce'], valid['activation_nonce'])
        self.assertFalse(h.call('personal_media_review', **valid)['ok'])
        self.assertFalse(out['auto_enabled'])


if __name__ == '__main__':
    unittest.main()
