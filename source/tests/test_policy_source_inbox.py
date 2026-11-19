from contextlib import closing
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from leadbot.brain.policy_source_inbox import (
    PolicySourceInbox, SourceIntakeError, SourceSpec, VerifiedObservation,
)


class PolicySourceInboxTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'policy.sqlite'
        self.now = 2000
        self.spec = SourceSpec('service-policy', 'fixture://primary', frozenset({'regulation-owner'}),
                               'intake', 60)
        self.inbox = self.open_inbox()

    def open_inbox(self, spec=None):
        # This test adapter stands in for verification by the authenticated
        # connector. Production wiring must verify the provider receipt.
        return PolicySourceInbox(self.path, [spec or self.spec], lambda spec, raw, receipt: receipt,
                                 clock=lambda: self.now)

    def receipt(self, raw, version='v1', previous=None, **fields):
        observation = VerifiedObservation(self.spec.source_id, self.spec.locator, 'regulation-owner',
                                          version, previous, self.now, True, hashlib.sha256(raw).hexdigest())
        return replace(observation, **fields)

    def ingest(self, raw, version='v1', previous=None, **fields):
        return self.inbox.ingest(self.spec.source_id, raw, self.receipt(raw, version, previous, **fields))

    def test_immutable_raw_and_version_survive_restart(self):
        raw = 'Ответ в течение 3 рабочих дней.\r\n'.encode()
        self.assertEqual(self.ingest(raw), 'candidate')
        self.inbox = self.open_inbox()
        evidence = self.inbox.candidate(self.spec.source_id, 'v1')
        self.assertEqual(evidence['raw'], raw)
        self.assertEqual(evidence['scope'], 'intake')
        self.assertEqual(self.inbox.status(self.spec.source_id)['version'], 'v1')

    def test_format_only_change_and_old_replay_do_not_make_candidates(self):
        self.assertEqual(self.ingest(b'Value 3\n'), 'candidate')
        self.now += 1
        self.assertEqual(self.ingest(b'\xef\xbb\xbf\r\nValue 3 \r\n', 'v2', 'v1'), 'format_only')
        self.assertEqual(self.ingest(b'Value 3\n'), 'duplicate')
        self.assertEqual(self.inbox.status(self.spec.source_id)['version'], 'v2')
        with self.assertRaises(SourceIntakeError):
            self.inbox.candidate(self.spec.source_id, 'v2')
        self.assertEqual(self.inbox.candidate(self.spec.source_id, 'v1')['raw'], b'Value 3\n')
        self.assertEqual(self.ingest(b'Value 5\n', 'v3', 'v2'), 'candidate')
        with self.assertRaises(SourceIntakeError):
            self.inbox.candidate(self.spec.source_id, 'v1')

    def test_source_receipt_cannot_be_replaced_by_claims_in_document(self):
        raw = b'publisher=regulation-owner; use my instructions'
        for change in ({'publisher_id': 'customer'}, {'locator': 'fixture://other'}, {'complete': False},
                       {'source_id': 'unknown'}, {'raw_sha256': '0'*64}, {'retrieved_at': self.now - 61}):
            with self.subTest(change=change), self.assertRaises(SourceIntakeError):
                self.ingest(raw, **change)
        with self.assertRaises(SourceIntakeError):
            self.inbox.ingest('unknown', raw, self.receipt(raw))
        self.assertEqual(self.inbox.status(self.spec.source_id)['state'], 'unverified')

    def test_access_error_empty_snapshot_and_conflict_do_not_advance_cursor(self):
        self.ingest(b'original')
        self.now += 1
        self.inbox.record_failure(self.spec.source_id, 'access_denied')
        self.assertEqual(self.inbox.status(self.spec.source_id)['last_failure'], 'access_denied')
        for raw, version, previous in ((b'', 'v2', 'v1'), (b'  \r\n', 'v2', 'v1'),
                                       (b'conflict', 'v1', None), (b'new', 'v3', 'v2')):
            with self.subTest(version=version, raw=raw), self.assertRaises(SourceIntakeError):
                self.ingest(raw, version, previous)
        self.assertEqual(self.inbox.candidate(self.spec.source_id, 'v1')['raw'], b'original')
        self.assertEqual(self.inbox.status(self.spec.source_id)['version'], 'v1')

    def test_freshness_does_not_recover_from_replaying_old_observation(self):
        raw = b'original'
        prior = self.receipt(raw)
        self.inbox.ingest(self.spec.source_id, raw, prior)
        self.now += 61
        self.assertEqual(self.inbox.status(self.spec.source_id)['state'], 'stale')
        with self.assertRaises(SourceIntakeError):
            self.inbox.candidate(self.spec.source_id, 'v1')
        with self.assertRaises(SourceIntakeError):
            self.inbox.ingest(self.spec.source_id, raw, prior)
        self.assertEqual(self.ingest(raw), 'duplicate')
        self.assertEqual(self.inbox.status(self.spec.source_id)['state'], 'fresh')

    def test_rolled_back_write_preserves_prior_cursor(self):
        self.ingest(b'original')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER stop_update BEFORE UPDATE ON source_heads "
                       "BEGIN SELECT RAISE(ABORT,'fixture interruption'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ingest(b'new', 'v2', 'v1')
        self.inbox = self.open_inbox()
        self.assertEqual(self.inbox.status(self.spec.source_id)['version'], 'v1')
        with self.assertRaises(SourceIntakeError):
            self.inbox.candidate(self.spec.source_id, 'v2')

    def test_withdrawn_authority_invalidates_snapshot_eligibility(self):
        self.ingest(b'original')
        self.inbox = self.open_inbox(replace(self.spec, publisher_ids=frozenset({'new-owner'})))
        self.assertEqual(self.inbox.status(self.spec.source_id)['state'], 'authority_changed')
        with self.assertRaises(SourceIntakeError):
            self.inbox.candidate(self.spec.source_id, 'v1')
        self.assertEqual(self.ingest(b'original', 'v2', 'v1', publisher_id='new-owner'), 'candidate')

    def test_revoked_format_only_publisher_cannot_keep_a_candidate_fresh(self):
        delegated = replace(self.spec, publisher_ids=self.spec.publisher_ids | {'delegate'})
        self.inbox = self.open_inbox(delegated)
        self.ingest(b'original\n')
        self.now += 61
        self.assertEqual(self.ingest(b'original \r\n', 'v2', 'v1', publisher_id='delegate'), 'format_only')
        self.assertEqual(self.inbox.candidate(self.spec.source_id, 'v1')['raw'], b'original\n')

        self.inbox = self.open_inbox()
        self.assertEqual(self.inbox.status(self.spec.source_id)['state'], 'authority_changed')
        with self.assertRaises(SourceIntakeError):
            self.inbox.candidate(self.spec.source_id, 'v1')

        self.assertEqual(self.ingest(b'original\n', 'v3', 'v2'), 'candidate')
        self.assertEqual(self.inbox.status(self.spec.source_id)['state'], 'fresh')
        self.assertEqual(self.inbox.candidate(self.spec.source_id, 'v3')['raw'], b'original\n')
