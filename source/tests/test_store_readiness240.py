import contextlib
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from assistant_store import Store


class StoreReadiness240Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'assistant.sqlite3'
        self.store = Store(self.path)

    def test_actual_housekeeping_queries_use_range_indexes_not_payload_scans(self):
        statements = []; original = self.store.connect
        @contextlib.contextmanager
        def observed():
            with original() as db:
                db.set_trace_callback(statements.append); yield db
        with patch.object(self.store, 'connect', observed): self.store.purge()
        deletes = [sql for sql in statements if sql.startswith('DELETE FROM ')]
        self.assertEqual(len(deletes), 6)
        with original() as db:
            for sql in deletes:
                plan = ' '.join(row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + sql))
                self.assertIn('USING INDEX', plan, (sql, plan))
                self.assertNotIn('SCAN ', plan, (sql, plan))

    def test_existing_retention_preserves_recent_and_still_live_old_requests(self):
        now = time.time(); old = now - 40 * 86400
        with self.store.connect() as db:
            for rid, status, lease, updated in [('old-done', 'done', 0, old),
                    ('old-expired-pending', 'pending', 0, old),
                    ('old-live-pending', 'pending', now + 86400, old),
                    ('recent', 'done', 0, now)]:
                db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)', ('test', rid, rid, status, lease, '{}', updated))
            for ident, stamp in [('old', old), ('recent', now)]:
                db.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?)', (ident, 'test', ident, 'r', 1, 'draft', '{}', stamp))
                db.execute('INSERT INTO dialogs VALUES(?,?,?,?,?,?)', ('test', ident, 'r', 1, 0, stamp))
                db.execute('INSERT INTO delivery_observations VALUES(?,?,?,?)', ('test', ident, 'm', stamp))
                db.execute('INSERT INTO short_pause_observations VALUES(?,?,?,?)', ('test', ident, 'm', stamp))
            db.execute('INSERT INTO execution VALUES(?,?,?,?)', ('test', 'expired', 'r', old))
            db.execute('INSERT INTO execution VALUES(?,?,?,?)', ('test', 'live', 'r', now + 86400))
        self.store.purge()
        with self.store.connect() as db:
            self.assertEqual({r[0] for r in db.execute('SELECT rid FROM requests')}, {'old-live-pending', 'recent'})
            self.assertEqual([r[0] for r in db.execute('SELECT id FROM drafts')], ['recent'])
            for table in ('dialogs', 'delivery_observations', 'short_pause_observations'):
                self.assertEqual([r[0] for r in db.execute('SELECT chat FROM ' + table)], ['recent'])
            self.assertEqual([r[0] for r in db.execute('SELECT chat FROM execution')], ['live'])

    def test_old_populated_schema_migrates_idempotently_without_row_changes(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)', ('test', 'r1', 'f', 'pending', 9999999999, '{"original":true}', time.time()))
            before = tuple(db.execute('SELECT * FROM requests').fetchone())
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE '%_expiry_idx'").fetchall():
                db.execute('DROP INDEX ' + row[0])
        again = Store(self.path); third = Store(self.path)
        with third.connect() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM requests').fetchone()), before)
            plan = ' '.join(r[3] for r in db.execute('EXPLAIN QUERY PLAN SELECT rid FROM requests WHERE updated<0'))
            self.assertIn('USING INDEX', plan)

    def test_failed_cleanup_does_not_suppress_the_next_maintenance_attempt(self):
        original = self.store.connect
        with patch.object(self.store, 'connect', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError): self.store.purge()
        self.assertEqual(getattr(self.store, '_last_purge', 0), 0)
        with patch.object(self.store, 'connect', wraps=original) as calls: self.store.purge()
        self.assertEqual(calls.call_count, 1)
        self.assertGreater(self.store._last_purge, 0)

    def test_mid_cleanup_failure_rolls_back_deletions_and_releases_the_lock(self):
        old = time.time() - 40 * 86400
        with self.store.connect() as db:
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)', ('test', 'old', 'f', 'done', 0, '{}', old))
            db.execute("CREATE TRIGGER fail_cleanup BEFORE DELETE ON drafts BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
            db.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?)', ('old', 'test', 'c', 'r', 1, 'draft', '{}', old))
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError): self.store.purge()
        self.assertEqual(getattr(self.store, '_last_purge', 0), 0)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 1)
            db.execute('DROP TRIGGER fail_cleanup')
        self.store.purge()
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0], 0)

    def test_successful_daily_cleanup_is_not_repeated_per_preview(self):
        self.store.purge()
        with patch.object(self.store, 'connect', side_effect=AssertionError('repeated cleanup')):
            self.store.purge()

    def test_parallel_requests_do_not_run_two_housekeeping_transactions(self):
        original = self.store.connect; entered = threading.Event(); release = threading.Event(); calls = []; errors = []
        @contextlib.contextmanager
        def held():
            calls.append(1); entered.set()
            if not release.wait(3): raise AssertionError('fixture release missing')
            with original() as db: yield db
        def run():
            try: self.store.purge()
            except BaseException as error: errors.append(type(error).__name__)
        with patch.object(self.store, 'connect', held):
            thread = threading.Thread(target=run); thread.start()
            try:
                self.assertTrue(entered.wait(2)); run(); self.assertEqual(len(calls), 1)
            finally: release.set(); thread.join(3)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])

    def test_actual_startup_finishes_store_preparation_before_http_listener(self):
        import server
        events = []
        class ReadyStore:
            def purge(self): events.append('purge')
        class HTTP:
            def __init__(self, *args): events.append('listener')
            def serve_forever(self): events.append('serve')
        def store(): events.append('store'); return ReadyStore()
        with patch('research_server.configure_from_environment', side_effect=lambda: events.append('sources')), \
                patch.object(server, '_assistant_store', store), patch.object(server, 'ThreadingHTTPServer', HTTP), \
                patch.object(server, '_load_answer_cache'), patch.object(server, '_legacy_transport_allowed', return_value=False), \
                patch.object(server.claude_api, 'config', return_value={}), patch('builtins.print'):
            server.main()
        self.assertEqual(events, ['sources', 'store', 'purge', 'listener', 'serve'])

    def test_failed_store_readiness_never_binds_a_listener_or_starts_transport(self):
        import server
        class BrokenStore:
            def purge(self): raise OSError('fixture store not ready')
        with patch('research_server.configure_from_environment'), \
                patch.object(server, '_assistant_store', return_value=BrokenStore()), \
                patch.object(server, 'ThreadingHTTPServer') as listener, patch.object(server.channel, 'start') as channel, \
                patch.object(server, '_load_answer_cache'), patch.object(server.claude_api, 'config', return_value={}), patch('builtins.print'):
            with self.assertRaises(OSError): server.main()
        listener.assert_not_called(); channel.assert_not_called()


if __name__ == '__main__': unittest.main()
