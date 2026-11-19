"""Relevant photo-only instructions preserve source and the full safety contract."""
import copy
import json
import unittest

import extension_assistant as ext
import test_photo_work_clarification514 as fixture


class PhotoContext163Tests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.PhotoWorkClarificationTests('test_exact_reviewed_photo_gets_useful_work_question')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def ready(self, prior='Здравствуйте'):
        ctx = self.h.context(prior=prior)
        p = self.h.receipt(ctx, observations={'content_kind': 'other'})
        t, c = self.h.candidate(p)
        return ctx, p, t, c

    def test_bounded_instructions_keep_all_observed_messages_roles_and_rules(self):
        ctx, p, t, c = self.ready()
        self.assertNotIn('diagnostic_fee_terms', p['model_task']['system'])
        self.assertNotIn('adult_presence_condition', p['model_task']['system'])
        self.assertIn('photo_work_review', p['model_task']['system'])
        self.assertEqual(len(t['conversation']), len(ctx['messages']))
        self.assertEqual([m['id'] for m in t['conversation']], [m['id'] for m in ctx['messages']])
        self.assertEqual([m['body'] for m in t['conversation']], [m['body'] for m in ctx['messages']])
        self.assertEqual([m['speaker_role'] for m in t['conversation']], ['client', 'staff', 'client'])
        self.assertIn('DOC-L0700', [v['id'] for v in t['primary_sources']])
        self.assertFalse(p['model_context_coverage']['truncated'])
        o = self.h.finish(p, c)
        self.assertFalse(o['validation'])
        self.assertIn('Что требуется сделать?', o['reply'])
        self.assertFalse(o['auto_enabled'])

    def test_the_full_native_schema_including_reply_enum_and_source_proof_is_preserved(self):
        ctx, p, t, c = self.ready()
        schema = p['model_task']['response_format']
        self.assertEqual(schema, ext._structured_response_format(t))
        self.assertTrue(schema['strict'])
        self.assertEqual(schema['schema']['properties']['reply']['enum'], ['', 'Что требуется сделать?'])
        review = schema['schema']['properties']['context_review']
        self.assertEqual(set(review['required']), set(t['output_contract']['context_review_fields']))
        self.assertEqual(len(review['properties']['photo_work_review']['required']), 6)
        self.assertEqual(review['properties']['photo_work_review']['properties']['future_messages_used']['enum'], [False])
        self.assertNotIn('enum', review['properties']['last_intent'])
        self.assertNotIn('enum', review['properties']['latest_client_meaning'])
        self.assertEqual(p['model_task']['max_tokens'], 1100)

    def test_bounded_wording_does_not_accept_an_invented_subject_or_work(self):
        for field, text, violation in [
                ('latest_client_meaning', 'На фото шкаф, работа пока неизвестна.', 'photo_subject_not_observed'),
                ('last_intent', 'Клиент хочет ремонт шкафа.', 'photo_unstated_work_or_diagnosis')]:
            with self.subTest(field=field):
                ctx, p, t, c = self.ready()
                c['context_review'][field] = text
                o = self.h.finish(p, c)
                self.assertIn(violation, o['validation'])
                self.assertEqual(o['reply'], '')
                self.assertTrue(o['needs_operator'])

    def test_an_observed_repeated_question_keeps_the_models_handoff_choice(self):
        ctx, p, t, c = self.ready(prior='Что требуется сделать?')
        c.update(reply='', needs_operator=True)
        c['context_review'].update(selected_step_fits=False,
            note='Этот вопрос уже задавался, новая фотография не прояснила требуемую работу.')
        o = self.h.finish(p, c)
        self.assertEqual(o['action'], 'handoff')
        self.assertFalse(o['reply'])
        self.assertFalse(o['lead']['can_create_automatically'])

    def test_special_conditions_fixed_replies_and_named_jobs_keep_the_existing_system(self):
        ctx, p, t, c = self.ready()
        for field in ('adult_presence_review', 'diagnostic_fee_review', 'background_work_review', 'future_special_review'):
            with self.subTest(field=field):
                task = copy.deepcopy(t)
                task['output_contract']['context_review_fields'].append(field)
                before = json.dumps(task, sort_keys=True)
                self.assertIsNone(ext._photo_only_context_system(task))
                self.assertEqual(json.dumps(task, sort_keys=True), before)
        task = copy.deepcopy(t)
        task['fixed_reply'] = 'Проверяемый фиксированный ответ'
        self.assertIsNone(ext._photo_only_context_system(task))
        p = self.h.receipt(self.h.context('Нужно поменять провода и собрать в распаячную коробку'),
                           observations={'content_kind': 'other'})
        t = json.loads(p['model_task']['task'])
        self.assertNotIn('photo_work_clarification', t)
        self.assertIsNone(ext._photo_only_context_system(t))
        self.assertEqual(t['decision']['next_question']['question'], 'Где расположен щиток или автомат?')


if __name__ == '__main__':
    unittest.main()
