"""Load trusted, versioned experience data; never admit a model's own output.

The publisher changes one pointer only after all immutable data files exist.
Each preparation/validation checks that same snapshot; missing new data never
falls back to an older, possibly revoked version.
"""
import hashlib
import json
import os
from pathlib import Path
from dataclasses import dataclass
import sqlite3

from experience_memory import Memory, digest
from experienced_dialogues import Reader

MODES = ('model', 'neural_review', 'neural_auto')
POINTER_FIELDS = {'schema', 'archive', 'archive_sha256', 'archive_version',
                  'lessons', 'lessons_sha256', 'reviews', 'reviews_sha256'}


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 8_000_000:
        raise ValueError('Experience manifest is too large')
    return json.loads(path.read_text())


def pointer_files(path):
    pointer = read_json(path)
    if not isinstance(pointer, dict) or set(pointer) != POINTER_FIELDS or pointer['schema'] != 1:
        raise ValueError('Experience pointer schema mismatch')
    files = {}
    for key in ('archive', 'lessons', 'reviews'):
        name = pointer[key]
        if not isinstance(name, str) or Path(name).name != name or name in ('', '.', '..'):
            raise ValueError('Experience file must be beside its pointer')
        file = Path(path).parent / name
        if file.is_symlink() or file.stat().st_size > 64_000_000:
            raise ValueError('Invalid experience snapshot file')
        if hashlib.sha256(file.read_bytes()).hexdigest() != pointer[key + '_sha256']:
            raise ValueError('Experience snapshot file changed')
        files[key] = file
    if Reader(files['archive']).version() != pointer['archive_version']:
        raise ValueError('Experience archive version changed')
    return files


@dataclass
class Snapshot:
    archive: Reader | None
    memory: Memory | None
    archive_version: str | None
    knowledge_version: str | None
    version: str
    policy: str

    def lessons(self, query, direction, *, case_id='', client_group='', stages=('intake',)):
        if self.memory is None:
            return []
        result = self.memory.retrieve_stages(query, direction, stages, self.policy,
                                             case_id=case_id, client_group=client_group)
        # The head can change between refresh and retrieval in another process.
        # Do not mislabel newer lessons with an older request binding.
        if result['version'] != self.knowledge_version:
            raise ValueError('Experience memory changed during preparation')
        return result['examples']


def load(store_path, policy, wording_mode='neural_review'):
    if wording_mode not in MODES:
        return None
    folder = Path(store_path).parent
    pointer = Path(os.environ.get('LEADBOT_EXPERIENCE_POINTER') or folder / 'experience-current.json')
    paths = pointer_files(pointer) if pointer.exists() or os.environ.get('LEADBOT_EXPERIENCE_POINTER') else {}
    archive = paths.get('archive') or Path(os.environ.get('LEADBOT_EXPERIENCED_DB') or folder / 'experienced-dialogues.sqlite3')
    required = os.environ.get('LEADBOT_EXPERIENCE_REQUIRED') == '1'
    reader = None
    if archive.exists() or required or os.environ.get('LEADBOT_EXPERIENCED_DB'):
        reader = Reader(archive)
        archive_version = reader.version()
    else:
        archive_version = None
    catalog = paths.get('lessons') or Path(os.environ.get('LEADBOT_EXPERIENCE_CATALOG') or folder / 'experienced-lessons.json')
    reviews = paths.get('reviews') or Path(os.environ.get('LEADBOT_EXPERIENCE_REVIEWS') or folder / 'experienced-reviews.json')
    memory, knowledge_version = None, None
    if (paths or catalog.exists() or reviews.exists() or os.environ.get('LEADBOT_EXPERIENCE_CATALOG')
            or os.environ.get('LEADBOT_EXPERIENCE_REVIEWS')):
        records, receipts = read_json(catalog), read_json(reviews)
        if (not isinstance(records, dict) or set(records) != {'schema', 'records'} or records['schema'] != 1
                or not isinstance(receipts, dict) or set(receipts) != {'schema', 'reviews'} or receipts['schema'] != 1):
            raise ValueError('Experience review schema mismatch')
        memory = Memory(folder / 'experience-memory.sqlite3')
        result = memory.refresh(records['records'], receipts['reviews'], policy)
        knowledge_version = result['version']
    if reader is None and memory is None:
        return None
    return Snapshot(reader, memory, archive_version, knowledge_version,
                    digest([archive_version, knowledge_version]), policy)


def current(payload, store_path, policy):
    mode = payload.get('wording_mode') or 'model'
    try:
        snapshot = load(store_path, policy, mode)
        return payload.get('experience_binding') == (snapshot.version if snapshot else None)
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return False
