"""Private per-dialogue memory with source/version binding and atomic fencing.

Only the trusted server can supply the authoritative revision. This class is
not exposed as a model tool and never grants customer/CRM action authority.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from experienced_dialogues import digest
from research_pipeline import pack_context


class MemoryConflict(ValueError):
    pass


def _versions(context):
    return [context[k] for k in ('revision','policy_version','memory_version','map_version')]


class QuickMemory:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS quick_dialogues (
                owner TEXT NOT NULL, cid TEXT NOT NULL, generation INTEGER NOT NULL,
                versions TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL,
                PRIMARY KEY(owner,cid))''')
        self.path.chmod(0o600)

    def load(self, owner, cid, observed):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            row = db.execute('SELECT generation,versions,payload,checksum FROM quick_dialogues WHERE owner=? AND cid=?', (owner,cid)).fetchone()
        if row is None:
            return dict(status='missing', generation=0, payload=None)
        generation, versions, payload, checksum = row
        context = json.loads(payload)
        if digest(context) != checksum or context.get('owner_id') != owner or context.get('dialogue_id') != cid:
            raise MemoryConflict('Private quick-memory integrity mismatch')
        if json.loads(versions) != _versions(observed):
            return dict(status='stale', generation=generation, payload=None)
        return dict(status='current', generation=generation, payload=context)

    def save(self, owner, cid, context, *, expected_generation, authoritative_revision):
        if (not isinstance(owner,str) or not owner or not isinstance(cid,str) or not cid
                or isinstance(expected_generation,bool) or not isinstance(expected_generation,int) or expected_generation < 0
                or context.get('owner_id') != owner or context.get('dialogue_id') != cid
                or context.get('revision') != authoritative_revision):
            raise MemoryConflict('Identity or authoritative revision mismatch')
        pack_context('research', context)  # Includes source/role and reviewed-lesson admission.
        checksum = digest(context)
        versions = json.dumps(_versions(context), ensure_ascii=False)
        payload = json.dumps(context, ensure_ascii=False, sort_keys=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT generation,versions,checksum FROM quick_dialogues WHERE owner=? AND cid=?', (owner,cid)).fetchone()
            generation = row[0] if row else 0
            if row and row[1] == versions and row[2] == checksum:
                return dict(generation=generation, idempotent=True)
            if generation != expected_generation or row and row[1] == versions:
                raise MemoryConflict('Stale worker or same-version content collision')
            generation += 1
            db.execute('''INSERT INTO quick_dialogues VALUES(?,?,?,?,?,?)
                ON CONFLICT(owner,cid) DO UPDATE SET generation=excluded.generation,
                versions=excluded.versions,payload=excluded.payload,checksum=excluded.checksum''',
                (owner,cid,generation,versions,payload,checksum))
        return dict(generation=generation, idempotent=False)
