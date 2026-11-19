import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assistant_store import Store
from experienced_dialogues import create_index
from extension_assistant import Assistant, _context_review
from test_assistant import context, message


class ExperienceAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'experience-a.sqlite3'
        self.archive(self.db, 'Схема сборки есть?')
        self.env = patch.dict(os.environ, {'LEADBOT_PERSONAL_OWNER_ID': 'owner',
                                          'LEADBOT_EXPERIENCED_DB': str(self.db),
                                          'LEADBOT_EXPERIENCE_REQUIRED': '1'})
        self.env.start()
        self.app = Assistant(Store(self.root / 'assistant.sqlite3'))

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def archive(self, path, reply, cid='historical-source'):
        record = dict(cid=cid, case=1, client_group='other-group', direction='mnc',
                      metadata={'item_title': 'Сборка мебели', 'experienced_authors': ['Мамонтов Георгий']},
                      review_flags={'text_reviewed': True, 'media_reviewed': True}, messages=[
                          dict(id='old-client', direction='in', sender_type='client', text='Нужно собрать шкаф'),
                          dict(id='old-staff', direction='out', sender_type='operator', author='Мамонтов Георгий',
                               delivery='delivered', text=reply)])
        create_index(path, [record], approved_cids=[cid])

    def preview(self, **extra):
        ctx = context([message('Нужно собрать шкаф', mid='current-client')], convId='current',
                      dir='mnc', itemTitle='Сборка мебели', accountTitle='Денис МНЧ')
        ctx.update(extra)
        out, status = self.app.handle(dict(owner='owner', action='preview', ctx=ctx, wording_mode='neural_review'))
        self.assertEqual(status, 200)
        return out

    def test_real_model_task_contains_relevant_staff_experience_before_provider(self):
        out = self.preview()
        self.assertTrue(out['pending_model'])
        task = json.loads(out['model_task']['task'])
        self.assertEqual(task['experience_context']['examples'][0]['staff_question'], 'Схема сборки есть?')
        self.assertEqual(task['style_examples'][0]['answer'], 'Схема сборки есть?')
        self.assertEqual([m['id'] for m in task['conversation']], ['current-client'])
        self.assertIn('исторические примеры', out['model_task']['system'])

    def test_current_case_is_never_its_own_teacher(self):
        out = self.preview(convId='historical-source')
        self.assertEqual(out['experience_context']['examples'], [])

    def test_historical_storage_wrapper_does_not_turn_own_source_into_an_independent_example(self):
        cid = '00000000-0000-0000-0000-000000000204'
        archive = self.root / 'wrapped.sqlite3'
        self.archive(archive, 'Схема сборки есть?', cid=cid)
        os.environ['LEADBOT_EXPERIENCED_DB'] = str(archive)
        out = self.preview(convId='historical-root-' + cid)
        self.assertEqual(out['experience_context']['examples'], [])

    def complete_question(self, reply):
        prepared = self.preview()
        return self.app.handle(dict(owner='owner', action='finalize', request_id=prepared['request_id'],
            revision=prepared['revision'], candidate=dict(reply=reply, needs_operator=False,
                context_review=dict(last_intent='Сборка шкафа', latest_client_meaning='Нужно собрать шкаф',
                    selected_step_fits=True, evidence_ids=['current-client'], note='Схема ещё не известна'))))[0]

    def test_reviewed_natural_model_question_is_preserved_instead_of_template_copy(self):
        out = self.complete_question('Подскажите, схема сборки есть?')
        self.assertEqual(out['validation'], [])
        self.assertEqual(out['reply'], 'Здравствуйте! Подскажите, схема сборки есть?')
        self.assertEqual(out['response_source'], 'model')
        self.assertNotEqual(out.get('model_status'), 'unreviewed_wording')

    def test_experience_does_not_allow_invented_rooms_in_a_paraphrase(self):
        out = self.complete_question('Схема сборки шкафа в спальне есть?')
        self.assertNotIn('спальн', out['reply'])
        self.assertEqual(out['response_source'], 'server_template')
        self.assertEqual(out['model_status'], 'unreviewed_wording')

    def test_required_missing_source_stops_before_model_instead_of_silent_template_fallback(self):
        os.environ['LEADBOT_EXPERIENCED_DB'] = str(self.root / 'missing.sqlite3')
        out = self.preview()
        self.assertFalse(out['ok'])
        self.assertEqual(out['code'], 'experience_unavailable')
        self.assertEqual(out['reply'], '')
        self.assertNotIn('model_task', out)
        self.assertFalse((self.root / 'missing.sqlite3').exists())

    def test_verified_new_archive_changes_learning_version_and_cache_identity_automatically(self):
        first = self.preview()
        ended, status = self.app.handle(dict(owner='owner', action='finalize',
            request_id=first['request_id'], revision=first['revision'],
            candidate=dict(reply='', needs_operator=True, context_review=dict(
                last_intent='Сборка шкафа', latest_client_meaning='Нужно собрать шкаф',
                selected_step_fits=False, evidence_ids=['current-client'], note='Нужна проверка оператора'))))
        self.assertEqual(status, 200)
        self.assertEqual(ended['context_review_status'], 'provided')
        self.assertTrue(ended['needs_operator'])
        replacement = self.root / 'experience-b.sqlite3'
        self.archive(replacement, 'Подскажите, схема сборки есть?')
        os.environ['LEADBOT_EXPERIENCED_DB'] = str(replacement)
        second = self.preview()
        self.assertNotEqual(first['experience_context']['version'], second['experience_context']['version'])
        self.assertNotEqual(first['request_id'], second['request_id'])
        self.assertFalse(second.get('cached', False))

    def review(self, **extra):
        candidate = dict(context_review=dict(last_intent='Сборка шкафа', latest_client_meaning='Нужно собрать шкаф',
                                             selected_step_fits=False, evidence_ids=['current-client'], note='Шаг не подходит'),
                         reply='', needs_operator=True)
        candidate['context_review'].update(extra)
        task = dict(context_review_version=2, conversation=[dict(id='current-client', review_ref='context-position:0')],
                    latest_client_message=dict(id='current-client', position=0, evidence_id='current-client',
                                               body='Нужно собрать шкаф'),
                    experience_context=dict(examples=[dict(case_id='historical-source')]))
        return _context_review(candidate, task)

    def test_experience_does_not_remove_independent_semantic_veto(self):
        _, status, errors = self.review()
        self.assertEqual(status, 'provided')
        self.assertEqual(errors, ['model_context_mismatch'])

    def test_historical_case_id_cannot_leak_into_current_intent_or_evidence(self):
        _, status, errors = self.review(last_intent='Сборка из historical-source')
        self.assertEqual(status, 'inconsistent')
        self.assertIn('historical_experience_identity_leak', errors)
        _, status, errors = self.review(evidence_ids=['historical-source'])
        self.assertEqual(status, 'invalid')
