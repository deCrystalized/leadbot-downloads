"""Durable, scoped request/draft store. No transport to customers or CRM."""
import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class Store:
    def __init__(self, path=None):
        self.path = str(path or os.environ.get("LEADBOT_ASSISTANT_DB")
                        or Path(__file__).resolve().parents[1] / "data" / "assistant.sqlite3")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._purge_lock = threading.Lock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS requests (
                    scope TEXT NOT NULL, rid TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL, lease REAL NOT NULL, result TEXT, updated REAL NOT NULL,
                    PRIMARY KEY(scope,rid));
                CREATE TABLE IF NOT EXISTS dialogs (
                    scope TEXT NOT NULL, chat TEXT NOT NULL, revision TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 1, held INTEGER NOT NULL DEFAULT 0,
                    updated REAL NOT NULL, PRIMARY KEY(scope,chat));
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, chat TEXT NOT NULL,
                    revision TEXT NOT NULL, generation INTEGER NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS draft_chat ON drafts(scope,chat,created);
                CREATE TABLE IF NOT EXISTS execution (
                    scope TEXT NOT NULL, chat TEXT NOT NULL, rid TEXT NOT NULL,
                    lease REAL NOT NULL, PRIMARY KEY(scope,chat));
                CREATE TABLE IF NOT EXISTS delivery_observations (
                    scope TEXT NOT NULL, chat TEXT NOT NULL, message TEXT NOT NULL,
                    first_confirmed REAL NOT NULL, PRIMARY KEY(scope,chat,message));
                CREATE TABLE IF NOT EXISTS short_pause_observations (
                    scope TEXT NOT NULL, chat TEXT NOT NULL, message TEXT NOT NULL,
                    first_seen REAL NOT NULL, PRIMARY KEY(scope,chat,message));
                CREATE INDEX IF NOT EXISTS requests_expiry_idx ON requests(updated);
                CREATE INDEX IF NOT EXISTS execution_expiry_idx ON execution(lease);
                CREATE INDEX IF NOT EXISTS dialogs_expiry_idx ON dialogs(updated);
                CREATE INDEX IF NOT EXISTS drafts_expiry_idx ON drafts(created);
                CREATE INDEX IF NOT EXISTS delivery_expiry_idx ON delivery_observations(first_confirmed);
                CREATE INDEX IF NOT EXISTS short_pause_expiry_idx ON short_pause_observations(first_seen);
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=3000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def claim(self, scope, rid, fingerprint, lease=60):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM requests WHERE scope=? AND rid=?", (scope, rid)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint:
                    return "mismatch", None
                if row["status"] == "done":
                    return "done", json.loads(row["result"])
                # An expired worker is indeterminate, never blindly re-executed.
                return ("pending" if row["lease"] > now else "interrupted"), None
            db.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?)",
                       (scope, rid, fingerprint, "pending", now + lease, None, now))
            return "claimed", None

    def observe_deliveries(self, scope, chat, identities, now, reset=()):
        """First server observation of confirmed delivery, never queue time.

        LeadChat has no persisted delivery timestamp. This conservative anchor
        may delay a timer after a long offline gap, but cannot shorten it.
        Scope and original message identity keep previews and plans consistent.
        """
        if not identities and not reset:
            return {}
        with self.connect() as db:
            for identity in reset:
                db.execute('DELETE FROM delivery_observations WHERE scope=? AND chat=? AND message=?',
                           (scope, chat, identity))
            for identity in identities:
                db.execute('INSERT OR IGNORE INTO delivery_observations VALUES (?,?,?,?)',
                           (scope, chat, identity, now))
            return {identity: db.execute(
                'SELECT first_confirmed FROM delivery_observations WHERE scope=? AND chat=? AND message=?',
                (scope, chat, identity)).fetchone()['first_confirmed'] for identity in identities}

    def complete(self, scope, rid, result):
        with self.connect() as db:
            db.execute("UPDATE requests SET status='done',result=?,updated=? WHERE scope=? AND rid=? AND status='pending'",
                       (json.dumps(result, ensure_ascii=False), time.time(), scope, rid))

    def observe_short_pause(self, scope, chat, identity, now):
        """Stable first server sighting, scoped to one account and dialogue."""
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO short_pause_observations VALUES (?,?,?,?)',
                       (scope, chat, identity, now))
            return db.execute('SELECT first_seen FROM short_pause_observations WHERE scope=? AND chat=? AND message=?',
                              (scope, chat, identity)).fetchone()['first_seen']

    def stage(self, scope, rid, payload):
        with self.connect() as db:
            db.execute("UPDATE requests SET result=?,updated=? WHERE scope=? AND rid=? AND status='pending'",
                       (json.dumps(payload, ensure_ascii=False), time.time(), scope, rid))

    def request(self, scope, rid):
        with self.connect() as db:
            row = db.execute("SELECT status,result FROM requests WHERE scope=? AND rid=?", (scope, rid)).fetchone()
        return (row["status"], json.loads(row["result"]) if row["result"] else None) if row else (None, None)

    def acquire_dialog(self, scope, chat, rid, lease=60):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT lease FROM execution WHERE scope=? AND chat=?", (scope, chat)).fetchone()
            if row:
                return "busy" if row["lease"] > time.time() else "interrupted"
            db.execute("INSERT INTO execution VALUES (?,?,?,?)", (scope, chat, rid, time.time() + lease))
        return "claimed"

    def release_dialog(self, scope, chat, rid):
        with self.connect() as db:
            db.execute("DELETE FROM execution WHERE scope=? AND chat=? AND rid=?", (scope, chat, rid))

    def resume(self, scope, chat, revision):
        # Resuming drafts never enables transport. Fence any abandoned worker.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE dialogs SET held=0,generation=generation+1,revision=?,updated=? WHERE scope=? AND chat=?",
                       (revision, time.time(), scope, chat))
            db.execute("UPDATE drafts SET status='stale' WHERE scope=? AND chat=? AND status='draft'", (scope, chat))
            db.execute("DELETE FROM execution WHERE scope=? AND chat=?", (scope, chat))

    def wait(self, scope, rid, timeout=9):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.connect() as db:
                row = db.execute("SELECT status,result FROM requests WHERE scope=? AND rid=?", (scope, rid)).fetchone()
            if row and row["status"] == "done":
                return json.loads(row["result"])
            time.sleep(0.025)
        return None

    def observe(self, scope, chat, revision, *, takeover=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM dialogs WHERE scope=? AND chat=?", (scope, chat)).fetchone()
            generation = row["generation"] if row else 1
            held = bool(takeover or (row and row["held"]))
            if row and (row["revision"] != revision or takeover):
                generation += 1
                db.execute("UPDATE drafts SET status='stale' WHERE scope=? AND chat=? AND status='draft'", (scope, chat))
            db.execute("INSERT OR REPLACE INTO dialogs VALUES (?,?,?,?,?,?)",
                       (scope, chat, revision, generation, int(held), time.time()))
            return generation, held

    def save_draft(self, scope, chat, revision, generation, payload):
        # Clock phases can produce different requests without a new message.
        # A new reply must not resolve to the earlier saved waiting payload.
        draft_id = digest([scope, chat, revision, generation, payload.get("policy_version"), payload.get('request_id')])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM dialogs WHERE scope=? AND chat=?", (scope, chat)).fetchone()
            if not row or row["revision"] != revision or row["generation"] != generation or row["held"]:
                return None
            db.execute("INSERT OR IGNORE INTO drafts VALUES (?,?,?,?,?,?,?,?)",
                       (draft_id, scope, chat, revision, generation, "draft", json.dumps(payload, ensure_ascii=False), time.time()))
        return draft_id

    def draft(self, scope, draft_id, revision, chat=None):
        with self.connect() as db:
            row = db.execute("""SELECT d.*,s.revision AS current_revision,s.generation AS current_generation,s.held
                FROM drafts d JOIN dialogs s ON s.scope=d.scope AND s.chat=d.chat
                WHERE d.id=? AND d.scope=?""", (draft_id, scope)).fetchone()
        if (not row or (chat is not None and row["chat"] != chat) or row["status"] != "draft" or row["held"] or revision != row["revision"]
                or row["current_revision"] != row["revision"] or row["current_generation"] != row["generation"]):
            return None
        return json.loads(row["payload"])

    def purge(self, days=30):
        if not self._purge_lock.acquire(blocking=False):
            return
        try:
            if time.time() - getattr(self, "_last_purge", 0) < 86400:
                return
            cutoff = time.time() - days * 86400
            with self.connect() as db:
                db.execute("DELETE FROM requests WHERE updated<? AND (status='done' OR lease<?)", (cutoff, time.time()))
                db.execute("DELETE FROM execution WHERE lease<?", (time.time(),))
                db.execute("DELETE FROM dialogs WHERE updated<?", (cutoff,))
                db.execute("DELETE FROM drafts WHERE created<?", (cutoff,))
                db.execute("DELETE FROM delivery_observations WHERE first_confirmed<?", (cutoff,))
                db.execute("DELETE FROM short_pause_observations WHERE first_seen<?", (cutoff,))
            # A failed or rolled-back cleanup must remain eligible for maintenance.
            self._last_purge = time.time()
        finally:
            self._purge_lock.release()
