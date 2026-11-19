"""A damaged prepared journal cannot manufacture a trusted negative fence."""
import json
import unittest

import test_native_revocation296 as fixture
from research_index import Header, IndexFailure
from source_protocol import SourceError


class WithdrawalJournalTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.NativeRevocationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.f.start()
        self.f.exporter.run(max_cases=20, force=True)
        with self.f.exporter.db() as db:
            self.plan = json.loads(db.execute('SELECT value FROM prepared WHERE id=1').fetchone()[0])

    def replace_plan(self, header, source):
        self.plan.update(header_type='source', header=vars(header), source=source)
        with self.f.exporter.db() as db:
            db.execute('UPDATE prepared SET value=? WHERE id=1', (json.dumps(self.plan),))

    def test_invalid_negative_header_cannot_withdraw_another_source_under_hold(self):
        self.replace_plan(Header('old-b', 1, '', (), (), '', op='delete', identity_complete=False), None)
        try:
            self.f.exporter._publish({})
        except IndexFailure:
            pass
        self.assertNotIn('old-b', self.f.index.revocations(('old-b',),
            expected_version=self.f.index.state()['version']))

    def test_legacy_negative_header_with_a_body_is_rejected_before_fencing(self):
        self.replace_plan(Header('old-b', 1, 'synthetic-group', (), (), '', op='delete'),
                          {'messages': ['not an admitted negative source']})
        with self.assertRaises(SourceError):
            self.f.exporter._publish({})
        self.assertNotIn('old-b', self.f.index.revocations(('old-b',),
            expected_version=self.f.index.state()['version']))


if __name__ == '__main__':
    unittest.main()
