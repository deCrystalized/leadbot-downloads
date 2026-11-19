import io
import unittest
from unittest.mock import patch
import urllib.parse

import avito_api


class LegacyAvito252Tests(unittest.TestCase):
    def test_messages_accept_supported_list_or_envelope(self):
        rows = [{'id': 'b', 'created': 2}, {'id': 'a', 'created': 1}]
        with patch.object(avito_api, 'self_id', return_value='synthetic-user'), patch.object(avito_api, '_auth', return_value={}):
            for payload in [rows, {'messages': rows}]:
                with self.subTest(payload=payload), patch.object(avito_api, '_req', return_value=payload):
                    self.assertEqual([m['id'] for m in avito_api.messages({}, 'synthetic-chat')], ['a', 'b'])

    def test_invalid_json_is_a_safe_client_error(self):
        raw = io.BytesIO(b'synthetic private upstream body')
        with patch('urllib.request.urlopen', return_value=raw):
            with self.assertRaises(avito_api.AvitoError) as error:
                avito_api._req('GET', 'https://api.avito.ru/synthetic')
        self.assertNotIn('private', str(error.exception))
        self.assertTrue(raw.closed)

    def test_unknown_message_shapes_are_errors_instead_of_an_empty_history(self):
        with patch.object(avito_api, 'self_id', return_value='synthetic-user'), patch.object(avito_api, '_auth', return_value={}):
            for payload in [None, 1, 'private', {}, {'messages': 'private'}, {'messages': [None]}]:
                with self.subTest(payload=payload), patch.object(avito_api, '_req', return_value=payload):
                    with self.assertRaises(avito_api.AvitoError):
                        avito_api.messages({}, 'synthetic-chat')

    def test_chat_ids_are_one_path_segment_for_every_messenger_method(self):
        chat = '../synthetic/other?x=1'
        urls = []
        def request(method, url, **kwargs):
            urls.append(url)
            return {'messages': []}
        with patch.object(avito_api, 'self_id', return_value='synthetic-user'), patch.object(avito_api, '_auth', return_value={}), patch.object(avito_api, '_req', side_effect=request):
            avito_api.messages({}, chat)
            avito_api.send({}, chat, 'synthetic-not-sent')
            avito_api.mark_read({}, chat)
        segment = urllib.parse.quote(chat, safe='')
        self.assertEqual(len(urls), 3)
        self.assertTrue(all('/chats/'+segment+'/' in url for url in urls))


if __name__ == '__main__':
    unittest.main()
