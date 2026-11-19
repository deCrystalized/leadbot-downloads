"""Download public Avito images for a guarded development party; no UI writes."""
import concurrent.futures
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'leadbot/brain'))
import contact_phone


def main():
    assert len(sys.argv) == 2 and re.fullmatch(r'\d+-\d+', sys.argv[1])
    party = ROOT / ('test-artifacts/human-practice/manual-batch' + sys.argv[1])
    rows = json.loads((party / 'sources-private.json').read_text())
    assert_development_dialogues(r['cid'] for r in rows)
    assert_development_phones(p.value for r in rows for m in r['messages'] if m['direction'] == 'in'
                              for p in contact_phone.find_all(m.get('text') or m.get('transcript') or ''))
    output = party / 'images';output.mkdir(mode=0o700, exist_ok=True)
    images, other = [], []
    for row in rows:
        for index, message in enumerate(row['messages'], 1):
            for offset, attachment in enumerate(message.get('attachments') or [], 1):
                record = dict(case=row['number'], message_index=index, message_id=message['id'],
                              attachment_index=offset, media_id=attachment.get('media_id'), viewed=False)
                if attachment.get('kind') != 'image':
                    other.append(dict(record, attachment=attachment, transcript=message.get('transcript'), reviewed=False))
                    continue
                record.update(url=attachment['url'], path=str(output / f"case{row['number']}-message{index}-{offset}.jpg"))
                images.append(record)

    def download(record):
        try:
            parsed = urllib.parse.urlparse(record['url'])
            assert parsed.scheme == 'https' and re.fullmatch(r'\d+\.img\.avito\.st', parsed.hostname or '')
            path = Path(record['path'])
            if path.exists():
                payload = path.read_bytes();mime = 'image/cached'
            else:
                with urllib.request.urlopen(record['url'], timeout=20) as response:
                    redirected = urllib.parse.urlparse(response.url)
                    assert redirected.scheme == 'https' and (redirected.hostname or '').endswith('.avito.st')
                    mime = response.headers.get_content_type();assert mime.startswith('image/')
                    payload = response.read(10 * 1024 * 1024 + 1)
                assert 0 < len(payload) <= 10 * 1024 * 1024
                path.write_bytes(payload);path.chmod(0o600)
            record.update(downloaded=True, mime=mime, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        except Exception as error:
            record.update(downloaded=False, error=type(error).__name__)
        return record

    # Preserve reviewed observations if this is a download retry.
    oldpath = party / 'image-files-private.json'
    old = {r['path']: r for r in json.loads(oldpath.read_text())} if oldpath.exists() else {}
    oldotherpath = party / 'other-media-private.json'
    oldother = {(r['message_id'], r['attachment_index']): r for r in json.loads(oldotherpath.read_text())} if oldotherpath.exists() else {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        images = list(pool.map(download, images))
    for row in images:
        previous = old.get(row['path'], {})
        if previous.get('viewed') and previous.get('sha256') == row.get('sha256'):
            row.update({k: previous[k] for k in ('viewed', 'observed', 'viewed_via', 'diagnosis_confirmed') if k in previous})
    for row in other:
        previous = oldother.get((row['message_id'], row['attachment_index']), {})
        if previous.get('attachment') == row.get('attachment') and previous.get('transcript') == row.get('transcript'):
            row.update({k: v for k, v in previous.items() if k not in row or k == 'reviewed'})
    for filename, data in (('image-files-private.json', images), ('other-media-private.json', other)):
        p = party / filename;p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n');p.chmod(0o600)
    print(json.dumps(dict(images=len(images), downloaded=sum(r['downloaded'] for r in images),
                          failures=sum(not r['downloaded'] for r in images), other_attachments=len(other),
                          manually_viewed=sum(r['viewed'] for r in images), auto_enabled=False)))


if __name__ == '__main__':
    main()
