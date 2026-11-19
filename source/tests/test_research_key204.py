import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

from configure_research_key import Form, SetupError, save_key


FAKE = 'sk-not-a-real-api-key-only-local-test'


class KeySetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.directory = self.root/'private'
        self.form = Form(self.directory);self.form.origin = 'http://127.0.0.1:12345'
        self.headers = {'Host':'127.0.0.1:12345', 'Origin':self.form.origin,
                        'Content-Type':'application/x-www-form-urlencoded'}

    def post(self, **extra):
        fields = dict(key=FAKE, nonce=self.form.nonce);fields.update(extra)
        return self.form.handle('POST', self.form.path, self.headers, urlencode(fields).encode())

    def test_password_form_has_no_external_resource_script_or_key_echo(self):
        code, body = self.form.handle('GET', self.form.path, self.headers)
        self.assertEqual(code, 200);self.assertIn('type="password"', body)
        self.assertNotIn('<script', body);self.assertNotIn(FAKE, body)
        self.assertNotIn('https://', body);self.assertFalse(self.directory.exists())

    def test_save_is_private_single_use_and_no_provider_activation(self):
        code, body = self.post()
        self.assertEqual(code, 200);self.assertTrue(self.form.saved)
        key = self.directory/'openai.key'
        self.assertEqual(key.read_text(), FAKE)
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(FAKE, body);self.assertIn('не запускались', body)
        self.assertEqual(self.post()[0], 404)

    def test_wrong_host_nonce_path_or_content_type_cannot_save(self):
        for field, value in [('Host','evil.invalid'),('Content-Type','application/json')]:
            old = self.headers[field];self.headers[field] = value
            with self.subTest(field=field, value=value):self.assertNotEqual(self.post()[0], 200)
            self.headers[field] = old
        self.assertEqual(self.post(nonce='wrong')[0], 400)
        self.assertEqual(self.form.handle('GET','/wrong',self.headers)[0], 404)
        self.assertFalse(self.directory.exists())

    def test_expiry_duplicate_field_oversize_and_bad_key_are_not_echoed_or_saved(self):
        for raw in (b'key=x&key=y&nonce=z', b'key=x'*2000):
            self.assertNotEqual(self.form.handle('POST',self.form.path,self.headers,raw)[0], 200)
        code, body = self.post(key='private-user-input-do-not-echo')
        self.assertEqual(code,400);self.assertNotIn('private-user-input',body)
        self.form.deadline = 0
        self.assertEqual(self.post()[0],404);self.assertFalse(self.directory.exists())

    def test_existing_key_requires_explicit_replace_and_remains_on_rejection(self):
        save_key(self.directory, FAKE)
        self.assertEqual(self.post(key=FAKE+'2')[0],400)
        self.assertEqual((self.directory/'openai.key').read_text(),FAKE)
        self.assertEqual(self.post(key=FAKE+'2', replace='yes')[0],200)
        self.assertEqual((self.directory/'openai.key').read_text(),FAKE+'2')

    def test_file_and_directory_symlinks_do_not_touch_target(self):
        target = self.root/'target';target.mkdir()
        self.directory.symlink_to(target, target_is_directory=True)
        with self.assertRaises(SetupError):save_key(self.directory, FAKE)
        self.directory.unlink();self.directory.mkdir()
        key_target = target/'data';key_target.write_text('original')
        (self.directory/'openai.key').symlink_to(key_target)
        with self.assertRaises(SetupError):save_key(self.directory,FAKE,replace=True)
        self.assertEqual(key_target.read_text(),'original')

    def test_concurrent_setup_cannot_silently_replace_first_key(self):
        def save(index):
            try:
                save_key(self.directory, FAKE+str(index));return index
            except SetupError:
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(save, range(6)))
        winners = [i for i in results if i is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual((self.directory/'openai.key').read_text(), FAKE+str(winners[0]))

    def test_unicode_nonce_is_rejected_without_crashing_or_echo(self):
        code, body = self.post(nonce='неправильный')
        self.assertEqual(code,400);self.assertNotIn('неправильный',body)

    def test_browser_relay_without_origin_still_needs_private_nonce_and_same_host(self):
        self.headers.pop('Origin')
        self.assertEqual(self.post(nonce='invalid')[0],400)
        self.headers['Sec-Fetch-Site'] = 'cross-site'
        self.headers['Origin'] = 'https://browser-relay.invalid'
        self.assertEqual(self.post(nonce='invalid')[0],400)
        self.headers['Content-Type'] += '; charset=UTF-8'
        self.assertEqual(self.post()[0],200)


if __name__ == '__main__':
    unittest.main()
