"""Authenticated read-only LeadChat source client; no browser URL or JWT.

The application supplies current identities only after its normal actor gate.
Archive metadata/body access is a separately enabled integration scope.
"""
import base64
import hashlib
import http.client
import ssl
import time
import uuid
from urllib.parse import urlsplit

import source_protocol as protocol

HOSTS = {'chat.partner-lead-centre.ru', '188-225-34-82.sslip.io'}


class NativeSources:
    def __init__(self, url, *, key, header_guard, cid_guard, connection_factory=None, clock=time.time):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.port not in (None, 443)
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username or parsed.password
                or not callable(key) or not callable(header_guard) or not callable(cid_guard)):
            raise protocol.SourceError('Trusted fixed native source configuration required')
        self.host, self.key, self.header_guard, self.cid_guard = parsed.hostname, key, header_guard, cid_guard
        self.connection_factory = connection_factory or http.client.HTTPSConnection
        self.clock = clock

    def _call(self, operation, arguments, actor=None,*,seconds=25):
        if type(seconds)not in(int,float) or not 0<seconds<=300:
            raise protocol.SourceError('Finite native source deadline required')
        deadline=time.monotonic()+seconds
        key = self.key()
        raw, headers = protocol.request(key, operation, arguments, actor=actor, now=self.clock())
        context = ssl.create_default_context()
        connection = self.connection_factory(self.host, 443, timeout=min(25,seconds), context=context)
        def remaining():
            left=deadline-time.monotonic()
            if left<=0:raise protocol.SourceError('Native source deadline expired')
            sock=getattr(connection,'sock',None)
            if sock is not None:sock.settimeout(min(25,left))
        try:
            remaining()
            connection.request('POST', protocol.PATH, body=raw,
                headers={**headers, 'Content-Type': 'application/json', 'Accept': 'application/json'})
            remaining()
            response = connection.getresponse()
            if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'application/json':
                raise protocol.SourceError('Native read was rejected; no source fallback')
            chunks, size = [], 0
            while True:
                remaining()
                chunk = response.read(min(65536, protocol.MAX_RESPONSE+1-size))
                if not chunk:break
                size += len(chunk)
                if size > protocol.MAX_RESPONSE:
                    raise protocol.SourceError('Native source response exceeds its budget')
                chunks.append(chunk)
            value = protocol.verify_response(key, b''.join(chunks), headers['X-LB-Read-Nonce'],
                                             response.getheader('X-LB-Read-Signature'))
        except protocol.SourceError:
            raise
        except Exception:
            raise protocol.SourceError('Native source observation failed; no automatic retry') from None
        finally:
            connection.close()
        if not isinstance(value, dict) or set(value) != {'ok', 'data'} or value['ok'] is not True or not isinstance(value['data'], dict):
            raise protocol.SourceError('Exact authenticated source response required')
        return value['data']

    def run_authority(self, run_id, generation, actor):
        """Fresh signed server-run metadata. Never reads a customer source/body."""
        def identifier(value):
            try:
                return isinstance(value, str) and str(uuid.UUID(value)) == value
            except (ValueError, AttributeError, TypeError):
                return False
        if (not identifier(run_id) or type(generation) is not int or not 1 <= generation <= 2**63-1
                or not isinstance(actor, dict) or set(actor) != {'principal_id', 'operator_id'}
                or not all(identifier(v) for v in actor.values())):
            raise protocol.SourceError('Exact verified native run binding required')
        data = self._call('run_authority', dict(run_id=run_id, generation=generation), actor)
        live = data.get('authority')
        fields = {'principal_id', 'operator_id', 'run_id', 'generation', 'mode', 'versions'}
        if (set(data) != {'authority'} or not isinstance(live, dict) or set(live) != fields
                or live['run_id'] != run_id or type(live['generation']) is not int
                or live['generation'] != generation or live['mode'] not in ('auto', 'rehearsal')
                or any(live[k] != actor[k] for k in actor)
                or not isinstance(live['versions'], list) or len(live['versions']) != 4
                or any(not isinstance(v, str) or not 1 <= len(v) <= 512 or v.strip() != v
                       for v in live['versions'])):
            raise protocol.SourceError('Native run authority changed or response is incomplete')
        return live

    def catalog(self, after=None, limit=100):
        result = self._call('catalog', dict(after=after, limit=limit))
        if (set(result) != {'cids', 'next', 'complete', 'consistency'} or not isinstance(result['cids'], list)
                or len(result['cids']) > limit or len(set(result['cids'])) != len(result['cids'])
                or type(result['complete']) is not bool or result['complete'] != (result['next'] is None)
                or not result['complete'] and (not result['cids'] or result['next'] != result['cids'][-1])):
            raise protocol.SourceError('Native source roster page is incomplete')
        return result

    def header(self, cid, actor=None):
        self.cid_guard([cid])  # Known protected CID rejected before native source access.
        result = self._call('headers', dict(cids=[cid]), actor)
        if set(result) != {'headers'} or not isinstance(result['headers'], list) or len(result['headers']) != 1:
            raise protocol.SourceError('Exact native source identity header required')
        header = result['headers'][0]
        if not isinstance(header, dict) or header.get('cid') != cid:
            raise protocol.SourceError('Native source returned another identity')
        if header.get('deleted') is True or header.get('pending') is True:
            return header
        self.header_guard(header)  # Phone/group/media guards before consumer body load.
        return header

    def history(self, header, actor=None):
        if header.get('pending') or header.get('deleted'):
            raise protocol.SourceError('Incomplete source has no admitted history body')
        self.cid_guard([header['cid']]);self.header_guard(header)
        result = self._call('history', dict(cid=header['cid'], source_sha256=header['source_sha256']), actor)
        source=result.get('source')
        if (set(result)!={'header','source'} or result.get('header') != header or not isinstance(source, dict)
                or any(source.get(k)!=header.get(k) for k in ('cid','client_group','phone_hashes','media_hashes','identity_keys'))
                or protocol.sha(protocol.encode(source)) != header['source_sha256']):
            raise protocol.SourceError('Native source changed; no repaired or partial history')
        return source

    def image(self, header, descriptor, actor):
        if header.get('pending') or header.get('deleted'):
            raise protocol.SourceError('Incomplete source has no admitted original image')
        if not actor:
            raise protocol.SourceError('Current verified native actor required for original image')
        self.cid_guard([header['cid']]);self.header_guard(header)
        args = dict(cid=header['cid'], source_sha256=header['source_sha256'],
            message_id=descriptor['source_message_id'], position=descriptor['position'],
            attachment_hash=descriptor['attachment_hash'])
        result = self._call('image', args, actor)
        if any(result.get(k) != v for k, v in args.items()) or result.get('resized') is not False:
            raise protocol.SourceError('Original image scope changed')
        try:raw = base64.b64decode(result['data'], validate=True)
        except (KeyError, ValueError, TypeError):raise protocol.SourceError('Original image bytes unavailable') from None
        from research_media import _image
        if (result.get('byte_length') != len(raw) or result.get('sha256') != hashlib.sha256(raw).hexdigest()
                or result.get('mime') != _image(raw)):
            raise protocol.SourceError('Original image hash or MIME changed')
        return dict(data=raw, mime=result['mime'], sha256=result['sha256'])
