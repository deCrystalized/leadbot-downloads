import contextlib
import io
import json
import unittest
from email.message import Message
from unittest.mock import patch

import server


def handler(path='/api/crm/status', payload=b'{}', lengths=None):
    h = server.Handler.__new__(server.Handler)
    h.path = path
    h.client_address = ('203.0.113.1', 1234)
    h.headers = Message()
    for value in lengths if lengths is not None else [str(len(payload))]:
        h.headers['Content-Length'] = value
    h.rfile = io.BytesIO(payload)
    h.connection = type('Connection', (), {'settimeout': lambda self, value: None})()
    h.responses = []
    h._send = lambda code, body=None, **kw: h.responses.append((code, body))
    h._gate = lambda path: False
    return h


class HTTPInput252Tests(unittest.TestCase):
    def test_panel_cookie_must_have_exact_name_and_value(self):
        h = handler()
        with patch.object(server, '_panel_token', return_value='synthetic-panel-secret'):
            for value in ['other_lb_panel=synthetic-panel-secret', 'lb_panel=synthetic-panel-secret-suffix',
                          'lb_panel=wrong; lb_panel=synthetic-panel-secret']:
                h.headers['Cookie'] = value
                self.assertFalse(h._authed(), value)
                del h.headers['Cookie']
            h.headers['Cookie'] = 'another=ok; lb_panel=synthetic-panel-secret'
            self.assertTrue(h._authed())

    def test_panel_link_and_query_values_never_enter_http_log(self):
        h = handler()
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            h.log_message('"%s" %s', 'GET /panel/synthetic-panel-secret?token=synthetic-query-secret HTTP/1.1', '302')
        self.assertNotIn('synthetic-panel-secret', text.getvalue())
        self.assertNotIn('synthetic-query-secret', text.getvalue())

    def test_remote_panel_cookie_is_secure(self):
        h = handler('/panel/synthetic-panel-secret')
        h.headers_sent = []
        h.send_response = lambda code: None
        h.send_header = lambda key, value: h.headers_sent.append((key, value))
        h.end_headers = lambda: None
        del h._gate
        with patch.object(server, '_panel_token', return_value='synthetic-panel-secret'):
            self.assertTrue(h._gate(h.path))
        self.assertIn('; Secure', dict(h.headers_sent)['Set-Cookie'])

    def test_invalid_framing_stops_before_read_or_route(self):
        cases = [(['-1'], None), (['abc'], None), (['2', '3'], None), ([str(12*1024*1024+1)], None),
                 (['2'], 'chunked')]
        for lengths, transfer in cases:
            with self.subTest(lengths=lengths, transfer=transfer):
                h = handler(lengths=lengths)
                if transfer: h.headers['Transfer-Encoding'] = transfer
                with patch.object(server, '_crm_status_save') as save:
                    h.do_POST()
                self.assertIn(h.responses[0][0], (400, 413))
                self.assertEqual(h.rfile.tell(), 0)
                save.assert_not_called()

    def test_body_reader_itself_rejects_bad_framing_and_nonobject_json(self):
        for lengths, raw in [(['-1'], b'{}'), (['2', '3'], b'{}'), (['3'], b'{}'), (['2'], b'[]')]:
            with self.subTest(lengths=lengths, raw=raw):
                h = handler(payload=raw, lengths=lengths)
                with self.assertRaises(ValueError):
                    h._body()

    def test_malformed_nonobject_or_truncated_json_stops_before_route(self):
        for raw, lengths in [(b'{', None), (b'[]', None), (b'null', None), (b'\xff', None), (b'{}', ['3'])]:
            with self.subTest(raw=raw):
                h = handler(payload=raw, lengths=lengths)
                with patch.object(server, '_crm_status_save') as save:
                    h.do_POST()
                self.assertEqual(h.responses[0][0], 400)
                save.assert_not_called()

    def test_extension_cap_is_checked_before_body_read(self):
        h = handler(server.EXTENSION_ASSISTANT_PATH, lengths=['1000001'])
        h.do_POST()
        self.assertEqual(h.responses[0][0], 413)
        self.assertEqual(h.rfile.tell(), 0)

    def test_status_route_consumes_its_own_valid_body_once(self):
        h = handler(payload=json.dumps({'статусы': [{'id': 'synthetic'}]}).encode())
        with patch.object(server, '_crm_status_save', return_value=0) as save:
            h.do_POST()
        save.assert_called_once_with([{'id': 'synthetic'}])
        self.assertEqual(h.responses[0], (200, {'ok': True, 'сохранено': 0}))


if __name__ == '__main__':
    unittest.main()
