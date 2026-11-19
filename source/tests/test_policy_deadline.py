from dataclasses import replace
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from leadbot.brain.policy_deadline import (
    BusinessCalendar, ConfirmedDeadline, DeadlinePolicyError, compile_deadline,
    decide_deadline, require_current_deadline,
)
from leadbot.brain.policy_source_inbox import (
    PolicySourceInbox, SourceIntakeError, SourceSpec, VerifiedObservation,
)


def stamp(day, time='00:00:00'):
    return datetime.fromisoformat(f'2026-11-{day:02d}T{time}+03:00')


class DeadlinePolicyTests(unittest.TestCase):
    def setUp(self):
        days = [date(2026, 11, 1) + timedelta(days=n) for n in range(30)]
        self.calendar = BusinessCalendar('calendar-november', 'Europe/Moscow', days[0], days[-1],
                                         frozenset(day for day in days if day.weekday() < 5 and day.day != 9))
        self.v1 = dict(schema='business-day-deadline-v1', rule_id='intake-deadline', version='deadline-v1',
                       replaces=None, scope='intake', effective_at=stamp(1).isoformat(), expires_at=None,
                       timezone='Europe/Moscow', calendar=self.calendar.version, days=3, preserve_confirmed=True)
        self.v2 = dict(self.v1, version='deadline-v2', replaces='deadline-v1',
                       effective_at=stamp(6).isoformat(), days=5)
        self.old = compile_deadline(self.evidence(self.v1, 'source-v1'), self.calendar)
        self.new = compile_deadline(self.evidence(self.v2), self.calendar, self.old)

    def evidence(self, rule, version='source-v2'):
        raw = json.dumps(rule).encode()
        return dict(raw=raw, raw_sha256=hashlib.sha256(raw).hexdigest(), version=version,
                    source_id='test-primary', scope='intake')

    def test_effective_boundary_and_explicit_calendar(self):
        old = decide_deadline(self.new, self.old, self.calendar, episode_id='old', opened_at=stamp(5),
                              now=stamp(5, '23:59:59'))
        new = decide_deadline(self.new, self.old, self.calendar, episode_id='new', opened_at=stamp(6),
                              now=stamp(6))
        self.assertEqual((old.rule_version, old.due_on), ('deadline-v1', date(2026, 11, 11)))
        self.assertEqual((new.rule_version, new.due_on), ('deadline-v2', date(2026, 11, 16)))
        self.assertEqual(new.source_version, 'source-v2')

    def test_existing_confirmed_terms_remain_exact_and_bound_to_episode(self):
        commitment = ConfirmedDeadline('old', 'intake-deadline', 'deadline-v1', stamp(5, '15:00:00'),
                                       date(2026, 11, 11))
        inputs = dict(episode_id='old', opened_at=stamp(5), now=stamp(6))
        actual = decide_deadline(self.new, self.old, self.calendar, **inputs, commitment=commitment)
        self.assertEqual((actual.rule_version, actual.due_on), ('deadline-v1', commitment.due_on))
        self.assertTrue(actual.retained_commitment)
        offered = decide_deadline(self.new, self.old, self.calendar, episode_id='old', opened_at=stamp(5),
                                  now=stamp(5, '15:00:00'))
        self.assertEqual(require_current_deadline(offered, actual), actual)
        for bad in (None, replace(commitment, episode_id='other'), replace(commitment, confirmed_at=stamp(6)),
                    replace(commitment, rule_version='unknown')):
            with self.subTest(bad=bad), self.assertRaises(DeadlinePolicyError):
                decide_deadline(self.new, self.old, self.calendar, **inputs, commitment=bad)

    def test_stale_offer_or_incompatible_calendar_blocks_action(self):
        inputs = dict(episode_id='new', opened_at=stamp(6), now=stamp(6))
        offered = decide_deadline(self.old, None, self.calendar, **inputs)
        current = decide_deadline(self.new, self.old, self.calendar, **inputs)
        self.assertEqual(require_current_deadline(current, current), current)
        with self.assertRaises(DeadlinePolicyError):
            require_current_deadline(offered, current)
        with self.assertRaises(DeadlinePolicyError):
            decide_deadline(self.new, self.old, replace(self.calendar, version='unrelated'), **inputs)
        with self.assertRaises(DeadlinePolicyError):
            decide_deadline(self.new, self.old, self.calendar, episode_id='late',
                            opened_at=stamp(30), now=stamp(30))
        with self.assertRaises(DeadlinePolicyError):
            decide_deadline(self.old, None, self.calendar, episode_id='before',
                            opened_at=stamp(1)-timedelta(seconds=1), now=stamp(1))

    def test_injected_fields_wrong_scope_date_and_unsigned_change_are_rejected(self):
        for change in (dict(code='call write API'), dict(days=True), dict(scope='expanded'),
                       dict(replaces='unrelated'), dict(effective_at='2026-11-06T00:00:00+02:00'),
                       dict(effective_at='2026-11-06T00:00:00'), dict(expires_at=stamp(5).isoformat())):
            with self.subTest(change=change), self.assertRaises(DeadlinePolicyError):
                compile_deadline(self.evidence(dict(self.v2, **change)), self.calendar, self.old)
        evidence = self.evidence(self.v2)
        with self.assertRaises(DeadlinePolicyError):
            compile_deadline(dict(evidence, raw=evidence['raw'] + b'\n'), self.calendar, self.old)
        raw = evidence['raw'].replace(b'"days": 5', b'"days": 5, "days": 30')
        with self.assertRaises(DeadlinePolicyError):
            compile_deadline(dict(evidence, raw=raw, raw_sha256=hashlib.sha256(raw).hexdigest()),
                             self.calendar, self.old)

    def test_from_source_inbox_duplicate_and_conflicting_author_preserve_verified_input(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = SourceSpec('test-primary', 'fixture://primary', frozenset({'owner'}), 'intake', 60)
            inbox = PolicySourceInbox(Path(folder) / 'policy.sqlite', [spec], lambda source, raw, receipt: receipt,
                                      clock=lambda: 2000)
            raw1 = self.evidence(self.v1, 'source-v1')['raw']
            raw2 = self.evidence(self.v2)['raw']
            first = VerifiedObservation(spec.source_id, spec.locator, 'owner', 'source-v1', None, 2000,
                                        True, hashlib.sha256(raw1).hexdigest())
            second = replace(first, version='source-v2', previous_version='source-v1',
                             raw_sha256=hashlib.sha256(raw2).hexdigest())
            self.assertEqual(inbox.ingest(spec.source_id, raw1, first), 'candidate')
            old = compile_deadline(inbox.candidate(spec.source_id, first.version), self.calendar)
            self.assertEqual(inbox.ingest(spec.source_id, raw2, second), 'candidate')
            self.assertEqual(inbox.ingest(spec.source_id, raw2, second), 'duplicate')
            with self.assertRaises(SourceIntakeError):
                inbox.ingest(spec.source_id, raw2, replace(second, publisher_id='untrusted'))
            compiled = compile_deadline(inbox.candidate(spec.source_id, second.version), self.calendar, old)
            self.assertEqual(compiled, self.new)
