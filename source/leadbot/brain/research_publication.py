"""Finite private source holds cover the interval from admission to completion.

The provider flock still serializes generation/publication. A pending reviewed
result must not lose its source version when that flock is released. These
metadata receipts confer neither model nor customer-action authority.
"""
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import time
from contextlib import closing
from pathlib import Path


class PublicationError(ValueError):
    pass


class Holds:
    def __init__(self, lock, database=None, *, clock=time.time):
        lock = Path(lock)
        if lock.is_symlink() or lock.parent.is_symlink():
            raise PublicationError('Publication lock must not be a symlink')
        self.directory = lock.parent.resolve() / (lock.name + '.admissions')
        self.database = Path(database).resolve() if database is not None else None
        self.clock = clock

    def _directory(self, create=False):
        if self.directory.is_symlink():
            raise PublicationError('Admission directory cannot be a symlink')
        if create:
            self.directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.directory.mkdir(exist_ok=True, mode=0o700)
        if not self.directory.exists():
            return False
        info = self.directory.lstat()
        parent = self.directory.parent.stat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or parent.st_uid != os.getuid()
                or parent.st_mode & 0o022):
            raise PublicationError('Private owned admission directory required')
        return True

    @staticmethod
    def _name(database, job):
        return hashlib.sha256(json.dumps([str(database), job]).encode()).hexdigest() + '.json'

    def path(self, job):
        if self.database is None or not re.fullmatch(r'[0-9a-f]{32}', job):
            raise PublicationError('Exact trusted job/database required')
        return self.directory / self._name(self.database, job)

    @staticmethod
    def _file(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 8192):
                raise PublicationError('Private bounded admission receipt required')
            raw = os.read(fd, 8193)
            after = os.fstat(fd)
            current = path.lstat()
            if ((info.st_ino,info.st_dev,info.st_mtime_ns,info.st_size) !=
                    (after.st_ino,after.st_dev,after.st_mtime_ns,after.st_size)
                    or (current.st_ino,current.st_dev) != (info.st_ino,info.st_dev)
                    or len(raw) != info.st_size):
                raise PublicationError('Admission receipt changed while reading')
            return raw
        finally:
            os.close(fd)

    def _read(self, path):
        def pairs(items):
            result = {}
            for key,value in items:
                if key in result:raise PublicationError('Duplicate admission field')
                result[key] = value
            return result
        try:
            value = json.loads(self._file(path), object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(PublicationError('Invalid admission number')))
        except (OSError, json.JSONDecodeError, UnicodeError) as error:
            raise PublicationError('Unreadable admission receipt') from error
        if (not isinstance(value,dict) or set(value) !=
                {'schema','job','jobs_database','binding_sha256','issued','deadline'}
                or type(value['schema']) is not int or value['schema'] != 1
                or not isinstance(value['job'],str) or not re.fullmatch(r'[0-9a-f]{32}', value['job'])
                or not isinstance(value['binding_sha256'],str)
                or not re.fullmatch(r'[0-9a-f]{64}', value['binding_sha256'])
                or not isinstance(value['jobs_database'],str)
                or not Path(value['jobs_database']).is_absolute()
                or Path(value['jobs_database']).name != 'jobs.sqlite3'
                or any(type(value[k]) not in (int,float) or not math.isfinite(value[k])
                       for k in ('issued','deadline'))
                or not 0 < value['deadline']-value['issued'] <= 300
                or value['issued'] > self.clock()+3
                or path.name != self._name(value['jobs_database'], value['job'])):
            raise PublicationError('Exact finite admission receipt required')
        return value

    def reserve(self, job, binding, deadline):
        self._directory(create=True)
        path = self.path(job)
        now = self.clock()
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or not 0 < deadline-now <= 300:
            raise PublicationError('Original finite admission deadline required')
        value = dict(schema=1, job=job, jobs_database=str(self.database),
            binding_sha256=binding, issued=now, deadline=deadline)
        if path.exists():
            self.verify(job, binding, deadline)
            return
        part = path.with_suffix('.part')
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(json.dumps(value,sort_keys=True,allow_nan=False).encode())
            stream.flush();os.fsync(stream.fileno())
        # The caller holds the exact Jobs SQLite write transaction. Complete
        # metadata is published before that job commits or can make a call.
        os.rename(part, path)
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def verify(self, job, binding, deadline):
        if not self._directory():raise PublicationError('Missing admitted source hold')
        value = self._read(self.path(job))
        if (value['jobs_database'] != str(self.database) or value['job'] != job
                or value['binding_sha256'] != binding or value['deadline'] != deadline
                or self.clock() >= deadline):
            raise PublicationError('Source hold no longer matches the original admission')

    def active_jobs(self):
        """Called under the publication flock; reads no source/model body."""
        if not self._directory():return []
        paths = list(self.directory.iterdir())
        if len(paths) > 4096:raise PublicationError('Admission directory exceeds finite capacity')
        active = []
        for path in paths:
            if re.fullmatch(r'[0-9a-f]{64}\.part',path.name):
                continue  # No committed job/provider call exists before rename.
            if not re.fullmatch(r'[0-9a-f]{64}\.json',path.name):
                raise PublicationError('Unexpected admission metadata')
            value = self._read(path)
            terminal = self.clock() >= value['deadline']
            if not terminal:
                database = Path(value['jobs_database'])
                if database != database.resolve() or database.is_symlink():
                    raise PublicationError('Canonical private Jobs database required')
                if database.exists():
                    info = database.stat()
                    parent = database.parent.stat()
                    if (info.st_uid != os.getuid() or info.st_mode & 0o077
                            or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode)
                            or parent.st_uid != os.getuid() or parent.st_mode & 0o077):
                        raise PublicationError('Private Jobs database required')
                    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
                        row = db.execute('SELECT j.state,g.binding_hash,g.deadline FROM jobs j '
                            'JOIN grants g ON g.id=j.grant_id WHERE j.id=?',(value['job'],)).fetchone()
                    after = database.stat()
                    if (after.st_ino,after.st_dev) != (info.st_ino,info.st_dev):
                        raise PublicationError('Jobs database changed during admission check')
                    if row:
                        if row[1] != value['binding_sha256'] or row[2] > value['deadline']:
                            raise PublicationError('Job admission changed')
                        terminal = row[0] in ('done','denied','rejected','stopped','cancelled') or self.clock() >= row[2]
                        if not terminal and row[0] not in ('queued','running','awaiting_root','accepted','finalizing'):
                            raise PublicationError('Unknown durable job state')
                # Missing DB/row after a crash stays held until the original
                # deadline, never inferred to be complete or silently extended.
            if terminal:
                path.unlink()  # Ephemeral metadata; canonical job/audit retained.
            else:active.append(value['job'])
        return active
