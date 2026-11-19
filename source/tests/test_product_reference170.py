"""Product references stay source-bound instead of inventing assembly information."""
import copy
import json
import unittest

import extension_assistant as ext
import personal_media
import test_personal_media as media_receipts


class ProductReference170Tests(unittest.TestCase):
    def setUp(self):
        self.h = media_receipts.PersonalMediaTests('test_exact_review_unblocks_only_the_viewed_image_without_inventing_facts')
        self.h.setUp()
        self.addCleanup(self.h.tearDown)
        self.h.ctx['messages'] = [
            dict(id='job', direction='in', sender_type='client',
                 body='Сколько стоит собрать шкаф-купе с зеркальными дверями?'),
            dict(id='question', direction='out', sender_type='operator', body='Схема есть?'),
            dict(id='answer', direction='in', sender_type='client', body='Схемы нет, шкаф б/у'),
            dict(id='image', direction='in', sender_type='client', body='',
                 attachments=[dict(kind='image', media_id='synthetic-product-170')]),
            dict(id='caption', direction='in', sender_type='client', body='Вот он в интернете'),
        ]

    def preview(self):
        return self.h.call('preview', wording_mode='neural_review')

    def ready(self):
        for _ in range(3):
            first = self.preview()
            if not first['media_review_required']:
                self.assertTrue(first.get('pending_model'), first.get('reason'))
                return first, json.loads(first['model_task']['task'])
            approval = self.h.confirmation()
            approval.update(client_version='2.8.13', observations={'content_kind': 'product_card'})
            self.assertTrue(self.h.call('personal_media_review', **approval)['ok'])
        self.fail('Not all synthetic image receipts were accepted')

    def candidate(self, task):
        return dict(reply=task['output_contract']['example']['reply'], needs_operator=False,
                    context_review=dict(last_intent='Сборка шкафа, вопрос стоимости.',
                        latest_client_meaning=task['output_contract']['fixed_latest_client_meaning'],
                        selected_step_fits=True, evidence_ids=['caption'], note='Следующий вопрос уместен.'))

    def finish(self, p, c):
        return self.h.call('finalize', request_id=p['request_id'], revision=p['revision'], candidate=c)

    def helper(self, **changes):
        ctx = copy.deepcopy(self.h.ctx)
        ctx['messages'][-1].update(changes)
        _, rows, _, _ = ext._parse(ctx)
        picture = next(m for m in rows if m['id'] == 'image')
        picture.update(unread_media=False, media_reviewed=True, offline_fixture=True)
        personal_media.attach_observation(picture, {'content_kind': 'product_card'}, source='offline_reviewed_image')
        timeline = [dict(id=m['id'], position=i, review_ref='context-position:'+str(i),
                        speaker_role='client' if m.get('direction') == 'in' else 'staff',
                        body=m.get('body', ''), voice_transcript=m.get('voice_transcript', ''),
                        attachment_count=len(m.get('attachments') or []))
                    for i, m in enumerate(ctx['messages'])]
        return timeline, rows

    def test_real_receipt_task_binds_caption_and_keeps_missing_instruction(self):
        p, task = self.ready()
        reference = task['product_reference_context']
        self.assertEqual(reference['evidence_id'], 'caption')
        self.assertEqual(reference['image_evidence_ids'], ['image'])
        self.assertEqual(reference['quote'], 'Вот он в интернете')
        self.assertIn('new_instruction_availability', reference['does_not_establish'])
        self.assertEqual(p['qualification']['instructions']['value'], 'Схемы нет')
        self.assertEqual(task['latest_client_message']['body'], 'Вот он в интернете')
        self.assertEqual(len(task['conversation']), len(self.h.ctx['messages']))
        schema = p['model_task']['response_format']['schema']['properties']['context_review']['properties']
        self.assertEqual(schema['latest_client_meaning']['enum'],
                         [task['output_contract']['fixed_latest_client_meaning']])

    def test_observed_wrong_assembly_meaning_is_rejected_without_repair(self):
        p, task = self.ready()
        c = self.candidate(task)
        c['context_review']['latest_client_meaning'] = 'Сообщает, что нашёл информацию о сборке шкафа в интернете'
        before = copy.deepcopy(c)
        out = self.finish(p, c)
        self.assertEqual(c, before)
        self.assertIn('product_reference_meaning_mismatch', out['validation'])
        self.assertFalse(out['reply'])
        self.assertTrue(out['needs_operator'])

    def test_correct_literal_preserves_question_and_reports_server_provenance(self):
        p, task = self.ready()
        out = self.finish(p, self.candidate(task))
        self.assertEqual(out['validation'], [])
        self.assertTrue(out['reply'])
        source = out['context_review']['field_sources']['latest_client_meaning']
        self.assertEqual(source['kind'], 'server_literal_product_reference')
        self.assertFalse(source['independent_model_interpretation'])
        self.assertFalse(out['auto_enabled'])

    def test_model_can_still_reject_the_proposed_step(self):
        p, task = self.ready()
        c = self.candidate(task)
        c.update(reply='', needs_operator=True)
        c['context_review'].update(selected_step_fits=False, note='Нужна проверка оператора.')
        out = self.finish(p, c)
        self.assertEqual(out['action'], 'handoff')
        self.assertIn('model_context_mismatch', out['validation'])
        self.assertFalse(out['reply'])

    def test_prior_positive_instruction_fact_is_not_overwritten(self):
        self.h.ctx['messages'][2]['body'] = 'Схема есть, комплектующие все куплены'
        p, task = self.ready()
        self.assertEqual(p['qualification']['instructions']['status'], 'answered')
        self.assertIn('Схема есть', p['qualification']['instructions']['value'])
        self.assertIn('Схема есть', task['conversation'][2]['body'])
        self.assertFalse(self.finish(p, self.candidate(task))['validation'])

    def test_real_new_information_questions_negation_and_work_are_not_frozen(self):
        for text in ('Нашёл схему в интернете', 'Вот инструкция сборки',
                     'Это не он', 'Вот он в интернете?', 'Вот он, но нужно заменить зеркало',
                     'Вот другой предмет — стол', 'Завтра после 18', 'Вот номер мастера',
                     'Схемы нет, но нужно собрать завтра'):
            with self.subTest(text=text):
                timeline, rows = self.helper(body=text)
                self.assertIsNone(ext._product_reference_context(timeline, rows))

    def test_common_deictic_variants_retain_the_exact_quote(self):
        for text in ('Вот он', 'Вот вот интернете он', 'Вот такая на сайте',
                     'Вот такой же в каталоге', 'Нашла его в интернете'):
            with self.subTest(text=text):
                timeline, rows = self.helper(body=text)
                result = ext._product_reference_context(timeline, rows)
                self.assertEqual(result['quote'], text)
                self.assertIn('«'+text+'»', result['literal_meaning'])

    def test_voice_and_quoted_other_people_are_not_plain_references(self):
        for changes in (dict(body='Вот он', voice_transcript='Нужен ремонт шкафа'),
                        dict(body='«Вот он в интернете»'), dict(body='Мастер сказал вот он в интернете')):
            with self.subTest(changes=changes):
                timeline, rows = self.helper(**changes)
                self.assertIsNone(ext._product_reference_context(timeline, rows))

    def test_unreviewed_wrong_signature_and_wrong_identity_do_not_get_context(self):
        for mutation in ('unreviewed', 'signature', 'identity', 'source'):
            with self.subTest(mutation=mutation):
                timeline, rows = self.helper()
                picture = next(m for m in rows if m['id'] == 'image')
                if mutation == 'unreviewed': picture['unread_media'] = True
                if mutation == 'signature': picture['media_observation']['signature'] = 'other'
                if mutation == 'identity': picture['media_observation']['message_id'] = 'other'
                if mutation == 'source': picture['media_observation']['source'] = 'raw_browser'
                self.assertIsNone(ext._product_reference_context(timeline, rows))

    def test_other_image_types_and_specific_facts_are_not_hidden(self):
        for value in ({'content_kind':'assembly_diagram'}, {'content_kind':'document_image'},
                      {'content_kind':'product_photo', 'device_kind':'tv'},
                      {'content_kind':'device_label', 'model':'Canon G1411'}):
            with self.subTest(value=value):
                timeline, rows = self.helper()
                next(m for m in rows if m['id'] == 'image')['media_observation'].update(value)
                self.assertIsNone(ext._product_reference_context(timeline, rows))

    def test_intervening_staff_or_text_does_not_link_an_old_picture(self):
        for role in ('staff', 'client'):
            with self.subTest(role=role):
                timeline, rows = self.helper()
                timeline.insert(-1, dict(id='other', position=4, speaker_role=role,
                                        body='Другой вопрос', voice_transcript='', attachment_count=0))
                self.assertIsNone(ext._product_reference_context(timeline, rows))

    def test_duplicate_ids_do_not_get_guessed_evidence(self):
        for which in ('caption', 'image'):
            with self.subTest(which=which):
                timeline, rows = self.helper()
                timeline[0]['id'] = which
                self.assertIsNone(ext._product_reference_context(timeline, rows))

    def test_multiple_contiguous_reviewed_products_are_retained(self):
        picture = copy.deepcopy(self.h.ctx['messages'][-2])
        picture['id'] = 'image2'
        picture['attachments'][0]['media_id'] = 'synthetic-second-product170'
        self.h.ctx['messages'].insert(-1, picture)
        p, task = self.ready()
        self.assertEqual(task['product_reference_context']['image_evidence_ids'], ['image', 'image2'])
        self.assertFalse(self.finish(p, self.candidate(task))['validation'])

    def test_raw_browser_flags_and_fake_context_cannot_bypass_receipts(self):
        self.h.ctx['product_reference_context'] = {'literal_meaning':'Инструкция есть'}
        self.h.ctx['messages'][-2].update(media_reviewed=True, unread_media=False,
                                        media_observation={'source':'reviewed_image', 'content_kind':'product_card'})
        out = self.preview()
        self.assertTrue(out['media_review_required'])
        self.assertFalse(out.get('pending_model'))

    def test_changed_actual_image_invalidates_the_receipt(self):
        p, task = self.ready()
        self.assertFalse(self.finish(p, self.candidate(task))['validation'])
        self.h.ctx['messages'][-2]['attachments'][0]['url'] = 'https://example.test/changed170.jpg'
        out = self.preview()
        self.assertTrue(out['media_review_required'])
        self.assertFalse(out.get('pending_model'))

    def test_nonclient_latest_and_future_image_positions_are_not_linked(self):
        for change in ('actor', 'position'):
            with self.subTest(change=change):
                timeline, rows = self.helper()
                if change == 'actor': timeline[-1]['speaker_role'] = 'staff'
                else: timeline[-2]['position'] = timeline[-1]['position'] + 1
                self.assertIsNone(ext._product_reference_context(timeline, rows))

    def test_reference_is_not_truncated_to_fit_native_schema(self):
        timeline, rows = self.helper(body='Вот ' * 70 + 'он в интернете')
        self.assertIsNone(ext._product_reference_context(timeline, rows))


if __name__ == '__main__':
    unittest.main()
