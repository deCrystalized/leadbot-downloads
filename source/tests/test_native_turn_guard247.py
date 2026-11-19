"""No new paid turn from a new release. Entirely synthetic sources/transport."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch

import assistant_policy as policy
import test_native_startup240 as fixtures
from research_workflow import ResearchService


class NativeTurnGuard247Tests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.NativeStartup240Tests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def failed_original(self):
        f = self.f
        f.preview()
        f.sim.provider_mode = 'transport'
        out, code = f.call('research_start')
        self.assertEqual(code, 200, out)
        f.workers()
        self.assertEqual(len(f.sim.requests), 1)
        self.original = copy.deepcopy(f.app.research.jobs.status(f.body['owner'], out['research_job_id']))
        return out['research_job_id']

    def new_preview(self):
        f = self.f
        # Only end the exact fixture's UI preview lease, representing the
        # old view closing/its 90s resource lease expiring. The original job,
        # grant, call allowance, unknown result and deadline are untouched.
        if f.body.get('request_id'):
            from assistant_store import digest
            f.app.store.release_dialog('assistant:' + digest(f.body['owner']),
                f.ctx['convId'], f.body['request_id'])
        f.run_id = str(uuid.uuid4())
        f.body['native_run']['run_id'] = f.run_id
        f.body.pop('request_id', None)
        f.body.pop('revision', None)
        return f.preview()

    def test_policy_only_new_run_cannot_regenerate_stopped_original(self):
        f = self.f
        job = self.failed_original()
        with patch.object(policy, 'VERSION', policy.VERSION + '.synthetic-next-release'):
            self.new_preview()
            out, code = f.call('research_start')
            self.assertEqual(code, 403, out)
            self.assertEqual(out.get('code'), 'research_prior_attempt', out)
        after = f.app.research.jobs.status(f.body['owner'], job)
        self.assertEqual(after, self.original)
        with f.app.research.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM grants').fetchone()[0], 1)
        self.assertEqual(len(f.sim.requests), 1)

    def test_legacy_unindexed_grant_uses_exact_original_across_policy_change(self):
        f = self.f
        job = self.failed_original()
        with f.app.research.jobs.connect() as db:
            db.execute('DELETE FROM auto_source_turns')  # Actual older schema content.
        with patch.object(policy, 'VERSION', policy.VERSION + '.synthetic-legacy-cutover'):
            self.new_preview()
            out, code = f.call('research_start')
        self.assertEqual((code, out.get('code')), (403, 'research_prior_attempt'))
        self.assertEqual(f.app.research.jobs.status(f.body['owner'], job), self.original)

    def test_missing_legacy_original_does_not_fall_back_to_preview_or_regenerate(self):
        f = self.f
        job = self.failed_original()
        f.app.research.jobs._file(job, 'input.json').unlink()
        with f.app.research.jobs.connect() as db:
            db.execute('DELETE FROM auto_source_turns')
        with patch.object(policy, 'VERSION', policy.VERSION + '.synthetic-missing-original'):
            self.new_preview()
            out, code = f.call('research_start')
        self.assertEqual((code, out.get('code')), (403, 'research_prior_attempt'))
        self.assertEqual(len(f.sim.requests), 1)

    def test_system_event_or_ui_location_is_not_a_new_client_turn(self):
        f = self.f
        self.failed_original()
        for change in ('system', 'UI-only'):
            with self.subTest(change=change):
                if change == 'system':
                    f.ctx['messages'].append(dict(id='synthetic-system', direction='system',
                        sender_type='system', body='Статус диалога изменён'))
                    f.sim.sync(f.ctx['convId'])
                else:
                    f.ctx['latitude'] = 44.0
                self.new_preview()
                out, code = f.call('research_start')
                self.assertEqual((code, out.get('code')), (403, 'research_prior_attempt'))
        self.assertEqual(len(f.sim.requests), 1)

    def test_actual_new_client_message_has_its_own_finite_attempt(self):
        f = self.f
        job = self.failed_original()
        f.ctx['messages'].append(dict(id='synthetic-new-client', direction='in',
            sender_type='client', body='Стена бетонная.'))
        f.sim.sync(f.ctx['convId'])
        self.new_preview()
        out, code = f.call('research_start')
        self.assertEqual(code, 200, out)
        self.assertNotEqual(out['research_job_id'], job)
        self.assertEqual(len(f.sim.requests), 1)  # No worker invocation/retry here.
        self.assertEqual(f.app.research.jobs.status(f.body['owner'], job), self.original)

    def test_source_turn_reservation_survives_crash_before_grant_and_new_release(self):
        f = self.f
        f.preview()
        with patch.object(f.app.research.jobs, 'admit', side_effect=OSError('Synthetic pre-grant crash')):
            f.call('research_start')
        with f.app.research.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM auto_source_turns').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM grants').fetchone()[0], 0)
        with patch.object(policy, 'VERSION', policy.VERSION + '.synthetic-after-crash'):
            self.new_preview()
            out, code = f.call('research_start')
        self.assertEqual((code, out.get('code')), (403, 'research_prior_attempt'))
        self.assertEqual(f.sim.requests, [])

    def test_unknown_opaque_legacy_reservation_cannot_refill_after_release_change(self):
        f = self.f
        f.preview()
        with patch.object(f.app.research.jobs, 'admit', side_effect=OSError('Synthetic old crash')):
            f.call('research_start')
        with f.app.research.jobs.connect() as db:
            db.execute('DELETE FROM auto_source_turns')
        with patch.object(policy, 'VERSION', policy.VERSION + '.synthetic-opaque'):
            self.new_preview()
            out, code = f.call('research_start')
        self.assertEqual((code, out.get('code')), (403, 'research_prior_attempt'))
        self.assertEqual(f.sim.requests, [])

    def test_turn_excludes_derived_annotations_dates_and_includes_same_id_ASR(self):
        f = self.f
        f.preview()
        payload = f.app.research._prepared(f.app, f.body)
        original = ResearchService._source_turn(payload)
        task = json.loads(payload['model_task']['task'])
        row = task['conversation'][0]
        row.update(created_at='synthetic-other-rendered-date', position=12,
                   source_roles={'derived': 'changed-policy-annotation'})
        payload['model_task']['task'] = json.dumps(task)
        self.assertEqual(ResearchService._source_turn(payload), original)
        row.update(voice_transcript='Полку нужно повесить на бетон.', voice_transcript_status='done')
        payload['model_task']['task'] = json.dumps(task)
        self.assertNotEqual(ResearchService._source_turn(payload), original)

    def test_missing_original_client_ids_is_not_proof_of_a_new_turn(self):
        f = self.f
        f.preview()
        payload = f.app.research._prepared(f.app, f.body)
        task = json.loads(payload['model_task']['task'])
        task['conversation'][0]['id'] = ''
        payload['model_task']['task'] = json.dumps(task)
        with self.assertRaises(ValueError):
            ResearchService._source_turn(payload)


if __name__ == '__main__':
    unittest.main()
