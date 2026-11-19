"""One bounded call over the existing authenticated loopback service bridge."""
import http.client
import os
import time

import native_execution_protocol as wire


class NotificationClient:
    def __init__(self, *, enabled=False, token=None, clock=time.time, connection=None):
        if type(enabled) is not bool or not callable(clock) or token is not None and not callable(token):
            raise ValueError('Trusted notification transport required')
        self.enabled, self.clock = enabled, clock
        self.token = token or (lambda: os.environ.get('LEADBOT_SERVICE_TOKEN', ''))
        self.connection = connection or http.client.HTTPConnection

    def prepare(self, body, persist):
        return self._call('prepare',body,persist)

    def send(self, body, persist, send_before):
        if type(send_before) not in (int,float) or not 0<send_before-self.clock()<=5:
            raise ValueError('Fresh short source-bound notification permission required')
        return self._call('send',body,persist,send_before)

    def _call(self, action, body, persist, send_before=None):
        if not self.enabled or not callable(persist):
            raise ValueError('Native notification transport is disabled')
        before = body.get('dispatch_before')
        if type(before) not in (int, float) or not 0 < before - self.clock() <= 90:
            raise ValueError('Original finite notification window required')
        token = self.token()
        if not isinstance(token, str) or not 16 <= len(token) <= 512 or any(c.isspace() for c in token):
            raise ValueError('Existing private service bridge unavailable')
        envelope=dict(action=action,payload=body)
        if action=='send':envelope['send_before']=send_before
        raw = wire.encode(envelope)
        if token.encode() in raw or len(raw) > 16000:
            raise ValueError('Unsafe notification request')
        conn = self.connection('127.0.0.1', 8081, timeout=max(.1, before-self.clock()))
        try:
            conn.request('POST', '/internal/leadbot/notification', body=raw,
                         headers={'Content-Type':'application/json','X-Leadbot-Token':token})
            response = conn.getresponse()
            chunks, size = [], 0
            while True:
                remaining = before-self.clock()
                if remaining <= 0:
                    raise ValueError('Original notification window expired')
                if getattr(conn, 'sock', None) is not None:
                    conn.sock.settimeout(remaining)
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > 350000:
                    raise ValueError('Notification response exceeds budget')
                chunks.append(chunk)
            body_raw = b''.join(chunks)
            if token.encode() in body_raw:
                raise ValueError('Credential reflection; raw receipt must not be saved')
            content_type = response.getheader('Content-Type','').split(';')[0]
            if len(content_type) > 64 or not content_type.isascii():
                content_type = 'invalid'
            persist(response.status, content_type, body_raw)
            if response.status != 200 or content_type != 'application/json':
                raise ValueError('Original broker response unconfirmed')
            value = wire.decode(body_raw, 350000)
            if not isinstance(value, dict):
                raise ValueError('Original bounded broker object required')
            return value
        except Exception:
            raise ValueError('Observe original notification; never repeat a possible send') from None
        finally:
            conn.close()


def receipt(result, payload):
    """Recheck original Team bytes independently of the broker success flag."""
    import base64
    import hashlib
    if not isinstance(result, dict) or result.get('ok') is not True or result.get('telegram_confirmed') is not True:
        raise ValueError('Independent Telegram receipt required')
    for out, field in [('work_id','work_id'),('intent_id','intent_id'),('crm_request_id','crm_request_id'),
                       ('source_sha256','source_sha256'),('snapshot_hash','snapshot_hash'),
                       ('form_reference','form_reference'),('card_sha256','card_sha256')]:
        if result.get(out) != payload[field]:
            raise ValueError('Original notification binding changed')
    if (type(result.get('message_id')) is not int or not 1 <= result['message_id'] <= 2**53-1
            or type(result.get('topic_id')) is not int or result['topic_id'] < 1
            or not isinstance(result.get('chat_id'), str)):
        raise ValueError('Actual message/chat/topic required')
    original = result.get('original_http')
    if (not isinstance(original,dict) or set(original) != {'status','content_type','sha256','body'}
            or original['status'] != 200 or original['content_type'] != 'application/json'):
        raise ValueError('Original successful Team response required')
    raw = base64.b64decode(original['body'], validate=True)
    if len(raw) > 200000 or hashlib.sha256(raw).hexdigest() != original['sha256']:
        raise ValueError('Original Team bytes changed')
    actual = wire.decode(raw, 200000)
    text = payload['crm_request_id']+' - '+payload['source_code']+' '+{'kp':'КП','mnc':'МНЧ','bt':'БТ'}[payload['direction']]
    expected = dict(ok=True, message_id=result['message_id'], native_intent=payload['intent_id'],
                    chat_id=result['chat_id'], reply_to=result['topic_id'],
                    text_sha256=hashlib.sha256(text.encode()).hexdigest())
    if (actual != expected or type(actual.get('message_id')) is not int
            or type(actual.get('reply_to')) is not int or result.get('text_sha256') != expected['text_sha256']):
        raise ValueError('Actual Team message does not match the original intent')
    return result
