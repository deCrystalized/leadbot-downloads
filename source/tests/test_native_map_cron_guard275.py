"""Existing cron cannot replace a pinned native map or restart its worker."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'leadbot/analysis/obnovit_karty.sh'


class NativeMapCronGuardTests(unittest.TestCase):
    def exercise(self, configured):
        with TemporaryDirectory(prefix='map guard ') as directory:
            root = Path(directory)
            (root / 'analysis').mkdir()
            (root / 'brain').mkdir()
            configuration = root / 'separate native runtime'
            configuration.mkdir()
            (root / 'bin').mkdir()
            original = b'{"accepted":"unchanged full map bytes"}'
            (root / 'brain/filial_zones.json').write_bytes(original)
            if configured:
                path = configuration / configured
                if configured == 'api0.json':
                    path.symlink_to(root / 'missing-config')
                else:
                    path.write_text('contents must not be read')
            # Actual shell, fully simulated executors. Any attempted fetch or restart
            # leaves a separate record; no network or production paths are available.
            for name, source in {
                'python3': '#!/bin/sh\nprintf "fetch\\n" >> "$LEADBOT_MAP_TEST_CALLS"\n',
                'systemctl': '#!/bin/sh\nprintf "%s\\n" "$*" >> "$LEADBOT_MAP_TEST_CALLS"\n',
            }.items():
                path = root / 'bin' / name
                path.write_text(source)
                path.chmod(0o700)
            calls = root / 'calls'
            log = root / 'map.log'
            environment = dict(os.environ, PATH=str(root / 'bin') + ':/usr/bin:/bin',
                               LEADBOT_MAP_REFRESH_ROOT=str(root), LEADBOT_MAP_REFRESH_LOG=str(log),
                               LEADBOT_MAP_REFRESH_CONFIG_ROOT=str(configuration),
                               LEADBOT_MAP_TEST_CALLS=str(calls))
            result = subprocess.run(['/bin/sh', str(SCRIPT)], env=environment, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'brain/filial_zones.json').read_bytes(), original)
            return calls.read_text() if calls.exists() else '', log.read_text()

    def test_native_config_stops_before_fetch_and_restart_without_parsing_it(self):
        calls, log = self.exercise('api275.json')
        self.assertEqual(calls, '')
        self.assertIn('автоматическая публикация и перезапуск не выполнялись', log)

    def test_future_native_release_is_also_guarded(self):
        calls, _ = self.exercise('api1234.json')
        self.assertEqual(calls, '')

    def test_native_guard_does_not_depend_on_any_key_file(self):
        calls, _ = self.exercise('api1.json')
        self.assertEqual(calls, '')

    def test_broken_config_marker_is_conservative_and_cannot_enable_legacy_publishing(self):
        calls, _ = self.exercise('api0.json')
        self.assertEqual(calls, '')

    def test_legacy_without_native_config_keeps_existing_update_path(self):
        calls, _ = self.exercise(None)
        self.assertEqual(calls.splitlines(), ['fetch', 'is-active --quiet leadbot', 'restart leadbot'])

    def test_unrelated_json_is_not_a_native_configuration(self):
        calls, _ = self.exercise('status.json')
        self.assertIn('fetch', calls)


if __name__ == '__main__':
    unittest.main()
