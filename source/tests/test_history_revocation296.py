"""Synthetic deletion propagation across raw and approved history views."""
import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import test_research_history212 as history_fixture
import test_research_pipeline218 as pipeline_fixture
from experienced_dialogues import Reader, create_index, digest
from research_history import HistoryCorpus
from research_index import DailyIndex, Header, IndexConflict, IndexFailure, Page
from research_pipeline import Corpus, Pipeline, ResearchError


LESSON_CID = '11111111-2222-4333-8444-555555555555'


class HistoryRevocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.epoch = 'a' * 64
        self.allowed = ['old-a', 'old-b', LESSON_CID]
        self.archive = self.root / 'approved.sqlite3'
        records = [pipeline_fixture.ResearchTests.record(self, cid) for cid in self.allowed]
        create_index(self.archive, records, approved_cids=self.allowed)
        self.archive_sha = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.approved = Corpus(Reader(self.archive), [
            {'id': 'R1', 'text': 'Не обещать наличие крепежа.', 'active_primary': True}
        ], allowed_cids=self.allowed, guard=lambda _: None, versions=lambda: 'approved-v1')
        self.index = DailyIndex(self.root / 'daily', source_instance='synthetic',
                                guard=lambda _: True, guard_version=lambda: self.epoch)
        self.identities = history_fixture.Identities()
        self.current = pipeline_fixture.context()
        self.current.update(client_group='current-group', phone_hashes=[], media_hashes=[])

    def corpus(self, *, raw=True):
        return HistoryCorpus(self.approved, self.index, self.identities,
                             raw_history_enabled=raw)

    def revoke(self, *cids):
        state = self.index.state()
        headers = tuple(Header(cid, 2, 'native-' + cid, (), (), '', op='delete',
                               identity_keys=('b' * 64,)) for cid in cids)
        loader = mock.Mock(side_effect=AssertionError('Deletion must not load a source body'))
        cursor_name = state['cursor'] or 'initial'
        self.index.apply(Page('synthetic', 'delete-' + cursor_name, state['cursor'],
                              cursor_name + '-next', headers), loader,
                         expected_version=state['version'])
        loader.assert_not_called()

    def search(self, corpus):
        return corpus.call('search_history', {'query': 'шкаф крепёж купить', 'direction': 'mnc'},
                           self.current)

    def test_published_delete_excludes_approved_source_before_loading_its_body(self):
        self.revoke('old-a')
        for raw in (True, False):
            with self.subTest(raw=raw):
                corpus = self.corpus(raw=raw)
                loaded = []
                original = corpus._body

                def body(row):
                    loaded.append(row['cid'])
                    return original(row)

                corpus._body = body
                result = self.search(corpus)
                self.assertNotIn('old-a', [row['case_id'] for row in result['hits']])
                self.assertNotIn('old-a', loaded)
                self.assertIn('old-b', [row['case_id'] for row in result['hits']])
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(), self.archive_sha)

    def test_deleted_historical_lesson_is_filtered_but_owner_correction_remains(self):
        self.revoke(LESSON_CID)
        corpus = self.corpus(raw=False)
        historical = {'id': 'staff', 'case_id': LESSON_CID, 'action': 'Уточнить неизвестное'}
        owner = {'id': 'owner', 'case_id': 'owner-rule', 'action': 'Не обещать материалы'}
        corpus.reviewed_lesson_metadata = {
            record['id']: {'record': record, 'review': {
                'source_kind': kind, 'content_sha256': digest(record)}}
            for record, kind in ((historical, 'reviewed_staff_case'), (owner, 'owner_correction'))
        }
        self.assertEqual(corpus.filter_lessons([historical, owner], self.current), [owner])

    def test_new_job_evidence_does_not_reuse_revoked_approved_read(self):
        before = self.corpus()
        self.search(before)
        before.call('read_history', {'case_id': 'old-a'}, self.current)
        before.call('read_history', {'case_id': 'old-b'}, self.current)
        self.revoke('old-a')
        after = self.corpus()
        evidence = after.evidence(self.current)
        self.assertNotIn('old-a', [row['case_id'] for row in evidence['histories']])
        self.assertIn('old-b', [row['case_id'] for row in evidence['histories']])

    def test_revoked_cached_reads_cannot_satisfy_new_job_research_readiness(self):
        before = self.corpus()
        self.search(before)
        before.call('read_history', {'case_id': 'old-a'}, self.current)
        before.call('read_history', {'case_id': LESSON_CID}, self.current)
        before.call('read_rule', {'rule_id': 'R1'}, self.current)
        self.assertTrue(before.ready(self.current))
        self.revoke('old-a', LESSON_CID)
        after = self.corpus()
        self.search(after)
        self.assertFalse(after.ready(self.current))
        after.call('read_history', {'case_id': 'old-b'}, self.current)
        self.assertTrue(after.ready(self.current))

    def test_old_job_rejects_evidence_and_readiness_after_publication_change(self):
        corpus = self.corpus()
        self.search(corpus)
        self.revoke('old-a')
        with self.assertRaises(ResearchError):
            corpus.evidence(self.current)
        with self.assertRaises(ResearchError):
            corpus.ready(self.current)

    def test_unavailable_raw_sync_retains_revocation_for_approved_fallback(self):
        self.revoke('old-a')
        self.index.source_unavailable()
        corpus = self.corpus()
        result = self.search(corpus)
        self.assertFalse(result['raw_archive_available'])
        self.assertNotIn('old-a', [row['case_id'] for row in result['hits']])
        self.assertIn('old-b', [row['case_id'] for row in result['hits']])

    def test_cached_search_row_cannot_load_deleted_approved_body(self):
        row = next(row for row in self.corpus()._catalog() if row['cid'] == 'old-a')
        self.revoke('old-a')
        with mock.patch.object(Corpus, '_body', side_effect=AssertionError('Body must remain unread')):
            with self.assertRaises(ResearchError):
                self.corpus()._body(row)

    def test_explicit_identity_exclusion_also_removes_approved_views(self):
        self.index.guard = lambda header: header.cid != 'old-a'
        state = self.index.state()
        header = Header('old-a', 1, 'native-old-a', (), (), 'c' * 64)
        loader = mock.Mock(side_effect=AssertionError('Excluded body must not be loaded'))
        result = self.index.apply(Page('synthetic', 'excluded', state['cursor'], 'excluded-next',
                                       (header,)), loader, expected_version=state['version'])
        self.assertEqual(result['excluded'], 1)
        loader.assert_not_called()
        self.assertNotIn('old-a', [row['case_id'] for row in self.search(self.corpus())['hits']])

    def test_revocation_lookup_reads_only_requested_identity_metadata(self):
        self.revoke('old-a', LESSON_CID)
        original = self.index.connect
        forbidden = []

        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ and (
                    table.startswith('source_fts') or table == 'sources' and column in ('payload', 'header')):
                forbidden.append((table, column))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        @contextmanager
        def metadata_only(readonly=False):
            self.assertTrue(readonly)
            with original(readonly) as db:
                db.set_authorizer(authorize)
                yield db

        with mock.patch.object(self.index, 'connect', metadata_only):
            result = self.index.revocations(('old-a', 'old-b'),
                                             expected_version=self.index.state()['version'])
        self.assertEqual(result, {'old-a': {'revision': 2, 'reason': 'deleted'}})
        self.assertEqual(forbidden, [])

    def test_revocation_lookup_batches_large_allowed_sets_without_broadening_them(self):
        self.revoke('old-a', LESSON_CID)
        cids = tuple('synthetic-' + str(i) for i in range(1200)) + ('old-a', 'old-a')
        result = self.index.revocations(cids, expected_version=self.index.state()['version'])
        self.assertEqual(set(result), {'old-a'})

    def test_revocation_lookup_rejects_bad_scope_before_opening_database(self):
        values = [None, 'old-a', {'old-a'}, [''], [False], [7], ['a' * 201]]
        with mock.patch.object(self.index, 'connect', side_effect=AssertionError('No database read')):
            for value in values:
                with self.subTest(value=value), self.assertRaises(IndexFailure):
                    self.index.revocations(value, expected_version='a' * 64)

    def test_revocation_lookup_requires_exact_publication_and_protection(self):
        old_version = self.index.state()['version']
        self.revoke('old-a')
        with self.assertRaises(IndexConflict):
            self.index.revocations(('old-a',), expected_version=old_version)
        current_version = self.index.state()['version']
        self.epoch = 'c' * 64
        with self.assertRaises(IndexFailure):
            self.index.revocations(('old-a',), expected_version=current_version)

    def test_revocation_lookup_rejects_protection_change_at_return_boundary(self):
        self.revoke('old-a')
        version = self.index.state()['version']
        with mock.patch.object(self.index, '_epoch', side_effect=['a' * 64, 'c' * 64]):
            with self.assertRaises(IndexFailure):
                self.index.revocations(('old-a',), expected_version=version)

    def test_unavailable_protection_blocks_even_an_empty_revocation_lookup(self):
        self.index.source_unavailable(protection=True)
        with self.assertRaises(IndexFailure):
            self.index.revocations((), expected_version=self.index.state()['version'])

    def test_restarted_index_and_new_job_keep_the_published_removal(self):
        self.revoke('old-a')
        self.index = DailyIndex(self.root / 'daily', source_instance='synthetic',
                                guard=lambda _: True, guard_version=lambda: self.epoch)
        hits = self.search(self.corpus(raw=False))['hits']
        self.assertNotIn('old-a', [row['case_id'] for row in hits])
        self.assertIn('old-b', [row['case_id'] for row in hits])
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(), self.archive_sha)

    def test_research_and_review_packets_exclude_revoked_cached_sources(self):
        before = self.corpus()
        self.search(before)
        for cid in self.allowed:
            before.call('read_history', {'case_id': cid}, self.current)
        before.call('read_rule', {'rule_id': 'R1'}, self.current)
        self.revoke('old-a', LESSON_CID)
        roles = []

        def model(role, packet, tools):
            roles.append(role)
            self.assertEqual(packet['input']['current'], self.current)
            self.assertEqual([row['case_id'] for row in packet['input']['research']['histories']],
                             ['old-b'])
            self.assertNotIn('history:old-a', packet['input']['source_references'])
            self.assertNotIn('history:' + LESSON_CID, packet['input']['source_references'])
            if role == 'review':
                return {'kind': 'review', 'approved': True, 'violations': [],
                        'checked_claims': [0], 'basis': ['rule:R1']}
            return pipeline_fixture.ResearchTests.draft(self)

        result = Pipeline(self.corpus(raw=False), model, max_calls=2).run(self.current)
        self.assertTrue(result['approved'], result['reason'])
        self.assertEqual(roles, ['research', 'review'])
        self.assertFalse(result['can_send_or_create'])


if __name__ == '__main__':
    unittest.main()
