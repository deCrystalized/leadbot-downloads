"""Synthetic native deletion through publication holds, service and memory."""
import hashlib
import json
import unittest
from unittest import mock

import auto_simulator231 as simulation_fixture
import test_native_research238 as native_fixture
import test_research_history212 as history_fixture
import test_research_index206 as index_fixture
from assistant_store import digest
from native_exporter import NativeExporter
from research_history import HistoryCorpus
from research_index import DailyIndex, Header, IndexFailure, Removal, SourceExcluded
from research_jobs import JobError
from research_workflow import ResearchService
from source_protocol import SourceError


class NativeRevocationTests(unittest.TestCase):
    def setUp(self):
        self.f = native_fixture.NativeResearch238Tests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.sim = self.f.sim
        self.base_corpus = self.sim.service.corpus_factory
        self.index = DailyIndex(self.sim.root / 'metadata-index', source_instance='synthetic-native',
                                guard=lambda _: True, guard_version=lambda: 'a' * 64)
        self.identities = history_fixture.Identities()
        self.sim.service.corpus_factory = self.corpus
        self.header_reads = []
        self.body_reads = []
        self.removal = 'deleted'
        self.archive_sha = hashlib.sha256(self.sim.archive.read_bytes()).hexdigest()
        case = self

        class Client:
            def catalog(self, after, limit):
                return {'cids': ['old-a'], 'next': None, 'complete': True,
                        'consistency': 'synthetic-metadata'}

            def header(self, cid):
                case.header_reads.append(cid)
                if case.removal == 'excluded':
                    raise SourceExcluded('Synthetic protected source')
                return {'cid': cid, case.removal: True}

            def history(self, header):
                case.body_reads.append(header['cid'])
                raise AssertionError('A negative observation must never read a history body')

        self.client = Client()
        self.exporter = self.exporter_instance()

    def corpus(self):
        return HistoryCorpus(self.base_corpus(), self.index, self.identities,
                             raw_history_enabled=False)

    def exporter_instance(self):
        return NativeExporter(self.client, self.index, self.sim.root / 'metadata-export',
                              shared_lock=self.sim.root / 'provider.lock')

    def finish(self):
        for _ in range(10):
            value = self.exporter.run(max_cases=20, force=True)
            if value['run'] is None:
                return value
        self.fail('Original finite metadata scan did not finish')

    def context(self):
        return self.sim.service._context(self.sim.app, self.f.body)

    def restart_service(self):
        old = self.sim.service
        self.sim.service = ResearchService(self.sim.root / 'research',
            shared_lock=self.sim.root / 'provider.lock', corpus_factory=self.corpus,
            request=self.sim.provider, schedule=self.sim.work.append,
            native_context=old.native_context, proposal_enabled=True,
            owner_auto_enabled=True, auto_session_call_limit=12,
            native_authority=self.f.authority)
        self.sim.app.research = self.sim.service

    def test_deleted_native_metadata_revokes_approved_source_without_old_raw_row(self):
        self.assertIn('old-a', [row['cid'] for row in self.corpus()._catalog()])
        self.assertEqual(self.index.state()['records'], 0)
        self.finish()
        revoked = self.index.revocations(('old-a',), expected_version=self.index.state()['version'])
        self.assertIn('old-a', revoked)
        self.assertNotIn('old-a', [row['cid'] for row in self.corpus()._catalog()])
        self.assertEqual(self.body_reads, [])
        self.assertEqual(hashlib.sha256(self.sim.archive.read_bytes()).hexdigest(), self.archive_sha)

    def test_native_removal_invalidates_real_service_quick_memory_binding(self):
        self.f.preview()
        before, current, _, _ = self.context()
        memory = self.sim.service.memory
        memory.save(before['owner'], before['chat'], current,
                    expected_generation=0, authoritative_revision=before['revision'])
        self.finish()
        with self.assertRaises(JobError) as stopped:
            self.context()
        self.assertEqual(stopped.exception.check, 'auto_session_changed')
        # Close only this view's preview lease, as the existing native turn
        # tests do. No job, generation allowance or source hold is replaced.
        self.sim.app.store.release_dialog('assistant:' + digest(before['owner']),
                                          before['chat'], before['request'])
        self.f.body.pop('request_id', None)
        self.f.body.pop('revision', None)
        self.f.preview()  # The old launch must not acquire a new memory binding silently.
        after, fresh, _, _ = self.context()
        self.assertNotEqual(after['memory'], before['memory'])
        loaded = memory.load(after['owner'], after['chat'], fresh)
        self.assertEqual(loaded['status'], 'stale')
        self.assertIsNone(loaded['payload'])
        saved = memory.save(after['owner'], after['chat'], fresh,
                            expected_generation=loaded['generation'],
                            authoritative_revision=after['revision'])
        self.assertEqual(saved['generation'], loaded['generation'] + 1)
        self.assertEqual(memory.load(after['owner'], after['chat'], fresh)['payload'], fresh)
        self.assertEqual(self.sim.requests, [])

    def test_queued_native_job_defers_original_negative_publication(self):
        job = self.f.start()
        old_version = self.index.state()['version']
        value = self.exporter.run(max_cases=20, force=True)
        self.assertTrue(value.get('waiting_for_model_lock'), value)
        self.assertEqual(self.index.state()['version'], old_version)
        self.assertIn(job, self.sim.service.jobs.holds.active_jobs())
        self.assertEqual(self.sim.requests, [])
        self.assertEqual(self.body_reads, [])

    def test_stopped_service_restart_finishes_same_prepared_removal_without_retry(self):
        job = self.f.start()
        value = self.exporter.run(max_cases=20, force=True)
        self.assertTrue(value.get('waiting_for_model_lock'), value)
        with self.exporter.db() as db:
            prepared = db.execute('SELECT value FROM prepared WHERE id=1').fetchone()[0]
        headers_before = list(self.header_reads)
        self.sim.service.jobs.stop(simulation_fixture.OWNER, job)
        self.sim.work.clear()  # Simulate the stopped process losing its in-memory scheduler queue.
        self.restart_service()
        self.exporter = self.exporter_instance()
        with self.exporter.db() as db:
            self.assertEqual(db.execute('SELECT value FROM prepared WHERE id=1').fetchone()[0], prepared)
        self.finish()
        self.assertEqual(self.header_reads, headers_before)
        self.assertEqual(self.body_reads, [])
        self.assertEqual(self.sim.service.jobs.status(simulation_fixture.OWNER, job)['state'], 'stopped')
        self.assertEqual(self.sim.service.jobs.status(simulation_fixture.OWNER, job)['calls_spent'], 0)
        self.assertEqual(self.sim.service.jobs.holds.active_jobs(), [])
        self.f.call('research_start')
        with self.sim.service.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)
        self.assertEqual(self.sim.requests, [])

    def test_exclusion_and_pending_metadata_revoke_without_a_cached_body(self):
        for state in ('excluded', 'pending'):
            self.removal = state
            with self.subTest(state=state):
                self.finish()
                self.assertNotIn('old-a', [row['cid'] for row in self.corpus()._catalog()])
        self.assertEqual(self.body_reads, [])

    def test_unchanged_negative_observation_does_not_publish_a_new_version(self):
        self.finish()
        version = self.index.state()['version']
        with self.exporter.db() as db:
            revision = db.execute('SELECT revision FROM observed WHERE cid=?', ('old-a',)).fetchone()[0]
        self.finish()
        self.assertEqual(self.index.state()['version'], version)
        with self.exporter.db() as db:
            self.assertEqual(db.execute('SELECT revision FROM observed WHERE cid=?', ('old-a',)).fetchone()[0],
                             revision)
        self.assertEqual(self.body_reads, [])

    def test_legacy_negative_scan_observation_is_backfilled_into_removal_ledger(self):
        fingerprint = 'unobserved_or_deleted:' + self.index.guard_version()
        with self.exporter.db() as db:
            db.execute('INSERT INTO observed VALUES(?,?,?)', ('old-a', fingerprint, 1))
        self.finish()
        self.assertIn('old-a', self.index.revocations(('old-a',),
                                                     expected_version=self.index.state()['version']))
        self.assertEqual(self.body_reads, [])

    def test_unknown_negative_commit_after_crash_is_reconciled_without_second_effect(self):
        class Interrupted(BaseException):
            pass

        def crash():
            raise Interrupted()

        with self.assertRaises(Interrupted):
            self.exporter.run(max_cases=20, force=True, after_publish=crash)
        version = self.index.state()['version']
        headers = list(self.header_reads)
        self.exporter = self.exporter_instance()
        self.finish()
        self.assertEqual(self.index.state()['version'], version)
        self.assertEqual(self.header_reads, headers)
        self.assertEqual(self.body_reads, [])
        with self.index.connect(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM batches').fetchone()[0], 1)
        with self.exporter.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE event='published'").fetchone()[0], 1)

    def test_corrupt_negative_journal_cannot_become_a_source_write(self):
        job = self.f.start()
        self.exporter.run(max_cases=20, force=True)
        with self.exporter.db() as db:
            original = json.loads(db.execute('SELECT value FROM prepared WHERE id=1').fetchone()[0])
        self.sim.service.jobs.stop(simulation_fixture.OWNER, job)
        for mutation in ({'header_type': 'unknown'}, {'source': {'messages': ['not admitted']}}):
            with self.subTest(mutation=mutation):
                with self.exporter.db() as db:
                    db.execute('UPDATE prepared SET value=? WHERE id=1',
                               (json.dumps({**original, **mutation}),))
                with self.assertRaises(SourceError):
                    self.exporter._publish({})
        self.assertEqual(self.index.state()['records'], 0)
        self.assertEqual(self.body_reads, [])
        self.assertEqual(self.sim.requests, [])

    def test_accepted_native_job_still_holds_negative_publication(self):
        job = self.f.start()
        self.f.workers()
        self.assertEqual(self.sim.service.jobs.status(simulation_fixture.OWNER, job)['state'], 'accepted')
        calls = len(self.sim.requests)
        version = self.index.state()['version']
        value = self.exporter.run(max_cases=20, force=True)
        self.assertTrue(value.get('waiting_for_model_lock'), value)
        self.assertEqual(self.index.state()['version'], version)
        self.assertEqual(len(self.sim.requests), calls)
        self.sim.service.jobs.stop(simulation_fixture.OWNER, job)
        self.finish()
        self.assertEqual(len(self.sim.requests), calls)


class RemovalIndexTests(unittest.TestCase):
    def setUp(self):
        self.f = index_fixture.IndexTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.index = self.f.index

    def remove(self, cid='never-loaded', revision=1, **extra):
        page = self.f.page([Removal(cid, revision)])
        loader = mock.Mock(side_effect=AssertionError('Removal has no history body'))
        result = self.index.apply(page, loader, expected_version=self.index.state()['version'], **extra)
        loader.assert_not_called()
        return page, result

    def test_removal_does_not_manufacture_positive_identity_or_read_source_body(self):
        _, result = self.remove()
        self.assertEqual(result['deleted'], 1)
        self.assertEqual(result['state']['records'], 0)
        self.assertEqual(self.f.guards, [])
        self.assertIn('never-loaded', self.index.revocations(('never-loaded',),
                                                            expected_version=self.index.state()['version']))

    def test_removal_rejects_invalid_identity_and_revision(self):
        for cid, revision in [('', 1), ('a' * 201, 1), (False, 1), ('a', True), ('a', 0)]:
            with self.subTest(cid=cid, revision=revision), self.assertRaises(IndexFailure):
                Removal(cid, revision).validate()
        with self.assertRaises(TypeError):
            Removal('a', 1, source_sha256='b' * 64)

    def test_positive_upsert_still_requires_a_complete_admitted_identity(self):
        header = Header('a', 1, '', (), (), 'b' * 64, identity_complete=False)
        loader = mock.Mock(side_effect=AssertionError('Incomplete identity cannot read a body'))
        with self.assertRaises(IndexFailure):
            self.index.apply(self.f.page([header]), loader, expected_version=self.index.state()['version'])
        loader.assert_not_called()
        self.assertEqual(self.index.state()['records'], 0)

    def test_removal_of_existing_raw_record_revokes_search_and_direct_read(self):
        self.f.apply(self.f.record('a'))
        bodies = list(self.f.loads)
        self.remove('a', 2)
        self.assertEqual(self.f.loads, bodies)
        self.assertEqual(self.f.search()['hits'], [])
        with self.assertRaises(IndexFailure):
            self.f.read('a')

    def test_stale_removal_cannot_delete_newer_source(self):
        self.f.apply(self.f.record('a', revision=2))
        _, result = self.remove('a', 1)
        self.assertEqual(result['stale'], 1)
        self.assertEqual(self.f.read('a')['source']['source_revision'], 2)

    def test_same_revision_removal_conflict_preserves_original_source(self):
        self.f.apply(self.f.record('a', revision=2))
        version = self.index.state()['data_version']
        with self.assertRaises(IndexFailure):
            self.remove('a', 2)
        self.assertEqual(self.index.state()['data_version'], version)
        with self.index.connect(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sources').fetchone()[0], 1)

    def test_replayed_removal_never_loads_or_republishes(self):
        page, _ = self.remove()
        version = self.index.state()['version']
        loader = mock.Mock(side_effect=AssertionError('No body on replay'))
        result = self.index.apply(page, loader, expected_version=version)
        self.assertTrue(result['replayed'])
        self.assertEqual(self.index.state()['version'], version)
        loader.assert_not_called()

    def test_removal_rollback_and_original_page_recovery_are_atomic(self):
        page = self.f.page([Removal('a', 1)])
        state = self.index.state()
        loader = mock.Mock(side_effect=AssertionError('No body'))

        def crash():
            raise OSError('Synthetic failure before commit')

        with self.assertRaises(IndexFailure):
            self.index.apply(page, loader, expected_version=state['version'], before_publish=crash)
        self.assertEqual(self.index.state()['cursor'], state['cursor'])
        with self.index.connect(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tombstones').fetchone()[0], 0)
        self.index.apply(page, loader, expected_version=self.index.state()['version'])
        self.assertIn('a', self.index.revocations(('a',), expected_version=self.index.state()['version']))
        loader.assert_not_called()

    def test_protection_change_rolls_back_removal(self):
        def changed():
            self.f.epoch = 'e' * 64

        with self.assertRaises(IndexFailure):
            self.remove(before_publish=changed)
        with self.index.connect(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tombstones').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
