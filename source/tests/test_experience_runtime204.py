import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

import assistant_policy as policy
from assistant_store import Store
from experienced_dialogues import create_index
from experience_memory import CHECKS, NEGATIVE_CHECKS, Memory, digest
import experience_runtime
from extension_assistant import Assistant
from test_assistant import context, message

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from publish_experience import publish


class ExperienceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.archive = self.folder / 'source.sqlite3'
        create_index(self.archive, [dict(cid='old-case', case=1, client_group='a'*64, direction='mnc',
            metadata={'experienced_authors': ['Опытный сотрудник']},
            review_flags=dict(text_reviewed=True, media_reviewed=True), messages=[
                dict(id='old-in', direction='in', sender_type='client', text='Нужно собрать шкаф'),
                dict(id='old-out', direction='out', sender_type='operator', author='Опытный сотрудник',
                     delivery='delivered', text='Схема сборки есть?')])], approved_cids=['old-case'])
        self.lessons = self.folder / 'source-lessons.json'
        self.reviews = self.folder / 'source-reviews.json'
        self.row = dict(id='photo-progress', case_id='other-case', client_group='b'*64,
            direction='mnc', stage='intake', source_sha256=hashlib.sha256(b'full guarded source').hexdigest(),
            situation='Сборка шкафа. Клиент обещает фото.', action='Ждать обещанное фото.',
            boundary='Обещание не доказывает получение изображения или наличие инструкции.')
        self.write()
        self.env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner',
            LEADBOT_EXPERIENCED_DB=str(self.archive), LEADBOT_EXPERIENCE_CATALOG=str(self.lessons),
            LEADBOT_EXPERIENCE_REVIEWS=str(self.reviews), LEADBOT_EXPERIENCE_REQUIRED='1')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = Assistant(Store(self.folder / 'assistant.sqlite3'))
        self.ctx = context([message('Нужно собрать шкаф', mid='current')], convId='current-case', dir='mnc',
                           itemTitle='Сборка мебели', accountTitle='Мастер МНЧ')

    def write(self, *, revoked=False, row=None):
        row = row or self.row
        self.lessons.write_text(json.dumps(dict(schema=1, records=[row]), ensure_ascii=False))
        self.reviews.write_text(json.dumps(dict(schema=1, reviews={} if revoked else {
            row['id']: dict(content_sha256=digest(row), policy=policy.VERSION,
                            source_kind='reviewed_staff_case', **dict.fromkeys(CHECKS, True))}), ensure_ascii=False))

    def preview(self):
        return self.app.handle(dict(owner='owner', action='preview', ctx=self.ctx, wording_mode='neural_review'))[0]

    def finalize(self, prepared):
        task = json.loads(prepared['model_task']['task'])
        return self.app.handle(dict(owner='owner', action='finalize', request_id=prepared['request_id'],
            revision=prepared['revision'], candidate=dict(reply=task['decision']['next_question']['question'],
            needs_operator=False, context_review=dict(last_intent='Сборка шкафа', latest_client_meaning='Нужно собрать шкаф',
                selected_step_fits=True, evidence_ids=['current'], note='Схема ещё не названа'))))[0]

    def test_structured_reason_and_boundary_reach_actual_model_task_separately_from_phrasing(self):
        prepared = self.preview()
        task = json.loads(prepared['model_task']['task'])
        lesson = task['experience_context']['lessons'][0]
        self.assertEqual(lesson, self.row)
        self.assertEqual(task['conversation'][0]['id'], 'current')
        self.assertNotIn('old-in', json.dumps(task['conversation']))

    def test_historical_wrapper_cannot_retrieve_its_own_reviewed_lesson(self):
        cid = '00000000-0000-0000-0000-000000000204'
        self.write(row=dict(self.row, case_id=cid))
        self.ctx['convId'] = 'historical-root-' + cid
        task = json.loads(self.preview()['model_task']['task'])
        self.assertEqual(task['experience_context']['lessons'], [])

    def test_revocation_after_generation_stops_finalize_without_rewriting_candidate(self):
        prepared = self.preview()
        self.write(revoked=True)
        result = self.finalize(prepared)
        self.assertEqual(result['reply'], '')
        self.assertEqual(result['validation'], ['experience_changed'])
        self.assertTrue(result['needs_operator'])

    def test_revocation_after_finalize_invalidates_existing_draft_before_send(self):
        draft = self.finalize(self.preview())
        self.assertTrue(draft['reply'])
        self.assertEqual(draft['validation'], [])
        validate = lambda: self.app.handle(dict(owner='owner', action='validate', ctx=self.ctx, draft_id=draft['draft_id']))[0]
        self.assertTrue(validate()['ok'])
        self.write(revoked=True)
        self.assertFalse(validate()['ok'])

    def test_done_request_cache_cannot_return_a_revoked_answer_on_finalize(self):
        prepared = self.preview()
        self.assertTrue(self.finalize(prepared)['reply'])
        self.write(revoked=True)
        result = self.finalize(prepared)
        self.assertEqual(result['reply'], '')
        self.assertEqual(result['code'], 'experience_changed')
        self.assertTrue(result['needs_operator'])

    def test_new_verified_lesson_is_loaded_on_next_prepare_without_restart(self):
        first = self.preview()
        self.finalize(first)
        changed = dict(self.row, boundary='Не выводить наличие схемы из обещанного фото шкафа.')
        self.write(row=changed)
        second = self.preview()
        self.assertNotEqual(first['experience_binding'], second['experience_binding'])
        self.assertNotEqual(first['request_id'], second['request_id'])
        self.assertEqual(second['experience_context']['lessons'][0]['boundary'], changed['boundary'])

    def test_customer_or_model_cannot_edit_approved_knowledge(self):
        self.lessons.write_text(json.dumps(dict(schema=1, records=[dict(self.row, action='Обещать ремонт')]), ensure_ascii=False))
        result = self.preview()
        self.assertEqual(result['experience_context']['lessons'], [])
        self.assertTrue(result['pending_model'])

    def test_verified_negative_teaches_boundary_without_claiming_completed_bot_case(self):
        memory = Memory(self.folder / 'negative.sqlite3')
        receipt = dict(content_sha256=digest(self.row), policy=policy.VERSION,
                       source_kind='root_reviewed_negative', **dict.fromkeys(NEGATIVE_CHECKS, True))
        self.assertNotIn('experienced_staff', receipt)
        self.assertNotIn('bot_case_closed', receipt)
        result = memory.refresh([self.row], {self.row['id']: receipt}, policy.VERSION)
        self.assertEqual(result['active'], 1)
        for check in NEGATIVE_CHECKS:
            with self.subTest(check=check):
                altered = dict(receipt, **{check: False})
                self.assertEqual(memory.refresh([self.row], {self.row['id']: altered}, policy.VERSION)['active'], 0)

    def test_atomic_publication_preserves_previous_pointer_on_failure(self):
        live = self.folder / 'live'
        result = publish(live, self.archive, self.lessons, self.reviews, policy.VERSION)
        pointer = Path(result['pointer'])
        original = pointer.read_bytes()
        self.write(revoked=True)
        with patch('publish_experience.os.replace', side_effect=OSError('synthetic publication failure')):
            with self.assertRaises(OSError):
                publish(live, self.archive, self.lessons, self.reviews, policy.VERSION)
        self.assertEqual(pointer.read_bytes(), original)
        experience_runtime.pointer_files(pointer)

    def test_published_snapshot_hash_change_stops_instead_of_reverting(self):
        live = self.folder / 'live'
        result = publish(live, self.archive, self.lessons, self.reviews, policy.VERSION)
        os.environ['LEADBOT_EXPERIENCE_POINTER'] = result['pointer']
        self.assertTrue(self.preview()['pending_model'])
        pointer = json.loads(Path(result['pointer']).read_text())
        (live / pointer['lessons']).write_text('{}')
        denied = self.preview()
        self.assertEqual(denied['code'], 'experience_unavailable')
        self.assertNotIn('model_task', denied)

    def test_pointer_cannot_reference_an_arbitrary_path(self):
        live = self.folder / 'live'
        result = publish(live, self.archive, self.lessons, self.reviews, policy.VERSION)
        pointer = Path(result['pointer'])
        data = json.loads(pointer.read_text())
        data['archive'] = '../source.sqlite3'
        pointer.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            experience_runtime.pointer_files(pointer)

    def test_reply_authorization_rechecks_memory_even_if_browser_skips_validate(self):
        from test_workflow import WorkflowTests
        harness = WorkflowTests()
        harness.setUp()
        self.addCleanup(harness.tearDown)
        ctx = harness.ctx()
        with patch.dict(os.environ, LEADBOT_PERSONAL_AUTO_AVAILABLE='1'):
            draft = harness.neural_draft(ctx)
            self.assertTrue(draft['reply'])
            plan = harness.call('personal_plan', ctx=ctx)
            lease = harness.call('personal_status')
            self.write(revoked=True)
            result = harness.call('personal_review_authorize', ctx=ctx, confirmed=True,
                activation_nonce=lease['activation_nonce'], policy_ack=lease['policy_version'], client_version='2.8.19',
                operation=dict(kind='reply', operation_id=plan['operation_id'], revision=plan['revision'],
                               draft_id=draft['draft_id'], reply=draft['reply']))
            self.assertFalse(result['ok'])
            self.assertEqual(result['code'], 'experience_changed')
