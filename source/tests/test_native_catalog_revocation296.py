"""Synthetic approved-only catalog omissions through the real sync CLI."""
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock

import test_research_history212 as history_fixture
import test_research_server209 as server_fixture
from native_exporter import NativeExporter
from research_index import SourceExcluded
from research_jobs import Jobs
from research_sources import ApprovedSources, SourceConfigurationError
from source_protocol import SourceError


class CatalogFixture:
    def setUp(self):
        self.s = server_fixture.ServerSourceTests()
        self.s.setUp()
        self.addCleanup(self.s.doCleanups)
        self.h = history_fixture.HistoryTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        path = Path(__file__).resolve().parents[1] / 'tools' / 'sync_native_history.py'
        spec = importlib.util.spec_from_file_location('synthetic_catalog_sync296', path)
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)
        self.headers = []
        self.bodies = []
        self.catalog_ids = []
        self.states = {'old-a': 'deleted'}
        self.after_header = lambda cid: None
        self.control = lambda: None
        self.s.config.update(schema=2, native_url='https://synthetic.invalid',
            native_history_scope='approved_only',
            native_protection=str(self.s.root / 'protection.json'), native_protection_sha256='a' * 64,
            native_identity_map=str(self.s.root / 'identities.json'), native_identity_map_sha256='b' * 64)
        case = self

        class Client:
            def protection_preflight(self, seconds):
                case.control()

            def catalog(self, after, limit):
                case.control()
                return {'cids': list(case.catalog_ids), 'next': None, 'complete': True,
                        'consistency': 'synthetic complete catalog'}

            def header(self, cid):
                case.control()
                case.headers.append(cid)
                state = case.states[cid]
                if state == 'unavailable':
                    raise SourceError('Synthetic metadata transport unavailable')
                if state == 'excluded':
                    raise SourceExcluded('Synthetic protected source')
                result = ({'cid': cid, 'identity_complete': True, 'message_count': 1,
                           'source_sha256': 'c' * 64, 'client_group': 'synthetic-' + cid,
                           'phone_hashes': [], 'media_hashes': [], 'identity_keys': ['d' * 64]}
                          if state == 'live' else {'cid': cid, state: True})
                case.after_header(cid)
                return result

            def history(self, header):
                case.bodies.append(header['cid'])
                raise AssertionError('Catalog omission must not open an original body')

        self.client = Client()

    def components(self, config, *, control):
        self.assertEqual(config['schema'], 2)
        self.control = control
        self.h.index.guard_version = lambda: (control(), 'a' * 64)[1]
        return self.client, self.h.index

    def run_cli(self):
        self.s.write(self.s.path, self.s.config)
        output = io.StringIO()
        with mock.patch.object(self.cli, 'source_components', side_effect=self.components), \
             mock.patch.object(ApprovedSources, 'corpus', side_effect=AssertionError('No corpus/body scope load')), \
             contextlib.redirect_stdout(output):
            self.cli.main(['--config', str(self.s.path), '--max-cases', '20', '--max-seconds', '5'])
        return json.loads(output.getvalue())


