import base64
from dataclasses import replace
import hmac
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from leadbot.brain.policy_attestations import DOMAIN, PolicyAttestations
from leadbot.brain.policy_source_inbox import PolicySourceInbox, SourceIntakeError, SourceSpec
from leadbot.brain.policy_source_worker import poll_sources, snapshot_filename
from leadbot.brain.source_protocol import encode, sha


class PolicySourceWorkerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.handoff = root / 'handoff'
        self.handoff.mkdir(mode=0o700)
        self.path = root / 'inbox.sqlite'
        self.now = 2000
        self.source = SourceSpec('service-policy', 'fixture://primary', frozenset({'owner'}), 'intake', 60)
        self.other = SourceSpec('region-policy', 'fixture://region', frozenset({'owner'}), 'intake', 60)
        self.keys = {('source', 'intake', 'owner'): b's' * 32,
                     ('normative', 'intake', 'compiler'): b'n' * 32,
                     ('release', 'intake', 'reviewer'): b'r' * 32}
        self.verifier = PolicyAttestations(self.keys, {'intake': frozenset({'baseline'})}, clock=lambda: self.now)
        self.inbox = self.open_inbox()

    def open_inbox(self):
        return PolicySourceInbox(self.path, [self.source, self.other], self.verifier.verify_source,
                                 clock=lambda: self.now)

    def envelope(self, raw, version, previous, *, source=None, retrieved_at=None, publisher='owner'):
        source = source or self.source
        claims = encode(dict(source_id=source.source_id, locator=source.locator, publisher_id=publisher,
                             version=version, previous_version=previous, raw_sha256=sha(raw), complete=True,
                             issued_at=self.now, retrieved_at=self.now if retrieved_at is None else retrieved_at))
        message = DOMAIN + f'source\0{source.scope}\0{publisher}\0'.encode() + claims
        mac = hmac.digest(self.keys[('source', source.scope, publisher)], message, 'sha256')
        return dict(issuer=publisher, raw_b64=base64.b64encode(raw).decode(),
                    claims_b64=base64.b64encode(claims).decode(), mac_b64=base64.b64encode(mac).decode())

    def place(self, cursor, envelope, *, source=None):
        source = source or self.source
        path = self.handoff / snapshot_filename(source.source_id, cursor)
        staged = self.handoff / 'fixture.tmp'
        staged.touch(mode=0o600, exist_ok=False)
        staged.write_bytes(encode(envelope))
        staged.replace(path)
        return path

    def poll(self):
        return poll_sources(self.inbox, self.handoff, [self.source.source_id])[self.source.source_id]

    def test_restart_reads_only_the_next_cursor_and_preserves_raw(self):
        self.place(None, self.envelope(b'First\r\n', 'v1', None))
        self.place('v1', self.envelope(b'Changed\n', 'v2', 'v1'))
        self.assertEqual(self.poll(), 'candidate')
        self.assertEqual(self.inbox.candidate(self.source.source_id, 'v1')['raw'], b'First\r\n')
        self.inbox = self.open_inbox()
        self.assertEqual(self.poll(), 'candidate')
        self.assertEqual(self.inbox.candidate(self.source.source_id, 'v2')['raw'], b'Changed\n')
        self.assertEqual(self.poll(), 'awaiting_snapshot')

    def test_signed_duplicate_and_format_only_do_not_create_a_second_candidate(self):
        self.place(None, self.envelope(b'First\n', 'v1', None))
        self.assertEqual(self.poll(), 'candidate')
        self.now += 1
        self.place('v1', self.envelope(b'First\n', 'v1', None))
        self.assertEqual(self.poll(), 'duplicate')
        self.now += 1
        self.place('v1', self.envelope(b'\r\nFirst  \r\n', 'v2', 'v1'))
        self.assertEqual(self.poll(), 'format_only')
        self.assertEqual(self.inbox.candidate(self.source.source_id, 'v1')['raw'], b'First\n')
        self.assertEqual(self.inbox.status(self.source.source_id)['version'], 'v2')

    def test_next_signed_snapshot_recovers_a_revoked_publisher_at_the_same_cursor(self):
        self.place(None, self.envelope(b'First', 'v1', None))
        self.assertEqual(self.poll(), 'candidate')

        self.now += 1
        self.source = replace(self.source, publisher_ids=frozenset({'successor'}))
        self.keys[('source', 'intake', 'successor')] = b'v' * 32
        self.verifier = PolicyAttestations(self.keys, {'intake': frozenset({'baseline'})}, clock=lambda: self.now)
        self.inbox = self.open_inbox()
        self.assertEqual(self.poll(), 'authority_changed')
        with self.assertRaises(SourceIntakeError):
            self.inbox.candidate(self.source.source_id, 'v1')

        rejected = {
            'revoked publisher': self.envelope(b'Stale authority', 'v2', 'v1'),
            'wrong predecessor': self.envelope(b'Wrong predecessor', 'v2', 'foreign', publisher='successor'),
        }
        for reason, envelope in rejected.items():
            with self.subTest(reason=reason):
                self.place('v1', envelope)
                outcome = self.poll()
                self.assertEqual(self.inbox.status(self.source.source_id)['version'], 'v1')
                self.assertEqual(outcome, 'unverified_snapshot')

        self.place('v1', self.envelope(b'First\n', 'v2', 'v1', publisher='successor'))
        self.assertEqual(self.poll(), 'candidate')
        self.inbox = self.open_inbox()
        self.assertEqual(self.inbox.candidate(self.source.source_id, 'v2')['publisher_id'], 'successor')
        self.assertEqual(self.poll(), 'awaiting_snapshot')

    def test_changed_source_locator_or_scope_does_not_read_the_old_handoff(self):
        self.place(None, self.envelope(b'First', 'v1', None))
        self.assertEqual(self.poll(), 'candidate')
        self.place('v1', self.envelope(b'Second', 'v2', 'v1'))
        original = self.source
        for change in (dict(locator='fixture://different'), dict(scope='different')):
            with self.subTest(change=change):
                self.source = replace(original, **change)
                self.inbox = self.open_inbox()
                with patch('leadbot.brain.policy_source_worker._read_snapshot') as read:
                    self.assertEqual(self.poll(), 'authority_changed')
                    read.assert_not_called()
                self.assertEqual(self.inbox.status(self.source.source_id)['version'], 'v1')

    def test_bad_signature_wrong_predecessor_and_stale_snapshot_preserve_cursor(self):
        self.place(None, self.envelope(b'First', 'v1', None))
        self.assertEqual(self.poll(), 'candidate')
        self.now += 61
        raw = b'Changed'
        tampered = dict(self.envelope(raw, 'v2', 'v1'), mac_b64=base64.b64encode(b'!' * 32).decode())
        rejected = {'signature': tampered, 'predecessor': self.envelope(raw, 'v3', 'v2'),
                    'age': self.envelope(raw, 'v2', 'v1', retrieved_at=self.now - 61),
                    'authority': self.envelope(raw, 'v2', 'v1', source=self.other)}
        for reason, envelope in rejected.items():
            with self.subTest(reason=reason):
                self.place('v1', envelope)
                self.assertEqual(self.poll(), 'unverified_snapshot')
                self.assertEqual(self.inbox.status(self.source.source_id),
                                 dict(version='v1', state='stale', last_failure='unverified_snapshot'))

    def test_malformed_and_empty_envelopes_do_not_block_other_sources(self):
        self.place(None, dict(issuer='owner'))
        self.place(None, self.envelope(b'Region', 'r1', None, source=self.other), source=self.other)
        self.assertEqual(poll_sources(self.inbox, self.handoff, [self.source.source_id, self.other.source_id]),
                         {self.source.source_id: 'schema_changed', self.other.source_id: 'candidate'})
        self.place(None, self.envelope(b'', 'v1', None))
        self.assertEqual(self.poll(), 'empty')
        self.assertIsNone(self.inbox.status(self.source.source_id)['version'])

    def test_access_restrictions_and_unknown_sources_are_enforced_before_ingest(self):
        path = self.place(None, self.envelope(b'First', 'v1', None))
        with self.assertRaises(ValueError):
            poll_sources(self.inbox, self.handoff, [self.source.source_id, 'unregistered'])
        self.assertIsNone(self.inbox.status(self.source.source_id)['version'])
        path.chmod(0o644)
        self.assertEqual(self.poll(), 'access_denied')
        target = self.handoff / 'other-file'
        path.rename(target)
        target.chmod(0o600)
        path.symlink_to(target)
        self.assertEqual(self.poll(), 'unavailable')
        path.unlink()
        path.mkdir(mode=0o700)
        self.assertEqual(self.poll(), 'access_denied')
        self.assertIsNone(self.inbox.status(self.source.source_id)['version'])
