from contextlib import closing
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from leadbot.brain.policy_bundles import BundleError, PolicyBundles, RuleRequirement
from leadbot.brain.policy_deadline import (
    BusinessCalendar, ConfirmedDeadline, compile_deadline, decide_deadline,
)
from leadbot.brain.policy_release_worker import publish_due
from leadbot.brain.policy_source_inbox import (
    PolicySourceInbox, SourceIntakeError, SourceSpec, VerifiedObservation,
)


SOURCE_KEY = b'fixture-only-source-signature'
CHECKS_KEY = b'fixture-only-separate-checks-signature'


def sign(key, payload):
    return hmac.digest(key, payload, 'sha256')


def checks_signature(digest, active):
    return sign(CHECKS_KEY, f'{digest}\0{active}'.encode())


def source_signature(rule):
    return sign(SOURCE_KEY, json.dumps(asdict(rule), sort_keys=True, separators=(',', ':')).encode())


class PolicyBundleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'bundles.sqlite'
        self.now = 5
        self.store = self.reopen()
        self.v1 = RuleRequirement('intake', 'v1', None, 'primary', 'snapshot-1', '1'*64, 0)
        self.v2 = RuleRequirement('intake', 'v2', 'v1', 'primary', 'snapshot-2', '2'*64, 10)
        self.parts = dict(rules=b'compiled-v1', index=b'index-v1',
                          templates=b'templates-v1', configuration=b'config-v1')

    def reopen(self):
        def verify_source(payload, receipt):
            return hmac.compare_digest(sign(SOURCE_KEY, payload), receipt)

        def verify_checks(manifest, active, receipt):
            digest = hashlib.sha256(manifest).hexdigest()
            return hmac.compare_digest(checks_signature(digest, active), receipt)

        return PolicyBundles(self.path, verify_source, verify_checks, clock=lambda: self.now)

    def stage(self, rule, parts=None):
        self.store.register(rule, source_signature(rule))
        return self.store.prepare(rule.scope, rule.version, parts or self.parts)

    def activate(self, rule, digest, previous=None):
        return self.store.activate(rule.scope, rule.version, digest, checks_signature(digest, previous),
                                   expected_active=previous)

    def test_registered_future_version_activates_only_at_boundary(self):
        old = self.stage(self.v1)
        self.assertEqual(self.activate(self.v1, old), 'activated')
        offered = self.store.active('intake')
        new = self.stage(self.v2, dict(self.parts, rules=b'compiled-v2'))
        with self.assertRaises(BundleError):
            self.activate(self.v2, new, old)
        self.assertEqual(self.store.require_current(offered), offered)
        self.now = 10
        with self.assertRaises(BundleError):
            self.store.active('intake')
        self.assertEqual(self.activate(self.v2, new, old), 'activated')
        self.assertEqual(self.activate(self.v2, new, old), 'duplicate')
        with self.assertRaises(BundleError):
            self.store.require_current(offered)
        self.assertEqual(self.store.active('intake').manifest_sha256, new)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM publication_events').fetchone()[0], 2)

    def test_missing_or_tampered_components_and_mismatched_checks_fail(self):
        self.store.register(self.v1, source_signature(self.v1))
        with self.assertRaises(BundleError):
            self.store.prepare('intake', 'v1', {'rules': b'v1'})
        good = self.store.prepare('intake', 'v1', self.parts)
        other = self.store.prepare('intake', 'v1', dict(self.parts, index=b'another-index'))
        with self.assertRaises(BundleError):
            self.store.activate('intake', 'v1', other, checks_signature(good, None), expected_active=None)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE bundle_parts SET content=? WHERE digest=? AND kind='index'", (b'mutated', good))
        with self.assertRaises(BundleError):
            self.activate(self.v1, good)

    def test_interrupted_activation_does_not_resurrect_expired_scope(self):
        old = self.stage(self.v1)
        self.activate(self.v1, old)
        isolated = replace(self.v1, scope='another-scope')
        other = self.stage(isolated)
        self.activate(isolated, other)
        new = self.stage(self.v2)
        self.now = 10
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER failed_activation BEFORE INSERT ON publication_events "
                       "WHEN NEW.version='v2' BEGIN SELECT RAISE(ABORT,'fixture crash'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.activate(self.v2, new, old)
        self.store = self.reopen()
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT version FROM active_bundles WHERE scope='intake'").fetchone(), ('v1',))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM publication_events WHERE version='v2'").fetchone()[0], 0)
            db.execute('DROP TRIGGER failed_activation')
        with self.assertRaises(BundleError):
            self.store.active('intake')
        with self.assertRaises(BundleError):
            self.activate(self.v1, old, old)
        self.assertEqual(self.store.active('another-scope').manifest_sha256, other)
        self.assertEqual(self.activate(self.v2, new, old), 'activated')

    def test_same_normative_version_rollback_requires_a_new_exact_transition(self):
        first = self.stage(self.v1)
        fixed = self.stage(self.v1, dict(self.parts, templates=b'fixed-v1'))
        self.activate(self.v1, first)
        self.activate(self.v1, fixed, first)
        with self.assertRaises(BundleError):
            self.activate(self.v1, first)
        self.assertEqual(self.activate(self.v1, first, fixed), 'activated')
        self.assertEqual(self.store.active('intake').manifest_sha256, first)

    def test_untrusted_conflicting_or_expired_requirement(self):
        with self.assertRaises(BundleError):
            self.store.register(self.v1, b'untrusted')
        expires = replace(self.v1, expires_at=8)
        digest = self.stage(expires)
        self.activate(expires, digest)
        with self.assertRaises(BundleError):
            self.store.register(self.v1, source_signature(self.v1))
        with self.assertRaises(BundleError):
            self.stage(self.v2)
        self.now = 8
        with self.assertRaises(BundleError):
            self.store.active('intake')

    def test_due_worker_recovers_schedule_and_publishes_only_once(self):
        old = self.stage(self.v1)
        self.activate(self.v1, old)
        new = self.stage(self.v2)
        self.assertEqual(self.store.schedule('intake', 'v2', new), 'scheduled')
        self.assertEqual(self.store.schedule('intake', 'v2', new), 'duplicate')
        requests = []

        def receipt(due):
            requests.append(due)
            return checks_signature(due.manifest_sha256, due.expected_active)

        self.assertEqual(publish_due(self.store, ['intake'], receipt), {'intake': 'idle'})
        self.assertFalse(requests)
        self.now = 10
        self.store = self.reopen()
        self.assertEqual(publish_due(self.store, ['intake'], lambda due: None), {'intake': 'awaiting_checks'})
        with self.assertRaises(BundleError):
            self.store.active('intake')
        self.assertEqual(publish_due(self.store, ['intake'], receipt), {'intake': 'activated'})
        self.store = self.reopen()
        self.assertEqual(publish_due(self.store, ['intake'], receipt), {'intake': 'idle'})
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.store.active('intake').manifest_sha256, new)

    def test_due_candidate_replaced_during_review_cannot_be_published(self):
        first = self.stage(self.v1)
        fixed = self.stage(self.v1, dict(self.parts, index=b'corrected-index'))
        self.store.schedule('intake', 'v1', first)
        with self.assertRaises(BundleError):
            self.store.schedule('intake', 'v1', fixed)

        def replace_choice(due):
            self.assertEqual(due.manifest_sha256, first)
            self.store.schedule('intake', 'v1', fixed, replaces=first)
            return checks_signature(due.manifest_sha256, due.expected_active)

        self.assertEqual(publish_due(self.store, ['intake'], replace_choice), {'intake': 'held'})
        with self.assertRaises(BundleError):
            self.store.active('intake')
        self.assertEqual(publish_due(self.store, ['intake'], lambda due:
                                    checks_signature(due.manifest_sha256, due.expected_active)),
                         {'intake': 'activated'})
        self.assertEqual(self.store.active('intake').manifest_sha256, fixed)

    def test_due_candidate_superseded_while_verifying_receipt_cannot_be_published(self):
        old = self.stage(self.v1)
        self.activate(self.v1, old)
        pending = self.stage(self.v2)
        self.store.schedule('intake', 'v2', pending)
        successor = replace(self.v2, version='v3', replaces='v2', source_version='snapshot-3',
                            source_sha256='3' * 64, effective_at=20)
        next_digest = self.stage(successor)
        self.store.schedule('intake', 'v3', next_digest)
        self.now = 10
        verify = self.store.verify_checks

        def verify_across_boundary(*args):
            result = verify(*args)
            self.now = 20
            return result

        self.store.verify_checks = verify_across_boundary

        def receipt(due):
            self.assertEqual(due.expected_active, old)
            return checks_signature(due.manifest_sha256, due.expected_active)

        self.assertEqual(publish_due(self.store, ['intake'], receipt), {'intake': 'held'})
        with self.assertRaises(BundleError):
            self.store.active('intake')
        self.store = self.reopen()
        self.assertEqual(publish_due(self.store, ['intake'], receipt), {'intake': 'activated'})
        self.assertEqual(self.store.active('intake').manifest_sha256, next_digest)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT version,published_at FROM publication_events ORDER BY rowid')
                             .fetchall(), [('v1', 5), ('v3', 20)])

    def test_manual_activation_cannot_publish_after_expiry_during_receipt_verification(self):
        expiring = replace(self.v1, expires_at=8)
        candidate = self.stage(expiring)
        verify = self.store.verify_checks

        def verify_until_expiry(*args):
            result = verify(*args)
            self.now = 8
            return result

        self.store.verify_checks = verify_until_expiry
        with self.assertRaises(BundleError):
            self.activate(expiring, candidate)
        self.store = self.reopen()
        with self.assertRaises(BundleError):
            self.store.active('intake')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM active_bundles').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM publication_events').fetchone()[0], 0)

    def test_due_worker_keeps_superseded_and_manually_replaced_jobs_inert(self):
        old = self.stage(self.v1)
        self.store.schedule('intake', 'v1', old)
        new = self.stage(self.v2)
        self.now = 10

        def unexpected(_):
            self.fail('An inactive schedule requested a receipt')

        self.assertEqual(publish_due(self.store, ['intake'], unexpected), {'intake': 'idle'})
        self.store.schedule('intake', 'v2', new)
        corrected = self.stage(self.v2, dict(self.parts, templates=b'updated-v2'))
        self.activate(self.v2, corrected)
        self.assertEqual(publish_due(self.store, ['intake'], unexpected), {'intake': 'idle'})
        self.assertEqual(self.store.active('intake').manifest_sha256, corrected)

    def test_unavailable_receipt_does_not_block_another_scope(self):
        first = self.stage(self.v1)
        other = replace(self.v1, scope='other')
        second = self.stage(other)
        self.store.schedule('intake', 'v1', first)
        self.store.schedule('other', 'v1', second)

        def receipt(due):
            if due.scope == 'intake':
                raise TimeoutError('fixture unavailable')
            return checks_signature(due.manifest_sha256, due.expected_active)

        self.assertEqual(publish_due(self.store, ['intake', 'other'], receipt),
                         {'intake': 'retry', 'other': 'activated'})
        self.assertEqual(self.store.active('other').manifest_sha256, second)
        with self.assertRaises(BundleError):
            self.store.active('intake')

    def test_master_deadline_from_source_through_publish_and_action_snapshot(self):
        def stamp(day):
            return datetime.fromisoformat(f'2026-11-{day:02d}T00:00:00+03:00')

        dates = [date(2026, 11, 1) + timedelta(days=i) for i in range(30)]
        calendar = BusinessCalendar('cal-11', 'Europe/Moscow', dates[0], dates[-1],
                                    frozenset(day for day in dates if day.weekday() < 5))
        spec = SourceSpec('primary', 'fixture://approved', frozenset({'owner'}), 'intake', 60)
        inbox = PolicySourceInbox(self.path.with_name('inbox.sqlite'), [spec],
                                  lambda source, raw, receipt: receipt, clock=lambda: self.now)

        def ingest(rule, source_version, previous, publisher='owner'):
            raw = json.dumps(rule).encode()
            observation = VerifiedObservation(spec.source_id, spec.locator, publisher, source_version,
                                              previous, self.now, True, hashlib.sha256(raw).hexdigest())
            return inbox.ingest(spec.source_id, raw, observation)

        def stage(rule):
            requirement = RuleRequirement(rule.scope, rule.version, rule.replaces, rule.source_id,
                                          rule.source_version, rule.source_sha256, int(rule.effective.timestamp()))
            evidence = inbox.candidate(spec.source_id, rule.source_version)
            digest = self.stage(requirement, dict(self.parts, rules=evidence['raw'],
                                                 index=f'index-{rule.version}'.encode(),
                                                 templates=f'templates-{rule.version}'.encode(),
                                                 configuration=f'config-{rule.version}'.encode()))
            return requirement, digest

        base = dict(schema='business-day-deadline-v1', rule_id='response', version='v1', replaces=None,
                    scope='intake', effective_at=stamp(1).isoformat(), expires_at=None, timezone='Europe/Moscow',
                    calendar='cal-11', days=3, preserve_confirmed=True)
        future = dict(base, version='v2', replaces='v1', effective_at=stamp(6).isoformat(), days=5)
        self.now = stamp(5).timestamp()
        self.assertEqual(ingest(base, 's1', None), 'candidate')
        first = compile_deadline(inbox.candidate(spec.source_id, 's1'), calendar)
        req1, digest1 = stage(first)
        self.activate(req1, digest1)
        before = self.store.active('intake')
        old = decide_deadline(first, None, calendar, episode_id='old', opened_at=stamp(5), now=stamp(5))
        commitment = ConfirmedDeadline('old', first.rule_id, first.version, stamp(5), old.due_on)
        self.assertEqual(ingest(future, 's2', 's1'), 'candidate')
        second = compile_deadline(inbox.candidate(spec.source_id, 's2'), calendar, first)
        req2, digest2 = stage(second)
        self.assertEqual(ingest(future, 's2', 's1'), 'duplicate')
        with self.assertRaises(SourceIntakeError):
            ingest(dict(future, days=30), 's3', 's2', publisher='customer')
        self.now = stamp(6).timestamp()
        self.activate(req2, digest2, digest1)
        with self.assertRaises(BundleError):
            self.store.require_current(before)
        active = self.store.require_current(self.store.active('intake'))
        self.assertEqual(dict(active.parts)['rules'], json.dumps(future).encode())
        new = decide_deadline(second, first, calendar, episode_id='new', opened_at=stamp(6), now=stamp(6))
        keep = decide_deadline(second, first, calendar, episode_id='old', opened_at=stamp(5), now=stamp(6),
                               commitment=commitment)
        self.assertEqual((new.due_on, keep.due_on), (date(2026, 11, 13), date(2026, 11, 10)))