class CatalogSyncTests(CatalogFixture, unittest.TestCase):
    def test_pinned_approved_source_missing_from_catalog_and_raw_cache_is_revoked(self):
        self.assertEqual(self.h.index.state()['records'], 0)
        self.run_cli()
        revoked = self.h.index.revocations(('old-a',), expected_version=self.h.index.state()['version'])
        self.assertIn('old-a', revoked)
        self.assertEqual(self.headers, ['old-a'])
        self.assertEqual(self.bodies, [])
        self.assertNotIn('old-a', [row['cid'] for row in self.h.corpus()._catalog()])
        self.assertIn('old-b', [row['cid'] for row in self.h.corpus()._catalog()])
        self.assertFalse(Path(self.s.config['key_file']).exists())

    def test_empty_catalog_cannot_revoke_an_exact_source_that_is_still_live(self):
        self.states['old-a'] = 'live'
        self.run_cli()
        self.assertEqual(self.headers, ['old-a'])
        self.assertEqual(self.bodies, [])
        self.assertEqual(self.h.index.revocations(('old-a',),
                                                  expected_version=self.h.index.state()['version']), {})
        self.assertIn('old-a', [row['cid'] for row in self.h.corpus()._catalog()])

    def test_common_metadata_failure_does_not_bulk_remove_approved_sources(self):
        self.states['old-a'] = 'unavailable'
        version = self.h.index.state()['data_version']
        with self.assertRaises(SourceError):
            self.run_cli()
        self.assertEqual(self.h.index.state()['data_version'], version)
        with self.h.index.connect(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tombstones').fetchone()[0], 0)
        self.assertEqual(self.bodies, [])

    def assert_negative_metadata_only(self, state):
        self.states['old-a'] = state
        result = self.run_cli()
        self.assertFalse(result.get('not_due'))
        self.assertNotIn('old-a', [row['cid'] for row in self.h.corpus()._catalog()])
        self.assertEqual(self.headers, ['old-a'])
        self.assertEqual(self.bodies, [])

    def test_missing_pending_source_is_a_negative_observation_only(self):
        self.assert_negative_metadata_only('pending')

    def test_missing_excluded_source_is_a_negative_observation_only(self):
        self.assert_negative_metadata_only('excluded')

    def test_changed_manifest_is_rejected_before_metadata_access(self):
        self.s.write(self.s.manifest, {**self.s.permission, 'approved_cids': ['old-b']})
        with self.assertRaises(SourceConfigurationError):
            self.run_cli()
        self.assertEqual(self.headers, [])
        self.assertEqual(self.bodies, [])

    def test_manifest_is_rechecked_before_negative_publication(self):
        def change_manifest(cid):
            self.s.write(self.s.manifest, {**self.s.permission, 'approved_cids': ['old-b']})

        self.after_header = change_manifest
        with self.assertRaises(ValueError):
            self.run_cli()
        with self.h.index.connect(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tombstones').fetchone()[0], 0)
        self.assertEqual(self.bodies, [])

    def test_pointer_is_rechecked_before_negative_publication(self):
        def change_pointer(cid):
            self.s.write(self.s.pointer, {'schema': 999})

        self.after_header = change_pointer
        with self.assertRaises(ValueError):
            self.run_cli()
        with self.h.index.connect(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tombstones').fetchone()[0], 0)
        self.assertEqual(self.bodies, [])

    def test_live_metadata_cannot_finish_after_source_permission_changes(self):
        self.states['old-a'] = 'live'

        def revoke_permission(cid):
            self.s.write(self.s.manifest, {**self.s.permission, 'approved_cids': ['old-b']})

        self.after_header = revoke_permission
        with self.assertRaises(ValueError):
            self.run_cli()
        self.assertEqual(self.bodies, [])

    def test_live_metadata_cannot_silently_restore_a_previously_removed_source(self):
        self.run_cli()
        # A separate invocation is not due yet; force the same publisher in
        # this synthetic test to observe a later metadata-only confirmation.
        self.states['old-a'] = 'live'
        worker = NativeExporter(self.client, self.h.index, self.s.root / 'research' / 'native-export',
            shared_lock=Path(self.s.config['shared_lock']), approved_cids=('old-a',))
        for _ in range(10):
            if worker.run(max_cases=20, force=True)['run'] is None:
                break
        self.assertIn('old-a', self.h.index.revocations(('old-a',),
                                                       expected_version=self.h.index.state()['version']))
        self.assertEqual(self.bodies, [])


class CatalogScopeTests(CatalogFixture, unittest.TestCase):
    def worker(self, approved=('old-a',), preflight=None):
        return NativeExporter(self.client, self.h.index, self.s.root / 'scope-scan',
            shared_lock=Path(self.s.config['shared_lock']), approved_cids=approved, preflight=preflight)

    def hold(self):
        binding = {'owner': 'synthetic', 'request': 'one', 'chat': 'current', 'revision': 'r1',
                   'principal': 'admin', 'operator': 'operator', 'policy': 'p', 'memory': 'm',
                   'map': 'map', 'task': 'task', 'profile': 'sol_only'}
        jobs = Jobs(self.s.root / 'scope-jobs', shared_lock=Path(self.s.config['shared_lock']))
        grant = jobs.admit(binding, max_calls=1, seconds=300)
        return jobs, jobs.submit(binding, grant)['job_id']

    def prepared(self, worker):
        with worker.db() as db:
            return db.execute('SELECT value FROM prepared WHERE id=1').fetchone()[0]

    def test_completed_catalog_negative_publication_respects_original_job_hold(self):
        jobs, job = self.hold()
        worker = self.worker()
        version = self.h.index.state()['version']
        result = worker.run(max_cases=20, force=True)
        self.assertTrue(result.get('waiting_for_model_lock'), result)
        original = self.prepared(worker)
        self.assertEqual(self.h.index.state()['version'], version)
        jobs.stop('synthetic', job)
        restored = self.worker()
        self.assertEqual(self.prepared(restored), original)
        for _ in range(10):
            if restored.run(max_cases=20, force=True)['run'] is None:
                break
        self.assertEqual(self.headers, ['old-a'])
        self.assertEqual(self.bodies, [])
        self.assertEqual(jobs.status('synthetic', job)['calls_spent'], 0)

    def test_active_scan_cannot_adopt_a_different_approved_scope(self):
        jobs, job = self.hold()
        worker = self.worker()
        self.assertTrue(worker.run(max_cases=20, force=True).get('waiting_for_model_lock'))
        original = self.prepared(worker)
        preflight = mock.Mock(side_effect=AssertionError('Changed scope must stop before source access'))
        changed = self.worker(('old-b',), preflight=preflight)
        with self.assertRaises(SourceError):
            changed.run(max_cases=20, force=True)
        self.assertEqual(self.prepared(changed), original)
        self.assertEqual(self.headers, ['old-a'])
        self.assertTrue(self.h.index.state()['protection_unavailable'])
        preflight.assert_not_called()
        self.assertIn(job, jobs.holds.active_jobs())

    def test_same_set_in_a_different_order_keeps_the_original_scan(self):
        self.states['old-b'] = 'deleted'
        jobs, job = self.hold()
        first = self.worker(('old-a', 'old-b'))
        self.assertTrue(first.run(max_cases=20, force=True).get('waiting_for_model_lock'))
        same = self.worker(('old-b', 'old-a'))
        self.assertEqual(first.approved_scope, same.approved_scope)
        self.assertTrue(same.run(max_cases=20, force=True).get('waiting_for_model_lock'))
        jobs.stop('synthetic', job)
        for _ in range(10):
            if same.run(max_cases=20, force=True)['run'] is None:
                break
        self.assertEqual(self.headers, ['old-a', 'old-b'])
        self.assertEqual(self.bodies, [])

    def test_metadata_presence_checks_obey_the_finite_case_budget(self):
        self.states.update({'old-a': 'live', 'old-b': 'live', 'old-c': 'live'})
        worker = self.worker(('old-a', 'old-b', 'old-c'))
        worker.run(max_cases=1, force=True)
        self.assertEqual(len(self.headers), 1)
        self.assertEqual(self.bodies, [])

    def test_pruning_waits_for_the_complete_catalog(self):
        self.states['page-marker'] = 'pending'

        def pages(after, limit):
            return ({'cids': ['page-marker'], 'next': 'page-marker', 'complete': False,
                     'consistency': 'synthetic paged catalog'} if after is None else
                    {'cids': [], 'next': None, 'complete': True,
                     'consistency': 'synthetic paged catalog'})

        self.client.catalog = pages
        worker = self.worker()
        worker.run(max_cases=1, force=True)
        self.assertNotIn('old-a', self.headers)
        self.assertEqual(self.h.index.revocations(('old-a',),
                                                  expected_version=self.h.index.state()['version']), {})
        for _ in range(10):
            if worker.run(max_cases=20, force=True)['run'] is None:
                break
        self.assertIn('old-a', self.headers)
        self.assertIn('old-a', self.h.index.revocations(('old-a',),
                                                       expected_version=self.h.index.state()['version']))
        self.assertEqual(self.bodies, [])

    def test_invalid_approved_scope_stops_before_any_directory_or_source_access(self):
        for value in ('old-a', None, ['old-a', 'old-a'], [False], [''], ['x' * 201]):
            with self.subTest(value=value), self.assertRaises(SourceError):
                self.worker(value)
        self.assertFalse((self.s.root / 'scope-scan').exists())
        self.assertEqual(self.headers, [])

    def test_legacy_active_scan_without_scope_does_not_expand_silently(self):
        self.catalog_ids = ['old-a']
        worker = self.worker(())
        worker.run(max_cases=1, force=True)
        original = self.prepared(worker)
        with worker.db() as db:
            scan = worker._get(db, 'scan')
            scan.pop('approved_scope')
            worker._put(db, 'scan', scan)
        with self.assertRaises(SourceError):
            self.worker(('old-a',)).run(max_cases=20, force=True)
        self.assertEqual(self.prepared(worker), original)
        self.assertEqual(self.bodies, [])

    def test_legacy_empty_scope_can_finish_the_same_prepared_operation(self):
        self.catalog_ids = ['old-a']
        worker = self.worker(())
        worker.run(max_cases=1, force=True)
        with worker.db() as db:
            scan = worker._get(db, 'scan')
            scan.pop('approved_scope')
            worker._put(db, 'scan', scan)
        restored = self.worker(())
        for _ in range(10):
            if restored.run(max_cases=20, force=True)['run'] is None:
                break
        self.assertEqual(self.headers, ['old-a'])
        self.assertEqual(self.bodies, [])


if __name__ == '__main__':
    unittest.main()
