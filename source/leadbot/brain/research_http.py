"""Explicit one-attempt Responses HTTPS transport. Construction is offline.

No API wallet/key detection, redirects, proxies, retries or alternate hosts.
Credentials are loaded only by a trusted prepare step, before a body can be
journalled. Returned bytes are unchanged; metadata excludes headers/secrets.
"""
import http.client
import json
import math
import os
import re
import ssl
import stat
import time
import hashlib
from pathlib import Path

from research_openai import RequestNotStarted, MAX_OUTPUT_TOKENS
from research_pipeline import models_for, TOOLS
from research_receipts import HTTPReceipt, HTTPFailure, ProviderResult
import research_cache


MAX_REQUEST_BYTES = 20 * 1024 * 1024
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_FIELDS = {'model','store','parallel_tool_calls','max_output_tokens','reasoning',
           'instructions','input','tools','text','service_tier','prompt_cache_options'}


class HTTPTransport:
    def __init__(self, key_file, *, enabled=False, profile='sol_only',
                 connection_factory=http.client.HTTPSConnection, clock=time.monotonic):
        if type(enabled) is not bool or not callable(connection_factory):
            raise ValueError('Explicit trusted HTTP configuration required')
        self.profile, self.models = profile, models_for(profile)
        self.key_file, self.enabled = Path(key_file).absolute(), enabled
        self.connection_factory, self.clock = connection_factory, clock

    def _key(self):
        try:
            if any(p.is_symlink() for p in [self.key_file, *self.key_file.parents]):
                raise ValueError('symlink')
            fd = os.open(self.key_file, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 1024):
                    raise ValueError('private file')
                with os.fdopen(fd,'rb') as stream:
                    fd = None
                    value = stream.read(1025)
            finally:
                if fd is not None:os.close(fd)
            if not re.fullmatch(rb'sk-[A-Za-z0-9_-]{20,509}', value):
                raise ValueError('format')
            return value
        except (OSError,ValueError):
            raise RequestNotStarted('Private credential is unavailable or unsafe; no provider attempt') from None

    def prepare(self, payload):
        """Called inside grant checks but BEFORE reservation/body journalling."""
        if not self.enabled:
            raise RequestNotStarted('HTTP transport is explicitly disabled')
        if (not isinstance(payload,dict) or set(payload)!=_FIELDS or payload.get('model') not in self.models.values()
                or payload.get('store') is not False or payload.get('parallel_tool_calls') is not False
                or type(payload.get('max_output_tokens')) is not int or not 1<=payload['max_output_tokens']<=MAX_OUTPUT_TOKENS
                or not isinstance(payload.get('instructions'),str) or not isinstance(payload.get('input'),list)
                or payload.get('reasoning')!={'effort':'max'}
                or payload.get('service_tier')!='default'
                or not isinstance(payload.get('tools'),list)
                or any(not isinstance(t,dict) or t.get('type')!='function' or t.get('name') not in TOOLS
                       or t.get('strict') is not True for t in payload['tools'])):
            raise RequestNotStarted('Unadmitted provider body/model/options')
        try:
            research_cache.validate(payload)
            instructions=json.loads(payload['instructions'])
            if (not isinstance(instructions,dict) or instructions.get('profile')!=self.profile
                    or self.models.get(instructions.get('role'))!=payload['model']):
                raise ValueError('role')
        except (ValueError,TypeError):
            raise RequestNotStarted('Provider role/profile/model mismatch; no automatic routing') from None
        try:
            raw = json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        except (ValueError,TypeError):
            raise RequestNotStarted('Provider body is not strict JSON') from None
        if not raw or len(raw)>MAX_REQUEST_BYTES:
            raise RequestNotStarted('Provider body exceeds the explicit size budget')
        secret = self._key()
        if secret in raw:
            raise RequestNotStarted('Credential found in model body; do not persist or send it')
        return Prepared(self,raw,secret)

    def __call__(self, payload, timeout):
        return self.prepare(payload)(timeout)


class Prepared:
    transport_kind = 'openai_https_v1'

    def __init__(self, transport, raw, secret):
        self.transport = transport
        self.body_sha256 = hashlib.sha256(raw).hexdigest()
        self._body, self._secret = raw, secret
        self.used = False

    def __call__(self, timeout):
        if self.used:
            raise RequestNotStarted('Prepared request is single-use; no retry')
        self.used = True
        if (isinstance(timeout,bool) or not isinstance(timeout,(int,float))
                or not math.isfinite(timeout) or not 0<timeout<=300):
            raise RequestNotStarted('Invalid remaining provider deadline')
        clock = self.transport.clock
        deadline = clock()+timeout
        conn, sent, chunks, size, tail = None, False, [], 0, b''
        def partial():
            value = b''.join(chunks)
            return b'' if self._secret in value else value[:MAX_RESPONSE_BYTES]
        def remaining():
            value = deadline-clock()
            if value<=0:raise HTTPFailure('deadline',partial())
            if conn is not None and conn.sock is not None:conn.sock.settimeout(value)
            return value
        try:
            ctx = ssl.create_default_context()
            conn = self.transport.connection_factory('api.openai.com',port=443,timeout=remaining(),context=ctx)
            conn.set_debuglevel(0)
            conn.connect()
            remaining()
            sent = True  # Any exception after writing may have reached the provider.
            conn.request('POST','/v1/responses',body=self._body,
                         headers={'Authorization':'Bearer '+self._secret.decode('ascii'),
                                  'Content-Type':'application/json','Accept':'application/json',
                                  'User-Agent':'LeadBot-Research/1','Connection':'close'})
            remaining()
            response = conn.getresponse()
            metadata = dict(schema=1,http_status=response.status,
                content_type='json' if str(response.getheader('Content-Type','')).split(';',1)[0].lower()=='application/json' else 'other')
            request_id = response.getheader('X-Request-ID','')
            if isinstance(request_id,str) and re.fullmatch(r'req_[A-Za-z0-9_-]{1,128}',request_id):
                metadata['request_id']=request_id
            while True:
                remaining()
                block = response.read1(min(65536,MAX_RESPONSE_BYTES-size+1))
                if not isinstance(block,bytes):raise HTTPFailure('invalid_http_metadata',partial())
                if not block:break
                chunks.append(block);size+=len(block)
                window=tail+block
                if self._secret in window:
                    raise HTTPFailure('credential_reflected')
                tail=window[-(len(self._secret)-1):]
                if size>MAX_RESPONSE_BYTES:
                    raise HTTPFailure('response_too_large',partial())
            remaining()
            try:
                return HTTPReceipt(b''.join(chunks),metadata)
            except ValueError:
                raise HTTPFailure('invalid_http_metadata',partial()) from None
        except HTTPFailure:
            raise
        except Exception:
            if not sent:
                raise RequestNotStarted('Provider preflight/connect stopped before body write') from None
            raise HTTPFailure('network',partial()) from None
        finally:
            if conn is not None:
                try:conn.close()
                except Exception:pass
