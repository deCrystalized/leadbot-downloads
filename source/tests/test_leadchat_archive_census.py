import json
import sqlite3
import unittest
from contextlib import asynccontextmanager

from tools.leadchat_archive_census import SNAPSHOT, census


class Result:
    def __init__(self, cursor):
        self.cursor = cursor

    def mappings(self):
        return self

    def one(self):
        return self.cursor.fetchone()

    def __iter__(self):
        return iter(self.cursor)


class FixtureSession:
    def __init__(self, db):
        self.db = db
        self.executed = []
        self.completed = False

    @asynccontextmanager
    async def begin(self):
        self.db.execute("BEGIN")
        try:
            yield
            self.completed = True
        finally:
            self.db.rollback()

    async def execute(self, query):
        self.executed.append(query)
        if query not in SNAPSHOT:
            return Result(self.db.execute(query))


class ArchiveCensusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("jsonb_typeof", 1, self.json_type)
        self.db.create_function("jsonb_array_length", 1, lambda value: len(json.loads(value)))
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS public;
            CREATE TABLE public.conversations
                (id TEXT PRIMARY KEY, channel TEXT, client_id TEXT, last_message_at TEXT,
                 crm_request_id TEXT, outcome TEXT);
            CREATE TABLE public.messages
                (conversation_id TEXT, direction TEXT, sender_type TEXT, created_at TEXT,
                 attachments TEXT, voice_transcript_status TEXT, delivery_status TEXT);
        """)
        self.session = FixtureSession(self.db)

    @staticmethod
    def json_type(value):
        if value is None:
            return None
        return "array" if isinstance(json.loads(value), list) else "other"

    async def test_counts_units_roles_and_markers_without_emitting_identifiers(self):
        self.db.executescript("""
            INSERT INTO public.conversations VALUES
              ('private-a','avito','private-client-a','2026-10-03','private-crm',NULL),
              ('private-b','avito','private-client-a',NULL,'','no_reply'),
              ('private-c','jivo','private-client-a','2026-10-03',NULL,NULL),
              ('private-d','private-other','private-client-b','2026-10-03',NULL,NULL);
            INSERT INTO public.messages VALUES
              ('private-a','in','client','2026-10-01','[{"secret":"private-attachment"}]','done','delivered'),
              ('private-b','in','client','2026-10-03','{}',NULL,'delivered'),
              ('private-a','out','operator','2026-10-03','[]',NULL,'delivered'),
              ('private-a','out','bot','2026-10-03','[]',NULL,'delivered'),
              ('private-b','out','system','2026-10-03','[]',NULL,'delivered'),
              ('private-c','system','avito','2026-10-03','[]',NULL,'delivered'),
              ('private-c','note','operator','2026-10-03','[]',NULL,'delivered'),
              ('private-missing','in','private-sender','2026-10-03','[]',NULL,'delivered');
        """)
        result = await census(self.session, str)
        self.assertEqual(result["totals"], dict(conversations=4, linked_client_cards=2, messages=8))
        channels = {row["channel_group"]: row for row in result["conversation_channels"]}
        self.assertEqual(set(channels), {"avito", "jivo", "other"})
        self.assertEqual(channels["avito"], dict(channel_group="avito", conversations=2,
            linked_client_cards=1, no_last_message_timestamp=1, crm_id_present=1,
            stored_outcome_present=1))
        roles = {row["role_group"]: row for row in result["message_roles"]}
        self.assertEqual({key: row["messages"] for key, row in roles.items()},
                         dict(client=2, operator=1, bot=1, system=2, note=1, other=1))
        self.assertEqual(roles["client"], dict(role_group="client", messages=2,
            first_stored_date_utc="2026-10-01", last_stored_date_utc="2026-10-03",
            with_attachments=1, asr_done_status=1))
        self.assertEqual(result["unlinked_messages"], 1)
        self.assertEqual(result["conversation_lengths"], [
            dict(minimum_messages=0, conversations=1, messages=0,
                 client_and_delivered_operator=0, client_and_delivered_bot=0, client_and_both=0),
            dict(minimum_messages=1, conversations=3, messages=7,
                 client_and_delivered_operator=1, client_and_delivered_bot=1, client_and_both=1),
        ])
        self.assertNotIn("private-", json.dumps(result))
        self.assertEqual(self.session.executed[:4], list(SNAPSHOT))
        self.assertTrue(self.session.completed)

    async def test_failure_after_conversation_counts_has_no_complete_snapshot(self):
        self.db.execute("DROP TABLE public.messages")
        with self.assertRaises(sqlite3.OperationalError):
            await census(self.session, str)
        self.assertFalse(self.session.completed)
        self.assertFalse(self.db.in_transaction)

    async def test_empty_store_is_a_valid_completed_snapshot(self):
        result = await census(self.session, str)
        self.assertEqual(result["totals"], dict(conversations=0, linked_client_cards=0, messages=0))
        self.assertEqual(result["message_roles"], [])
        self.assertEqual(result["conversation_lengths"], [])
        self.assertEqual(result["unlinked_messages"], 0)
        self.assertTrue(self.session.completed)

    async def test_length_band_boundaries_and_delivered_reply_presence(self):
        sizes = (0, 1, 5, 6, 20, 21, 100, 101)
        for size in sizes:
            cid = f'private-case-{size}'
            self.db.execute("INSERT INTO public.conversations (id, channel) VALUES (?, 'avito')", (cid,))
            history = [('system', 'system', 'delivered')] * size
            if size:
                history[0] = ('in', 'client', 'delivered')
            if size == 5:
                history[1:4] = [('out', 'operator', 'pending'), ('out', 'bot', 'failed'),
                                ('note', 'operator', 'delivered')]
            if size == 6:
                history[1] = ('out', 'operator', 'delivered')
            if size == 101:
                history[1] = ('out', 'bot', 'delivered')
            self.db.executemany(
                "INSERT INTO public.messages (conversation_id, direction, sender_type, delivery_status) "
                "VALUES (?, ?, ?, ?)", ((cid, *message) for message in history),
            )
        self.db.commit()
        result = await census(self.session, str)
        bands = result["conversation_lengths"]
        self.assertEqual([(b["minimum_messages"], b["conversations"], b["messages"]) for b in bands],
                         [(0, 1, 0), (1, 2, 6), (6, 2, 26), (21, 2, 121), (101, 1, 101)])
        self.assertEqual([b["client_and_delivered_operator"] for b in bands], [0, 0, 1, 0, 0])
        self.assertEqual([b["client_and_delivered_bot"] for b in bands], [0, 0, 0, 0, 1])
        self.assertFalse(any(b["client_and_both"] for b in bands))
        self.assertEqual(result["unlinked_messages"], 0)
