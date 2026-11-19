"""Bounded control diagnostics distinguish stages without weakening gates."""
import json
import unittest
from unittest.mock import patch
import test_research_control214 as fixtures
from research_jobs import JobError


class ControlDiagnostic237Tests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.Admission214Tests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def last(self):
        with self.f.app.store.connect() as db:
            row = db.execute("select payload from workflow_audit where kind='research_control_stopped' order by id desc limit 1").fetchone()
        self.assertIsNotNone(row)
        return json.loads(row['payload'])

    def test_unknown_job_has_a_distinct_safe_code_and_original_action(self):
        out, code = self.f.call('research_status', research_job_id='f'*32)
        self.assertEqual(code, 403)
        event = self.last()
        self.assertEqual(event['stage'], 'job_lookup')
        self.assertEqual(event['action'], 'research_status')
        self.assertEqual(event['check'], 'unknown_scoped_job')
        self.assertTrue(event['supplied_job'])
        self.assertFalse(event['known_job'])
        self.assertEqual(self.f.requests, [])

    def test_missing_unsubmitted_cancel_is_not_mislabeled_as_job_lookup(self):
        out, code = self.f.call('research_cancel')
        self.assertEqual(code, 403)
        self.assertEqual(out['failure_stage'], 'pending_cancel')
        event = self.last()
        self.assertEqual(event['action'], 'research_cancel')
        self.assertEqual(event['check'], 'pending_observer_missing')
        self.assertFalse(event['supplied_job'])
        self.assertEqual(self.f.requests, [])

    def test_expired_pending_cancel_stays_strict_without_a_paid_retry(self):
        self.f.pending()
        now = self.f.service.jobs.clock()+60
        with patch.object(self.f.service.jobs, 'clock', return_value=now):
            self.assertEqual(self.f.service.pending_metadata(), [])
            self.f.identity.update(iat=int(now), exp=int(now)+40)
            out, code = self.f.call('research_cancel')
        self.assertEqual(code, 403)
        self.assertEqual(self.last()['check'], 'pending_observer_missing')
        self.assertEqual(self.f.requests, [])
        self.assertEqual(self.f.work, [])

    def test_wrong_preview_revision_is_identified_without_any_prompt_or_body(self):
        out, code = self.f.call('research_status', revision='different-revision')
        self.assertEqual(code, 403)
        event = self.last()
        self.assertEqual(event['check'], 'preview_not_current')
        self.assertEqual(event['action'], 'research_status')
        self.assertNotIn('Нужно повесить полку', json.dumps(event, ensure_ascii=False))
        self.assertNotIn(self.f.body['identity_proof'], json.dumps(event))

    def test_manual_hold_is_identified_and_not_converted_to_a_refresh(self):
        self.f.app.store.observe(self.f.scope, self.f.ctx['convId'], self.f.prepared['revision'], takeover=True)
        out, code = self.f.call('research_start')
        self.assertEqual(code, 403)
        self.assertEqual(self.last()['check'], 'conversation_held')
        self.assertNotIn('refresh_preview', out)
        self.assertEqual(self.f.requests, [])

    def test_unknown_action_is_not_copied_into_the_diagnostic(self):
        sentinel = 'private-action-marker-do-not-log'
        # The public Assistant correctly rejects unsupported actions earlier
        # with400. Exercise the already-authenticated control entry itself.
        out, code = self.f.service.handle(self.f.app, dict(self.f.body, action=sentinel))
        self.assertEqual(code, 403)
        event = self.last()
        self.assertEqual(event['action'], 'unsupported')
        self.assertNotIn(sentinel, json.dumps(event))

    def test_rejection_before_action_parsing_still_logs_only_safe_metadata(self):
        out, code = self.f.service.handle(self.f.app, dict(self.f.body,
                          action='research_start', unexpected='private-unaccepted-field'))
        self.assertEqual(code, 403)
        event = self.last()
        self.assertEqual(event['stage'], 'observer_contract')
        self.assertNotIn('private-unaccepted-field', json.dumps(event))

    def test_unknown_exception_check_or_message_cannot_enter_audit(self):
        private = 'private-exception-and-check'
        with patch.object(self.f.service, '_context', side_effect=JobError(private)) as mocked:
            out, code = self.f.call('research_start')
        self.assertEqual(code, 403)
        event = self.last()
        self.assertIsNone(event['check'])
        self.assertNotIn(private, json.dumps(event))
        self.assertNotIn(private, json.dumps(out))
