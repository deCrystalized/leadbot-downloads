"""Finite caller/broker deadlines without network, credentials or generation."""
import io
import json
import os
import unittest
from unittest.mock import patch
import gigachat_api


class BrokerDeadline180Tests(unittest.TestCase):
    def call(self, **kwargs):
        calls = []
        def open_fake(req, timeout):
            calls.append((json.loads(req.data), timeout))
            return io.BytesIO(json.dumps({'ok': True, 'text': '{}', 'model': 'GigaChat-2-Pro'}).encode())
        with patch.dict(os.environ, {'LEADBOT_SERVICE_TOKEN': 'synthetic-only'}, clear=True), \
                patch.object(gigachat_api.urllib.request, 'urlopen', side_effect=open_fake):
            result = gigachat_api.messages('system', [dict(role='user', content='task')], **kwargs)
        return calls, result

    def test_default_outer_wait_exceeds_full_model_budget(self):
        calls, result = self.call()
        self.assertEqual(calls, [({'system': 'system', 'task': 'task', 'max_tokens': 350, 'deadline_ms': 30000}, 35)])
        self.assertEqual(result['provider'], 'gigachat')

    def test_existing_eight_second_legacy_caller_shortens_inner_budget(self):
        calls, _ = self.call(timeout=8)
        self.assertEqual(calls[0][0]['deadline_ms'], 7500)
        self.assertEqual(calls[0][1], 8)

    def test_excessive_outer_wait_is_capped_without_extra_requests(self):
        calls, _ = self.call(timeout=600, retries=100)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 35)
        self.assertEqual(calls[0][0]['deadline_ms'], 30000)

    def test_short_wait_cannot_leave_long_generation_running(self):
        calls, _ = self.call(timeout=1)
        self.assertEqual(calls[0][0]['deadline_ms'], 500)
        self.assertEqual(calls[0][1], 1)

    def test_invalid_deadline_never_reaches_transport(self):
        for value in [0, -5, float('inf'), float('nan'), '35', None]:
            with self.subTest(value=value), self.assertRaises(gigachat_api.GigaChatError):
                self.call(timeout=value)

    def test_timeout_is_terminal_and_error_does_not_expose_source_or_credentials(self):
        with patch.dict(os.environ, {'LEADBOT_SERVICE_TOKEN': 'synthetic-secret'}, clear=True), \
                patch.object(gigachat_api.urllib.request, 'urlopen', side_effect=TimeoutError('private source')) as transport:
            with self.assertRaises(gigachat_api.GigaChatError) as error:
                gigachat_api.messages('private system', [dict(role='user', content='private task')])
        self.assertEqual(transport.call_count, 1)
        self.assertNotIn('private', str(error.exception))
        self.assertNotIn('synthetic-secret', str(error.exception))
