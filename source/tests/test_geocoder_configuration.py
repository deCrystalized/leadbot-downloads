"""Environment replacement is isolated, atomic and never destroys other keys."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from configure_geocoder_secure import remote


class GeocoderConfigurationTests(unittest.TestCase):
    def run_fixture(self,exists=True,fail=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'secrets.env';backup=root/'backups';backup.mkdir()
            original='EXISTING_SECRET="synthetic-safe"\nYANDEX_GEOCODER_KEY="old"\nOTHER=value\n'
            if exists:p.write_text(original);p.chmod(0o640)
            code=remote.replace("Path('/etc/lead-centre/secrets.env')",'Path('+repr(str(p))+')').replace("Path('/root/leadbot-release-backups')",'Path('+repr(str(backup))+')')
            code=code.replace("r=subprocess.run(['systemctl','restart','lc-brain'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)","r=type('Result',(),{'returncode':"+str(int(fail))+"})()")
            code=code.replace("subprocess.run(['systemctl','restart','lc-brain'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)","None")
            result=subprocess.run([sys.executable,'-c',code],input='00000000-0000-0000-0000-000000000044\n',text=True,capture_output=True)
            self.assertNotIn('00000000-',result.stdout)
            if fail:
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(p.read_text() if p.exists() else None,original if exists else None)
            else:
                self.assertEqual(result.returncode,0,result.stderr)
                lines=p.read_text().splitlines()
                self.assertEqual(sum(line.startswith('YANDEX_GEOCODER_KEY=') for line in lines),1)
                self.assertIn('YANDEX_GEOCODER_KEY="00000000-0000-0000-0000-000000000044"',lines)
                if exists:
                    self.assertIn('EXISTING_SECRET="synthetic-safe"',lines);self.assertIn('OTHER=value',lines)
                    self.assertEqual(p.stat().st_mode&0o777,0o640)
                    self.assertEqual(next(backup.glob('*/secrets.env')).read_text(),original)
                else:self.assertEqual(p.stat().st_mode&0o777,0o600)

    def test_replace_only_target_key(self):self.run_fixture()
    def test_new_secret_file(self):self.run_fixture(exists=False)
    def test_restore_old_config_after_restart_failure(self):self.run_fixture(fail=True)
    def test_remove_new_config_after_restart_failure(self):self.run_fixture(exists=False,fail=True)


if __name__=='__main__':unittest.main()
