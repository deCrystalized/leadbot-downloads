"""Pinned approved sources for trusted server startup, never browser paths.

The publication manifest contains metadata identities only. Check its exact
hash and exclusions before opening the immutable history publication. The raw
daily pool is deliberately a different authority from this reviewed archive.
"""
import hashlib
import json
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

import assistant_catalog
import assistant_policy as policy
import experience_runtime
from experienced_dialogues import Reader, digest
from research_pipeline import Corpus


class SourceConfigurationError(ValueError):
    pass


def private_file(path, *, limit=8_000_000):
    if not isinstance(path, Path) or not path.is_absolute():
        raise SourceConfigurationError('Absolute trusted source path required')
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise SourceConfigurationError('Source configuration cannot use symlinks')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > limit):
            raise SourceConfigurationError('Private bounded source configuration required')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        current = path.stat(follow_symlinks=False)
        if (len(raw) > limit or len(raw) != info.st_size
                or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) !=
                   (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)):
            raise SourceConfigurationError('Source configuration changed while reading')
        return raw
    finally:
        os.close(fd)


def strict_json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise SourceConfigurationError('Duplicate configuration field')
            out[k] = v
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              SourceConfigurationError('Invalid configuration constant')))
    except (TypeError, UnicodeError, json.JSONDecodeError):
        raise SourceConfigurationError('Invalid source configuration') from None


class ApprovedSources:
    def __init__(self, manifest, expected_sha256, *, control=None):
        self.control = control
        self.path = manifest
        self.expected = expected_sha256
        raw = private_file(manifest)
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise SourceConfigurationError('Approved source manifest changed')
        value = strict_json(raw)
        fields = {'schema', 'approved_cids', 'excluded_cids', 'protection_version',
                  'pointer', 'pointer_sha256'}
        if (not isinstance(value, dict) or set(value) != fields or value['schema'] != 1
                or not isinstance(value['protection_version'], str) or not value['protection_version']):
            raise SourceConfigurationError('Approved source manifest schema mismatch')
        for key in ('approved_cids', 'excluded_cids'):
            ids = value[key]
            if (not isinstance(ids, list)
                    or any(not isinstance(cid, str) or not cid or len(cid) > 200 for cid in ids)
                    or len(ids) != len(set(ids))):
                raise SourceConfigurationError('Exact source identities required')
        self.allowed, self.excluded = set(value['approved_cids']), set(value['excluded_cids'])
        if not self.allowed or self.allowed & self.excluded:
            raise SourceConfigurationError('Approved source intersects protected identities')
        self.pointer = Path(value['pointer'])
        if not self.pointer.is_absolute():
            raise SourceConfigurationError('Absolute approved publication path required')
        self.pointer_sha256 = value['pointer_sha256']
        self.protection_version = value['protection_version']
        self.check()

    def check(self):
        if self.control is not None:
            self.control()
        raw = private_file(self.path)
        if hashlib.sha256(raw).hexdigest() != self.expected:
            raise SourceConfigurationError('Source permission or protection changed')
        raw_pointer = private_file(self.pointer)
        if hashlib.sha256(raw_pointer).hexdigest() != self.pointer_sha256:
            raise SourceConfigurationError('Approved publication changed; re-admission required')
        return digest([self.expected, self.pointer_sha256, self.protection_version])

    def guard(self, ids):
        self.check()
        if not set(ids) <= self.allowed or set(ids) & self.excluded:
            raise SourceConfigurationError('Source outside approved development identities')

    def corpus(self):
        self.guard(self.allowed)  # BEFORE pointer_files hashes or opens sources.
        paths = experience_runtime.pointer_files(self.pointer)
        lessons = experience_runtime.read_json(paths['lessons'])
        reviews = experience_runtime.read_json(paths['reviews'])
        if (not isinstance(lessons, dict) or set(lessons) != {'schema', 'records'}
                or lessons['schema'] != 1 or not isinstance(lessons['records'], list)
                or not isinstance(reviews, dict) or set(reviews) != {'schema', 'reviews'}
                or reviews['schema'] != 1 or not isinstance(reviews['reviews'], dict)):
            raise SourceConfigurationError('Published learning and review formats are incompatible')
        reader = Reader(paths['archive'])
        with closing(sqlite3.connect(reader.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            ids = [r[0] for r in db.execute('SELECT cid FROM dialogues')]
        if set(ids) != self.allowed:
            raise SourceConfigurationError('Publication roster differs from approved identities')
        self.guard(ids)
        directory = Path(policy.__file__).parent
        primary_paths = [directory / 'policy_registry.json', directory / 'reviewed_catalog.json']
        def versions():
            return digest([self.check(), policy.VERSION,
                [(p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in primary_paths]])
        corpus = Corpus(reader, policy.registry()['sources'] + assistant_catalog.data()['owner_amendments'],
                        allowed_cids=ids, guard=self.guard, versions=versions)
        corpus.reviewed_lesson_metadata = {
            record['id']: dict(record=record, review=reviews['reviews'].get(record['id']))
            for record in lessons['records']}
        return corpus
