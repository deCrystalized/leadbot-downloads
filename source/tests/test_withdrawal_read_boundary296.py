"""A concurrent negative fence must win at raw read/search return boundaries."""
import unittest

import test_research_index206 as fixture
from research_index import IndexFailure, Removal


class WithdrawalReadBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.IndexTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.apply(self.f.record())
        self.index = self.f.index

    def fence_during_guard(self):
        original = self.index.guard

        def guard(header):
            self.index.withdraw(Removal(header.cid, 2), expected_version=self.index.state()['version'])
            return original(header)

        self.index.guard = guard

    def test_withdrawal_during_raw_identity_check_blocks_body_read(self):
        self.fence_during_guard()
        statements = []
        original = self.index.connect

        def connect(readonly=False):
            context = original(readonly)
            return TracedConnection(context, statements)

        self.index.connect = connect
        with self.assertRaises(IndexFailure):
            self.f.read()
        self.assertFalse(any('SELECT payload FROM sources' in sql for sql in statements))

    def test_withdrawal_during_search_identity_check_cannot_return_old_hit(self):
        self.fence_during_guard()
        with self.assertRaises(IndexFailure):
            self.f.search()

    def test_withdrawal_during_stored_body_validation_cannot_return_body(self):
        original = self.index._record

        def record(header, body):
            self.index.withdraw(Removal(header.cid, 2), expected_version=self.index.state()['version'])
            return original(header, body)

        self.index._record = record
        with self.assertRaises(IndexFailure):
            self.f.read()


class TracedConnection:
    def __init__(self, context, statements):
        self.context, self.statements = context, statements

    def __enter__(self):
        self.connection = self.context.__enter__()
        self.connection.set_trace_callback(self.statements.append)
        return self.connection

    def __exit__(self, *args):
        return self.context.__exit__(*args)


if __name__ == '__main__':
    unittest.main()
