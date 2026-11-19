"""Build a fresh immutable code-only release; never reuse a cached JS bundle."""
import argparse
import ast
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True)
    parser.add_argument('--baseline-manifest', default='test-artifacts/auto-release/stage/test-artifacts/deploy-manifest.json')
    args = parser.parse_args()
    policy = ast.parse((ROOT / 'leadbot/brain/assistant_policy.py').read_text())
    policy_version = next(ast.literal_eval(node.value) for node in policy.body
                          if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in node.targets))
    registry_version = json.loads((ROOT / 'leadbot/brain/policy_registry.json').read_text())['version']
    assert policy_version == registry_version, 'Policy code and registry versions differ; no stage created'
    stage = (ROOT / args.stage).resolve()
    assert stage.is_relative_to(ROOT / 'test-artifacts') and not stage.exists()
    baseline = (ROOT / args.baseline_manifest).resolve()
    assert baseline.is_relative_to(ROOT / 'test-artifacts')
    manifest = json.loads(baseline.read_text())
    required = {'leadbot/brain/assistant_store.py', 'leadbot/brain/assistant_policy.py',
                'leadbot/brain/extension_assistant.py', 'leadbot/brain/personal_workflow.py',
                'leadbot/brain/own_visit.py'}
    missing = required - {row['source'] for row in manifest['entries']}
    assert not missing, 'Incomplete runtime manifest: ' + ', '.join(sorted(missing))
    assert any(row['source'] == 'leadbot/brain/contact_address.py' for row in manifest['entries']), (
        'Baseline must include the independently verified installed address parser')
    stage.mkdir(mode=0o700)
    for row in manifest['entries']:
        source = (ROOT / row['source']).resolve()
        assert source.is_relative_to(ROOT) and source.is_file()
        target = stage / row['source']
        assert target.resolve().is_relative_to(stage)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        row['baseline_sha256'] = row['sha256']
    bundle = stage / 'test-artifacts/auto-release/brain-dist.js'
    subprocess.run(['node', str(ROOT / 'extension-server/brain/build.js'), 'ext', str(bundle)], cwd=ROOT, check=True)
    version = subprocess.check_output(['node', '-e', 'process.stdout.write(require(process.argv[1]).ВЕРСИЯ)', str(bundle)], cwd=ROOT, text=True)
    assert version and len(version) < 30
    for row in manifest['entries']:
        row['sha256'] = hashlib.sha256((stage / row['source']).read_bytes()).hexdigest()
    manifest['policy_version'] = json.loads((ROOT / 'leadbot/brain/policy_registry.json').read_text())['version']
    manifest['brain_version'] = version
    # Installed compiled-entry checks also load the actual form adapter.
    shutil.copytree(ROOT / 'ext', stage / 'ext')
    for name in ('deploy_release.py', 'verify_history_release.py', 'production_auto_entry.js',
                 'production_map_entry.js', 'production_far_trip_entry.js', 'production_locality_entry.js',
                 'production_presence_case63.cjs', 'production_minima63.cjs',
                 'production_image_roles73.py', 'check_image_roles73.cjs',
                 'production_history_roles74.py', 'production_contact_followup75.py',
                 'check_contact_followup75.cjs', 'production_history_intent76.py',
                 'check_history_intent76.cjs', 'production_client_scope77.py',
                 'check_client_scope77.cjs', 'production_history_scope78.py',
                 'check_history_scope78.cjs', 'production_confirmation79.py',
                 'check_confirmation79.cjs', 'production_price_correction80.py',
                 'check_price_correction80.cjs', 'production_unified82.py', 'check_diagnostic_scope117.cjs'):
        target = stage / 'tools' / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'tools' / name, target)
    # Public map snapshots used by the installed-entry read-only checks.
    # These are checker fixtures, never customer history or runtime config.
    for name in ('kp.html', 'mytishchi-expected.json'):
        source = ROOT / 'test-artifacts/custom-maps-20261018' / name
        target = stage / 'test-artifacts/custom-maps-20261018' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (stage / 'test-artifacts/deploy-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'files': len(manifest['entries']), 'policy_version': manifest['policy_version'], 'fresh_brain_version': version}))


if __name__ == '__main__':
    main()
