import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_experienced_dialogues import reviewed_roster


class ExperienceRosterTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(base500_registry=[dict(case=n, cid='synthetic-old-'+str(n)) for n in range(500)])
        self.closed = dict(case=900, cid='synthetic-new', historical_review_closed=True,
                           full_text_read=True, primary_rules_reviewed=['DOC-source'])

    def test_new_canonical_full_review_is_indexed_without_hardcoded_total(self):
        roster = reviewed_roster(self.identity, [self.closed])
        self.assertEqual(len(roster), 501)
        self.assertEqual(roster[-1]['cid'], 'synthetic-new')

    def test_unclosed_or_unreviewed_primary_cannot_self_admit(self):
        for field, value in [('historical_review_closed', False), ('full_text_read', False),
                             ('primary_rules_reviewed', []), ('primary_rules_reviewed', 'claimed'),
                             ('primary_rules_reviewed', [{'id': 'claimed'}])]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                reviewed_roster(self.identity, [dict(self.closed, **{field: value})])

    def test_canonical_full_primary_source_rows_keep_their_actual_schema(self):
        row = dict(self.closed, primary_rules_reviewed=[dict(id='DOC-source', text='Прочитанный первичный регламент')])
        self.assertEqual(len(reviewed_roster(self.identity, [row])), 501)

    def test_duplicate_and_conflicting_identity_are_rejected(self):
        with self.assertRaises(ValueError):
            reviewed_roster(self.identity, [self.closed, self.closed])
        with self.assertRaises(ValueError):
            reviewed_roster(self.identity, [dict(self.closed, cid='synthetic-old-2')])
