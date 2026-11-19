"""Trusted negative metadata must fence an original held research operation."""
import json
import unittest
from unittest import mock

import auto_simulator231 as simulation
import test_native_revocation296 as native_fixture
import test_research_index206 as index_fixture
from research_index import DailyIndex, Header, IndexConflict, IndexFailure, Removal


class EmergencyNativeTests(unittest.TestCase):
    def setUp(self):
        self.f = native_fixture.NativeRevocationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.sim = self.f.sim

    def observe_withdrawal(self):
        result = self.f.exporter.run(max_cases=20, force=True)
        self.assertTrue(result.get('waiting_for_model_lock'), result)
        self.assertEqual(self.f.body_reads, [])

    def test_queued_original_cannot_generate_after_negative_observation_under_hold(self):
        job = self.f.f.start()
        version = self.f.index.state()['version']
        self.observe_withdrawal()
        self.assertEqual(self.f.index.state()['version'], version)
        self.assertIn(job, self.sim.service.jobs.holds.active_jobs())
        self.f.f.workers()
        self.assertEqual(len(self.sim.requests), 0)
        status = self.sim.service.jobs.status(simulation.OWNER, job)
        self.assertEqual(status['state'], 'stopped')
        self.assertEqual(status['calls_spent'], 0)

    def test_withdrawal_between_proposal_and_review_preserves_one_original_attempt(self):
        original = self.sim.provider

        def provider(payload, timeout):
            result = original(payload, timeout)
            self.observe_withdrawal()
            return result

        self.sim.service.request = provider
        job = self.f.f.start()
        self.f.f.workers()
        self.assertEqual(len(self.sim.requests), 1)
        status = self.sim.service.jobs.status(simulation.OWNER, job)
        self.assertEqual(status['state'], 'stopped')
        self.assertEqual(status['calls_spent'], 1)

    def test_accepted_original_cannot_finalize_after_negative_observation_under_hold(self):
        job = self.f.f.start()
        self.f.f.workers()
        self.assertEqual(self.sim.service.jobs.status(simulation.OWNER, job)['state'], 'accepted')
        self.observe_withdrawal()
        with mock.patch.object(self.sim.app, 'finish', wraps=self.sim.app.finish) as finish:
            result, code = self.f.f.call('research_finalize')
        self.assertEqual(code, 403, result)
        self.assertFalse(result.get('draft_id'))
        # The service finishes its reserved request with a safe abort handoff.
        # That cleanup is not successful finalization of the reviewed answer.
        finish.assert_called_once()
        aborted = finish.call_args.args[1]
        self.assertEqual(aborted['reply'], '')
        self.assertEqual(aborted['code'], 'research_stopped')
        self.assertEqual(aborted['action'], 'handoff')
        with self.sim.service.jobs.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE job=? AND event=?",
                (job, 'legacy_finalize_started')).fetchone()[0], 0)
        self.assertEqual(len(self.sim.requests), 2)

    def test_first_finite_planning_slice_fences_before_deferred_publication(self):
        job = self.f.f.start()
        before = self.f.corpus().initial
        self.f.exporter.run(max_cases=1, force=True)
        self.assertIn('old-a', self.f.index.revocations(('old-a',),
            expected_version=self.f.index.state()['version']))
        self.assertNotEqual(self.f.corpus().initial, before)
        self.assertIn(job, self.sim.service.jobs.holds.active_jobs())
        self.assertEqual(len(self.sim.requests), 0)
        self.assertEqual(self.f.body_reads, [])

    def test_restart_keeps_fence_original_hold_and_prepared_negative_bytes(self):
        job = self.f.f.start()
        self.observe_withdrawal()
        with self.f.exporter.db() as db:
            prepared = db.execute('SELECT value FROM prepared WHERE id=1').fetchone()[0]
        original_hold = self.sim.service.jobs.holds.path(job).read_bytes()
        stamp = self.f.index.withdrawal_version()
        self.sim.work.clear()
        self.f.restart_service()
        self.f.index = DailyIndex(self.f.index.directory, source_instance='synthetic-native',
                                 guard=lambda _: True, guard_version=lambda: 'a' * 64)
        self.f.exporter = self.f.exporter_instance()
        self.assertEqual(self.f.index.withdrawal_version(), stamp)
        self.assertEqual(self.sim.service.jobs.holds.path(job).read_bytes(), original_hold)
        self.assertNotIn('old-a', [row['cid'] for row in self.f.corpus()._catalog()])
        with self.f.exporter.db() as db:
            self.assertEqual(db.execute('SELECT value FROM prepared WHERE id=1').fetchone()[0], prepared)
        self.sim.service.jobs.stop(simulation.OWNER, job)
        headers = list(self.f.header_reads)
        self.f.finish()
        self.assertEqual(self.f.header_reads, headers)
        self.assertEqual(self.f.body_reads, [])
        self.assertEqual(len(self.sim.requests), 0)
        with self.sim.service.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)

    def test_fence_does_not_remove_the_other_original_job_hold(self):
        first = self.f.f.start()
        jobs = self.sim.service.jobs
        with jobs.connect() as db:
            binding = json.loads(jobs._row(db, first)['binding'])
        binding.update(request='second-original-request', chat='second-original-chat')
        grant = jobs.admit(binding, max_calls=2, seconds=300)
        second = jobs.submit(binding, grant)['job_id']
        original_hold = jobs.holds.path(second).read_bytes()
        self.observe_withdrawal()
        self.assertEqual(set(jobs.holds.active_jobs()), {first, second})
        jobs.stop(simulation.OWNER, first)
        self.observe_withdrawal()
        self.assertEqual(jobs.holds.path(second).read_bytes(), original_hold)
        self.assertEqual(jobs.status(simulation.OWNER, second)['state'], 'queued')
        jobs.stop(simulation.OWNER, second)
        self.f.finish()
        self.assertEqual(len(self.sim.requests), 0)


