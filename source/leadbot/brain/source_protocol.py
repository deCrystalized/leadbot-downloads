"""Purpose-bound read-only native LeadChat RPC, shared with its native overlay.

No user JWT, model call, credential logging or customer operation is defined.
The caller keeps signing material in trusted process memory only.
"""
import hashlib
import hmac
import json
import re
import secrets

PATH = '/api/v1/bot-dialogs/assistant/reader'
DOMAIN = b'leadbot-native-reader-v1\x00'
OPERATIONS = {'catalog', 'headers', 'history', 'image', 'run_authority'}
MAX_REQUEST = 64000
MAX_RESPONSE = 24 * 1024 * 1024


class SourceError(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw, limit=MAX_RESPONSE):
    if not isinstance(raw, bytes) or not raw or len(raw) > limit:
        raise SourceError('Source payload exceeds the exact read budget')
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise SourceError('Duplicate source field')
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(SourceError('Nonfinite source number')))
    except (ValueError, UnicodeError):
        raise SourceError('Invalid source payload') from None


def _key(key):
    if not isinstance(key, bytes) or not 32 <= len(key) <= 512 or any(chr(c).isspace() for c in key):
        raise SourceError('Native source reader is not configured')
    return key


def request(key, operation, arguments, *, actor=None, now):
    if operation not in OPERATIONS or not isinstance(arguments, dict):
        raise SourceError('Read-only source operation required')
    if actor is not None and (not isinstance(actor, dict) or set(actor) != {'principal_id', 'operator_id'}):
        raise SourceError('Exact verified native actor required')
    raw = encode(dict(v=1, operation=operation, arguments=arguments, actor=actor))
    if len(raw) > MAX_REQUEST:
        raise SourceError('Source request exceeds its budget')
    stamp, nonce = str(int(now)), secrets.token_urlsafe(24)
    message = DOMAIN + b'POST\n' + PATH.encode() + b'\n' + stamp.encode() + b'\n' + nonce.encode() + b'\n' + sha(raw).encode()
    signature = hmac.new(_key(key), message, hashlib.sha256).hexdigest()
    return raw, {'X-LB-Read-Time': stamp, 'X-LB-Read-Nonce': nonce, 'X-LB-Read-Signature': signature}


def verify(key, raw, headers, *, now):
    stamp, nonce, signature = (headers.get(k, '') for k in ('x-lb-read-time', 'x-lb-read-nonce', 'x-lb-read-signature'))
    if (not re.fullmatch(r'\d{10}', stamp) or abs(now-int(stamp)) > 30
            or not re.fullmatch(r'[A-Za-z0-9_-]{32}', nonce)
            or not re.fullmatch(r'[a-f0-9]{64}', signature)):
        raise SourceError('Source read authentication expired or invalid')
    message = DOMAIN + b'POST\n' + PATH.encode() + b'\n' + stamp.encode() + b'\n' + nonce.encode() + b'\n' + sha(raw).encode()
    expected = hmac.new(_key(key), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise SourceError('Source read authentication failed')
    value = decode(raw, MAX_REQUEST)
    if (not isinstance(value, dict) or set(value) != {'v', 'operation', 'arguments', 'actor'}
            or type(value['v']) is not int or value['v'] != 1 or value['operation'] not in OPERATIONS
            or not isinstance(value['arguments'], dict)):
        raise SourceError('Exact read-only source envelope required')
    actor = value['actor']
    if actor is not None and (not isinstance(actor, dict) or set(actor) != {'principal_id', 'operator_id'}):
        raise SourceError('Exact verified actor required')
    return value, nonce


def response_signature(key, raw, nonce):
    return hmac.new(_key(key), DOMAIN+b'response\n'+nonce.encode()+b'\n'+sha(raw).encode(), hashlib.sha256).hexdigest()


def verify_response(key, raw, nonce, signature):
    if not isinstance(signature, str) or not hmac.compare_digest(signature, response_signature(key, raw, nonce)):
        raise SourceError('Native source response binding failed')
    return decode(raw)
