import json
import unittest
from source_protocol import (request, verify, response_signature, verify_response,
                             encode, SourceError)


class SourceProtocolTests(unittest.TestCase):
    def setUp(self):
        self.key = b'public-test-only-source-key-1234567890'
        self.now = 1793070000

    def exchange(self):
        raw, headers = request(self.key, 'headers', {'cids': ['cid']}, now=self.now)
        lower = {k.lower(): v for k, v in headers.items()}
        return raw, lower

    def test_roundtrip_only_read_scope_and_exact_body(self):
        raw, headers = self.exchange()
        value, _ = verify(self.key, raw, headers, now=self.now)
        self.assertEqual(value['operation'], 'headers')
        self.assertIsNone(value['actor'])
        self.assertNotIn(self.key.decode(), raw.decode())

    def test_send_claim_sql_and_other_operations_are_not_authorized(self):
        for op in ('reply', 'claim', 'crm', 'sql', 'delete', 'telegram'):
            with self.subTest(op=op), self.assertRaises(SourceError):
                request(self.key, op, {}, now=self.now)

    def test_changed_body_stale_future_wrong_key_and_actor_cannot_borrow_signature(self):
        raw, headers = self.exchange()
        for key, data, now in ((b'different-public-test-key-123456789012', raw, self.now),
                               (self.key, raw.replace(b'cid', b'other'), self.now),
                               (self.key, raw, self.now+31), (self.key, raw, self.now-31)):
            with self.assertRaises(SourceError):verify(key, data, headers, now=now)

    def test_response_is_bound_to_request_nonce_and_exact_bytes(self):
        raw, headers = self.exchange();_, nonce = verify(self.key, raw, headers, now=self.now)
        body = encode({'ok': True, 'data': {'source': 'complete'}})
        signature = response_signature(self.key, body, nonce)
        self.assertEqual(verify_response(self.key, body, nonce, signature)['data']['source'], 'complete')
        for data, other in ((body+b' ', nonce), (body, 'different')):
            with self.assertRaises(SourceError):verify_response(self.key, data, other, signature)

    def test_actor_is_narrow_not_arbitrary_browser_credentials(self):
        with self.assertRaises(SourceError):
            request(self.key, 'image', {}, actor={'jwt': 'not-accepted'}, now=self.now)

    def test_empty_or_weak_key_does_not_enable_reader(self):
        for key in (None, b'short', b' '*40):
            with self.assertRaises(SourceError):request(key, 'catalog', {}, now=self.now)


if __name__ == '__main__':unittest.main()