class WithdrawalIndexTests(unittest.TestCase):
    def setUp(self):
        self.f = index_fixture.IndexTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.index = self.f.index

    def withdraw(self, cid='a', revision=2):
        return self.index.withdraw(Removal(cid, revision), expected_version=self.index.state()['version'])

    def test_fence_filters_raw_search_and_body_without_changing_publication(self):
        self.f.apply(self.f.record())
        before = self.index.state()
        stamp = self.index.withdrawal_version()
        self.assertTrue(self.withdraw())
        self.assertEqual(self.index.state(), before)
        self.assertNotEqual(self.index.withdrawal_version(), stamp)
        self.assertEqual(self.f.search()['hits'], [])
        with self.assertRaises(IndexFailure):
            self.f.read()
        self.assertEqual(self.f.loads, ['a'])
        self.assertEqual(self.index.revocations(('a',), expected_version=before['version'])['a']['reason'],
                         'withdrawal_pending_publication')

    def test_repeated_fence_is_idempotent_and_never_admits_a_body(self):
        self.assertTrue(self.withdraw())
        stamp = self.index.withdrawal_version()
        self.assertFalse(self.withdraw())
        self.assertFalse(self.withdraw(revision=1))
        self.assertEqual(self.index.withdrawal_version(), stamp)
        self.assertEqual(self.f.loads, [])
        self.assertEqual(self.f.guards, [])

    def test_fence_requires_a_negative_identity_and_exact_current_publication(self):
        for value in [None, {}, Header('a', 1, 'group', (), (), 'a' * 64), Removal('', 1), Removal('a', True)]:
            with self.subTest(value=type(value).__name__), self.assertRaises(IndexFailure):
                self.index.withdraw(value, expected_version=self.index.state()['version'])
        with self.assertRaises(IndexConflict):
            self.index.withdraw(Removal('a', 1), expected_version='stale')
        self.assertEqual(self.index.revocations(('a',), expected_version=self.index.state()['version']), {})

    def test_changed_protection_rolls_back_new_fence(self):
        original = self.f.epoch
        calls = []

        def epoch():
            calls.append(1)
            return original if len(calls) == 1 else 'b' * 64

        self.index.guard_version = epoch
        with self.assertRaises(IndexFailure):
            self.withdraw()
        self.index.guard_version = lambda: original
        self.assertEqual(self.index.revocations(('a',), expected_version=self.index.state()['version']), {})

    def test_unavailable_protection_cannot_approve_even_an_existing_fence(self):
        self.withdraw()
        self.index.source_unavailable(protection=True)
        with self.assertRaises(IndexFailure):
            self.withdraw()
        with self.assertRaises(IndexFailure):
            self.index.withdrawal_version()

    def test_matching_original_removal_commits_once_and_releases_pending_fence(self):
        self.withdraw()
        page = self.f.page([Removal('a', 2)])
        loader = mock.Mock(side_effect=AssertionError('Negative source has no body'))
        version = self.index.state()['version']
        first = self.index.apply(page, loader, expected_version=version)
        self.assertEqual(first['deleted'], 1)
        with self.index.connect(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM withdrawals').fetchone()[0], 0)
        self.assertFalse(self.index.withdraw(Removal('a', 2), expected_version=version))
        self.assertTrue(self.index.apply(page, loader, expected_version=version)['replayed'])
        loader.assert_not_called()

    def test_older_or_same_revision_positive_source_cannot_clear_pending_fence(self):
        self.withdraw(revision=3)
        for revision in [1, 3]:
            result = self.f.apply(self.f.record(revision=revision))
            self.assertEqual(result['stale'], 1)
        self.assertEqual(self.f.loads, [])
        self.assertIn('a', self.index.revocations(('a',), expected_version=self.index.state()['version']))

    def test_newer_fully_admitted_positive_source_can_restore_after_fence(self):
        self.withdraw(revision=2)
        self.f.apply(self.f.record(revision=3))
        self.assertEqual(self.f.read()['source']['source_revision'], 3)
        self.assertEqual(self.index.revocations(('a',), expected_version=self.index.state()['version']), {})
        self.assertFalse(self.withdraw(revision=2))

    def test_withdrawal_during_positive_body_read_blocks_publication_without_clearing_fence(self):
        value = self.f.record()
        page = self.f.page([self.f.header(value)])

        def load(header):
            source = self.f.load(header)
            self.withdraw()
            return source

        with self.assertRaises(IndexFailure):
            self.index.apply(page, load, expected_version=self.index.state()['version'])
        self.assertEqual(self.index.state()['records'], 0)
        self.assertIn('a', self.index.revocations(('a',), expected_version=self.index.state()['version']))


if __name__ == '__main__':
    unittest.main()
