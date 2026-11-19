import contextlib
import io
import unittest
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from unittest.mock import patch

import server


class Image252Tests(unittest.TestCase):
    def setUp(self):
        for name in ('_IMG_CACHE', '_IMG_FAIL'):
            p = patch.object(server, name, type(getattr(server, name))())
            p.start(); self.addCleanup(p.stop)

    def transport(self, redirect):
        calls = []
        class FakeHTTP(urllib.request.BaseHandler):
            handler_order = 100
            def http_open(self, request):
                calls.append(request.full_url)
                headers = Message()
                if redirect and len(calls) == 1:
                    headers['Location'] = 'http://127.0.0.1/private.png'
                    result = urllib.response.addinfourl(io.BytesIO(), headers, request.full_url, 302)
                    result.msg = 'Found'
                else:
                    result = urllib.response.addinfourl(io.BytesIO(b'\x89PNGsynthetic-only'), headers, request.full_url, 200)
                    result.msg = 'OK'
                return result
            https_open = http_open
        original = urllib.request.build_opener
        old_opener = original(urllib.request.ProxyHandler({}), FakeHTTP())
        patches = [patch('urllib.request.urlopen', side_effect=old_opener.open),
                   patch('urllib.request.build_opener', side_effect=lambda *handlers: original(*handlers, FakeHTTP())),
                   patch.object(server, '_img_url_ok', return_value=True),
                   patch.object(server, '_downscale', side_effect=lambda raw: (raw, None))]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        return calls

    def test_allowed_initial_host_does_not_authorize_an_internal_redirect(self):
        calls = self.transport(True)
        result = server._fetch_image_block('https://img.avito.st/synthetic.png')
        self.assertEqual(calls, ['https://img.avito.st/synthetic.png'])
        self.assertIsNone(result)

    def test_direct_image_remains_bounded_and_cached(self):
        calls = self.transport(False)
        url = 'https://img.avito.st/synthetic.png'
        first = server._fetch_image_block(url)
        self.assertEqual(first['source']['media_type'], 'image/png')
        self.assertEqual(server._fetch_image_block(url), first)
        self.assertEqual(len(calls), 1)

    def test_rejected_signed_image_url_is_not_logged(self):
        text = io.StringIO()
        with patch.object(server, '_img_url_ok', return_value=False), contextlib.redirect_stdout(text):
            self.assertIsNone(server._fetch_image_block('https://external.invalid/image?token=synthetic-private-signature'))
        self.assertNotIn('synthetic-private-signature', text.getvalue())
        self.assertNotIn('external.invalid', text.getvalue())

    def test_http_error_response_is_closed_when_image_is_rejected(self):
        stream = io.BytesIO(b'synthetic error body')
        error = urllib.error.HTTPError('https://img.avito.st/synthetic.png', 302, 'Found', Message(), stream)
        opener = type('Opener', (), {'open': lambda *args, **kw: (_ for _ in ()).throw(error)})()
        try:
            with patch.object(server, '_img_url_ok', return_value=True), patch('urllib.request.build_opener', return_value=opener):
                self.assertIsNone(server._fetch_image_block('https://img.avito.st/synthetic.png'))
            self.assertTrue(stream.closed)
        finally:
            error.close()


if __name__ == '__main__':
    unittest.main()
