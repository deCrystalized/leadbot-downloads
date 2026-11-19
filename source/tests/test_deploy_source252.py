import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class DeploySource252Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.stage = self.folder/'stage'; (self.stage/'tools').mkdir(parents=True)
        source = Path(__file__).resolve().parents[1]/'tools/deploy_release.py'
        shutil.copyfile(source, self.stage/'tools/deploy_release.py')
        entries = []
        for name in ['assistant_store.py', 'assistant_policy.py', 'extension_assistant.py', 'personal_workflow.py', 'own_visit.py']:
            relative = 'leadbot/brain/'+name
            source = self.stage/relative; source.parent.mkdir(parents=True, exist_ok=True); source.write_text('synthetic staged code\n')
            target = self.folder/'targets'/name; target.parent.mkdir(exist_ok=True); target.write_text('synthetic previous code\n')
            entries.append(dict(source=relative,target=str(target),sha256=self.sha(source),baseline_sha256=self.sha(target)))
        self.manifest = self.stage/'test-artifacts/deploy-manifest.json'; self.manifest.parent.mkdir()
        self.data = dict(entries=entries); self.save()

    def sha(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def save(self):
        self.manifest.write_text(json.dumps(self.data))

    def run_preflight(self):
        return subprocess.run([sys.executable, str(self.stage/'tools/deploy_release.py')], capture_output=True, text=True)

    def test_matching_stage_is_accepted_without_apply(self):
        result = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.folder/'leadbot-release-backups').exists())

    def test_changed_or_missing_stage_source_fails_before_dryrun_success(self):
        source = self.stage/self.data['entries'][0]['source']
        for missing in [False, True]:
            with self.subTest(missing=missing):
                if missing: source.unlink()
                else: source.write_text('changed synthetic code\n')
                result = self.run_preflight()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('source', (result.stdout+result.stderr).lower())

    def test_a_source_cannot_escape_the_stage(self):
        source = self.folder/'outside.py'; source.write_text('synthetic outside code\n')
        extra = dict(self.data['entries'][0], source='../outside.py', sha256=self.sha(source))
        self.data['entries'].append(extra); self.save()
        result = self.run_preflight()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source', (result.stdout+result.stderr).lower())


if __name__ == '__main__':
    unittest.main()
