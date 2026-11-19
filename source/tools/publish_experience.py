"""Atomically publish reviewed data; never manufacture review approvals."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from experience_memory import Memory, validate
from experienced_dialogues import Reader
from experience_runtime import pointer_files, read_json


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(folder, archive, lessons, reviews, policy):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    records, receipts = read_json(lessons), read_json(reviews)
    if (not isinstance(records, dict) or set(records) != {'schema', 'records'} or records['schema'] != 1
            or not isinstance(receipts, dict) or set(receipts) != {'schema', 'reviews'} or receipts['schema'] != 1):
        raise ValueError('Expected separate reviewed data and review manifests')
    if not isinstance(records['records'], list) or not all(validate(row) for row in records['records']):
        raise ValueError('Malformed experience lesson')
    with tempfile.TemporaryDirectory(prefix='experience-check-') as temp:
        checked = Memory(Path(temp) / 'checked.sqlite3').refresh(records['records'], receipts['reviews'], policy)
    # Removed review receipts explicitly revoke their records. No automatic
    # retry, policy relabelling or old-snapshot fallback is performed.
    pointer = dict(schema=1, archive_version=Reader(archive).version())
    for key, source in (('archive', archive), ('lessons', lessons), ('reviews', reviews)):
        content = Path(source).read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        name = key + '-' + checksum + ('.sqlite3' if key == 'archive' else '.json')
        destination = folder / name
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes() != content:
                raise ValueError('Immutable experience destination changed')
        else:
            fd, temporary = tempfile.mkstemp(prefix='.experience-', dir=folder)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, destination)
            finally:
                os.unlink(temporary)
        pointer[key], pointer[key + '_sha256'] = name, checksum
    fd, temporary = tempfile.mkstemp(prefix='.pointer-', dir=folder)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(pointer, stream, ensure_ascii=False, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        pointer_files(temporary)
        os.replace(temporary, folder / 'experience-current.json')
        fsync_directory(folder)
    finally:
        if Path(temporary).exists():
            os.unlink(temporary)
    return dict(archive_version=pointer['archive_version'], knowledge=checked, new_credit=0,
                pointer=str(folder / 'experience-current.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('folder', 'archive', 'lessons', 'reviews'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--policy', required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.folder, args.archive, args.lessons, args.reviews, args.policy), ensure_ascii=False))
