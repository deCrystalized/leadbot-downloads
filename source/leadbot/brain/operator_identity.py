"""Verify a native LeadChat admin's short-lived selected-author attestation.

The opaque proof is transport metadata. It must never enter a model task,
history, audit payload or exported diagnostic. No LeadChat JWT is accepted.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid

from assistant_store import digest

FIELDS = {'v', 'aud', 'principal_id', 'operator_id', 'principal_name',
          'operator_name', 'role', 'nonce', 'sid', 'iat', 'exp'}


def key():
    value = os.environ.get('LEADBOT_ACTOR_PROOF_KEY', '')
    return value.encode() if 32 <= len(value) <= 512 and not any(c.isspace() for c in value) else None


def uuid_string(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS operator_challenges '
               '(scope TEXT, sid TEXT, operator TEXT, nonce TEXT, expires REAL, '
               'PRIMARY KEY(scope,sid))')


def challenge(store, owner, body, now):
    sid, who = body.get('browser_session'), body.get('operator_id')
    if (not key() or not uuid_string(who) or not isinstance(sid, str)
            or not re.fullmatch(r'[A-Za-z0-9:_-]{8,120}', sid)):
        return {'ok': False, 'code': 'operator_unconfigured', 'auto_enabled': False,
                'error': 'Подключение администратора ещё не настроено'}
    nonce = secrets.token_urlsafe(32)
    with store.connect() as db:
        schema(db)
        db.execute('DELETE FROM operator_challenges WHERE expires<?', (now,))
        db.execute('INSERT OR REPLACE INTO operator_challenges VALUES(?,?,?,?,?)',
                   (digest(owner), sid, who, nonce, now + 45))
    return {'ok': True, 'nonce': nonce, 'browser_session': sid,
            'expires_at': now + 45, 'auto_enabled': False}


def no_duplicate_keys(pairs):
    out = {}
    for name, value in pairs:
        if name in out:
            raise ValueError('duplicate identity field')
        out[name] = value
    return out


def current_challenge(db, owner, data, now):
    """Recheck revocation under the caller's existing write transaction."""
    row = db.execute('SELECT * FROM operator_challenges WHERE scope=? AND sid=?',
                     (digest(owner), data['sid'])).fetchone()
    return bool(row and data['exp'] > now and row['expires'] > now
                and row['operator'] == data['operator_id']
                and hmac.compare_digest(row['nonce'], data['nonce']))


def verify(store, owner, body, now):
    """None on every malformed/unconfigured/stale proof; never echo a proof."""
    proof, secret = body.get('identity_proof'), key()
    if not secret or not isinstance(proof, str) or len(proof) > 5000:
        return None
    try:
        encoded, signature = proof.split('.')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', encoded + signature):
            return None
        expected = base64.urlsafe_b64encode(hmac.new(secret, encoded.encode(), hashlib.sha256).digest()).rstrip(b'=')
        if not hmac.compare_digest(signature.encode(), expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)), object_pairs_hook=no_duplicate_keys)
        if (not isinstance(data, dict) or set(data) != FIELDS or type(data['v']) is not int
                or data['v'] != 1 or data['aud'] != 'leadbot-browser-operator' or data['role'] != 'admin'
                or not uuid_string(data['principal_id']) or not uuid_string(data['operator_id'])
                or type(data['iat']) is not int or type(data['exp']) is not int
                or not now - 45 <= data['iat'] <= now + 3
                or not now < data['exp'] <= data['iat'] + 45
                or data['sid'] != body.get('browser_session')
                or data['operator_id'] != body.get('operator_id')
                or not all(isinstance(data[n], str) and len(data[n]) <= 300
                           for n in ('principal_name', 'operator_name', 'nonce', 'sid'))):
            return None
        with store.connect() as db:
            schema(db)
            if not current_challenge(db, owner, data, now):
                return None
        return data
    except (ValueError, TypeError, KeyError, UnicodeError):
        return None
