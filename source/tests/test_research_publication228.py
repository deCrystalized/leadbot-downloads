import json
import uuid
import unittest

import test_native_exporter212 as exporter_fixture
from research_jobs import Jobs, JobError


class Publication228Tests(unittest.TestCase):
    def setUp(self):
        exporter_fixture.ExporterTests.setUp(self)
        self.now = float(self.now)
        self.binding = dict(owner='owner', request='one', chat='chat', revision='r1',
            principal='admin', operator='operator', policy='p', memory='m', map='map',
            task='task', profile='sol_only')
        self.jobs = Jobs(self.directory/'jobs', shared_lock=self.lock, clock=lambda:self.now)
        self.grant = self.jobs.admit(self.binding, max_calls=2, seconds=300)
        self.job = self.jobs.submit(self.binding, self.grant)['job_id']

    def candidate(self):
        return self.jobs.propose(self.job, self.binding,
            dict(approved=True, candidate=dict(reply='Вопрос о стене.', needs_operator=False)),
            fresh=lambda:self.binding)

    def blocked(self):
        value = self.exporter.run(max_cases=20)
        self.assertTrue(value.get('waiting_for_model_lock'), value)
        self.assertEqual(self.index.state()['records'], 0)

    def published(self):
        exporter_fixture.ExporterTests.finish(self)
        self.assertEqual(self.index.state()['records'], 2)

    def test_awaiting_manual_review_defers_publication_after_worker_lock_released(self):
        with self.jobs.session_worker(self.job):
            self.candidate()
        self.assertFalse(self.jobs.worker_present(self.job))
        self.assertEqual(self.jobs.status('owner', self.job)['state'], 'awaiting_root')
        self.blocked()

    def test_queued_admission_survives_process_restart_without_a_new_call(self):
        restored = Jobs(self.directory/'jobs', shared_lock=self.lock, clock=lambda:self.now)
        self.assertEqual(restored.submit(self.binding, self.grant)['job_id'], self.job)
        self.blocked()
        self.assertEqual(restored.status('owner', self.job)['calls_spent'], 0)

    def test_root_acceptance_keeps_hold_until_final_result_is_durable(self):
        result = self.candidate()
        self.jobs.decide(self.job, result['result_sha256'], accepted=True, reviewer='root')
        self.blocked()
        def finish(candidate):
            self.blocked()
            return dict(reply='Вопрос о стене.', validation=[])
        self.jobs.finalize(self.job, self.binding, fresh=lambda:self.binding, finish=finish)
        self.published()

    def test_unknown_finalize_remains_held_without_repeating_finish(self):
        result = self.candidate()
        self.jobs.decide(self.job, result['result_sha256'], accepted=True, reviewer='root')
        def lost(candidate):
            raise SystemExit('simulated interruption after finalize began')
        with self.assertRaises(SystemExit):
            self.jobs.finalize(self.job, self.binding, fresh=lambda:self.binding, finish=lost)
        self.assertEqual(self.jobs.status('owner', self.job)['state'], 'finalizing')
        self.blocked()
        self.jobs.reconcile(self.job, self.binding, fresh=lambda:self.binding,
            read=lambda:dict(done=True, result=dict(reply='saved')))
        self.published()

    def test_cancel_denial_and_stop_release_only_terminal_job(self):
        for operation in ('cancel', 'stop', 'stop_series', 'denial'):
            with self.subTest(operation=operation):
                binding = dict(self.binding, request=operation)
                grant = self.jobs.admit(binding, max_calls=2, seconds=300)
                job = self.jobs.submit(binding, grant)['job_id']
                if operation == 'denial':
                    receipt = self.jobs.propose(job, binding, dict(approved=True), fresh=lambda:binding)
                    self.jobs.decide(job, receipt['result_sha256'], accepted=False, reviewer='root')
                elif operation == 'stop_series':
                    self.jobs.stop_series('owner')
                else:
                    getattr(self.jobs, operation)('owner', job)
                self.assertNotIn(job, self.jobs.holds.active_jobs())
        self.jobs.stop('owner', self.job)
        self.published()

    def test_one_terminal_job_does_not_release_another_current_admission(self):
        other = dict(self.binding, owner='other', request='two')
        grant = self.jobs.admit(other, max_calls=1, seconds=300)
        job = self.jobs.submit(other, grant)['job_id']
        self.jobs.stop('owner', self.job)
        self.blocked()
        self.jobs.cancel('other', job)
        self.published()

    def test_original_deadline_expires_hold_without_observer_or_extra_generation(self):
        self.candidate()
        self.blocked()
        self.now += 301
        self.published()
        with self.assertRaises(JobError):
            self.jobs.requester(self.job, self.binding, fresh=lambda:self.binding,
                request=lambda *args:self.fail('No paid retry'))({}, 10)
        self.assertEqual(self.jobs.status('owner', self.job)['calls_spent'], 0)

    def test_missing_or_changed_hold_prevents_provider_before_network(self):
        path = self.jobs.holds.path(self.job)
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(JobError):
            self.candidate()
        path.write_bytes(original);path.chmod(0o600)
        value = json.loads(original);value['binding_sha256'] = '0'*64
        path.write_text(json.dumps(value))
        with self.assertRaises(JobError):
            self.candidate()

    def test_corrupt_or_symlink_hold_fails_closed_in_publication(self):
        path = self.jobs.holds.path(self.job)
        original = path.read_bytes()
        path.write_bytes(b'not json')
        with self.assertRaises(ValueError):
            self.jobs.holds.active_jobs()
        path.unlink();target=self.directory/'target';target.write_bytes(original);target.chmod(0o600)
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.jobs.holds.active_jobs()

    def test_private_metadata_contains_no_body_proof_credential_or_owner(self):
        path=self.jobs.holds.path(self.job)
        value=json.loads(path.read_bytes())
        self.assertEqual(set(value), {'schema','job','jobs_database','binding_sha256','issued','deadline'})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn('owner',value)
        path.chmod(0o644)
        with self.assertRaises(ValueError):self.jobs.holds.active_jobs()

    def test_partial_commit_orphan_holds_only_until_its_original_deadline(self):
        orphan=uuid.uuid4().hex
        self.jobs.holds.reserve(orphan, 'a'*64, self.now+20)
        self.jobs.stop('owner',self.job)
        self.assertEqual(self.jobs.holds.active_jobs(),[orphan])
        self.now+=21
        self.assertEqual(self.jobs.holds.active_jobs(),[])
        self.published()

    def test_poisoned_metadata_latches_exporter_without_publishing_prepared_source(self):
        self.jobs.holds.path(self.job).write_bytes(b'{"schema":1,"schema":2}')
        with self.assertRaises(ValueError):self.exporter.run(max_cases=20)
        self.assertEqual(self.index.state()['records'],0)
        self.assertIsNotNone(self.exporter.state()['error'])

    def test_broken_symlink_admission_directory_is_not_absence_of_active_jobs(self):
        path=self.jobs.holds.path(self.job)
        path.unlink();path.parent.rmdir();path.parent.symlink_to(self.directory/'missing',target_is_directory=True)
        with self.assertRaises(ValueError):self.jobs.holds.active_jobs()

    def test_binding_diagnostic_names_changed_fields_without_copying_values(self):
        changed=dict(self.binding,memory='private-other-source-version')
        with self.assertRaises(JobError):self.jobs.propose(self.job,self.binding,
            dict(approved=True),fresh=lambda:changed)
        events=self.jobs.audit_read('owner',self.job)['events']
        mismatch=next(row for row in events if row['event']=='context_binding_changed')
        self.assertEqual(mismatch['detail'],dict(changed_fields=['memory']))
        self.assertNotIn('private-other-source-version',json.dumps(events))


if __name__ == '__main__':
    unittest.main()
