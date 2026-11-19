"""Package the current extension without embedding credentials or fixed versions."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'ext'
OUT = ROOT.parents[1] / 'outputs'
manifest = json.loads((EXT / 'manifest.json').read_text())
version = manifest['version']
assert all(p.isdigit() for p in version.split('.'))
for section in manifest['content_scripts']:
    for name in section.get('js', []) + section.get('css', []):
        assert (EXT / name).is_file(), name
OUT.mkdir(exist_ok=True)
archive = OUT / ('LeadChat-' + version + '.zip')
files = [p for p in sorted(EXT.rglob('*')) if p.is_file() and not any(part.startswith('.') or part == '__pycache__' for part in p.relative_to(EXT).parts)]
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in files:
        z.write(path, 'LeadChat-' + version + '/' + str(path.relative_to(EXT)))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert json.loads(z.read('LeadChat-' + version + '/manifest.json'))['version'] == version
print(json.dumps(dict(version=version,archive=str(archive),entries=len(files),sha256=hashlib.sha256(archive.read_bytes()).hexdigest())))
