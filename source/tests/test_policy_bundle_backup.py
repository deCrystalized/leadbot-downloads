from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from leadbot.brain.policy_bundle_backup import BackupError, restore, snapshot
from leadbot.brain.policy_bundles import BundleError, PolicyBundles, RuleRequirement
from leadbot.brain.policy_release_worker import publish_due
import test_policy_bundles as fixture


class PolicyBackupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'policy.sqlite'
        self.copy = self.root / 'checkpoint.sqlite'
        self.recovered = self.root / 'restored.sqlite'
        self.now = 5
        self.bundles = self.open(self.source)

    def open(self, path):
        def verify_source(payload, receipt):
            return fixture.sign(fixture.SOURCE_KEY, payload) == receipt

        def verify_checks(manifest, active, receipt):
            return fixture.checks_signature(hashlib.sha256(manifest).hexdigest(), active) == receipt

        return PolicyBundles(path, verify_source, verify_checks, clock=lambda: self.now)

    def stage(self, version, replaces, effective_at):
        requirement = RuleRequirement('intake', version, replaces, 'regulation', version, '1' * 64, effective_at)
        self.bundles.register(requirement, fixture.source_signature(requirement))
        return self.bundles.prepare('intake', version, {
            field: (field + version).encode() for field in ('configuration', 'index', 'rules', 'templates')
        })

    def test_restores_wal_snapshot_and_resumes_one_due_publication(self):
        with closing(sqlite3.connect(self.source)) as writer:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
            old = self.stage('v1', None, 0)
            self.bundles.activate('intake', 'v1', old, fixture.checks_signature(old, None), expected_active=None)
            due = self.stage('v2', 'v1', 10)
            self.bundles.schedule('intake', 'v2', due)
            writer.execute("DELETE FROM scheduled_bundles WHERE scope='intake' AND version='v2'")
            saved = snapshot(self.source, self.copy, max_seconds=5)
            writer.commit()
        original = self.bundles.active('intake')
        self.assertEqual(original.manifest_sha256, old)
        recovery = restore(self.copy, self.recovered, expected_sha256=saved['sha256'], max_seconds=5)
        self.assertEqual(recovery['sha256'], saved['sha256'])
        self.assertEqual(recovery['bytes'], saved['bytes'])
        self.assertEqual(self.copy.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root / 'checkpoint.sqlite-wal').exists())
        reopened = self.open(self.recovered)
        self.assertEqual(reopened.active('intake'), original)
        self.now = 10
        self.assertIsNone(self.bundles.due('intake'))
        self.assertEqual(reopened.due('intake').manifest_sha256, due)
        with self.assertRaises(BundleError):
            reopened.require_current(original)
        signed = lambda transition: fixture.checks_signature(transition.manifest_sha256, transition.expected_active)
        self.assertEqual(publish_due(reopened, ['intake'], signed), {'intake': 'activated'})
        self.assertEqual(publish_due(self.open(self.recovered), ['intake'], signed), {'intake': 'idle'})
        self.assertEqual(reopened.active('intake').manifest_sha256, due)
        with closing(sqlite3.connect(self.recovered)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM publication_events WHERE version='v2'").fetchone(), (1,))

    def test_wrong_hash_or_existing_destination_cannot_publish(self):
        saved = snapshot(self.source, self.copy, max_seconds=5)
        with self.assertRaisesRegex(BackupError, 'approved hash'):
            restore(self.copy, self.recovered, expected_sha256='0' * 64, max_seconds=5)
        self.assertFalse(self.recovered.exists())
        self.recovered.write_bytes(b'keep existing')
        with self.assertRaises(FileExistsError):
            restore(self.copy, self.recovered, expected_sha256=saved['sha256'], max_seconds=5)
        self.assertEqual(self.recovered.read_bytes(), b'keep existing')
        self.assertFalse(list(self.root.glob('.policy-bundle-*')))

    def test_unrelated_database_and_symlink_are_rejected(self):
        bad = self.root / 'unrelated.sqlite'
        with closing(sqlite3.connect(bad)) as db:
            db.execute('CREATE TABLE unrelated(value TEXT)')
        bad.chmod(0o600)
        with self.assertRaisesRegex(BackupError, 'Unexpected policy'):
            snapshot(bad, self.copy, max_seconds=5)
        alias = self.root / 'link.sqlite'
        alias.symlink_to(self.source)
        with self.assertRaises(BackupError):
            snapshot(alias, self.copy, max_seconds=5)
        self.assertFalse(self.copy.exists())

    def test_valid_sqlite_with_damaged_scheduled_bundle_is_not_a_checkpoint(self):
        old = self.stage('v1', None, 0)
        self.bundles.activate('intake', 'v1', old, fixture.checks_signature(old, None), expected_active=None)
        due = self.stage('v2', 'v1', 10)
        self.bundles.schedule('intake', 'v2', due)
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("UPDATE bundle_parts SET content=? WHERE version='v2' AND kind='rules'",
                       (b'damaged rules',))
            self.assertEqual(db.execute('PRAGMA quick_check').fetchall(), [('ok',)])
            self.assertIsNone(db.execute('PRAGMA foreign_key_check').fetchone())
        original = self.source.read_bytes()
        approved_hash = hashlib.sha256(original).hexdigest()

        for mode in ('snapshot', 'restore'):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(BackupError, 'bundle manifest'):
                    if mode == 'snapshot':
                        snapshot(self.source, self.copy, max_seconds=5)
                    else:
                        restore(self.source, self.recovered, expected_sha256=approved_hash, max_seconds=5)
        self.assertFalse(self.copy.exists())
        self.assertFalse(self.recovered.exists())
        self.assertFalse(list(self.root.glob('.policy-bundle-*')))
        self.assertEqual(self.source.read_bytes(), original)

    def test_interrupted_publication_leaves_no_destination(self):
        with patch('leadbot.brain.policy_bundle_backup.os.link', side_effect=OSError('fixture interruption')):
            with self.assertRaisesRegex(OSError, 'fixture interruption'):
                snapshot(self.source, self.copy, max_seconds=5)
        self.assertFalse(os.path.lexists(self.copy))
        self.assertFalse(list(self.root.glob('.policy-bundle-*')))
