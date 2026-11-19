"""Fingerprint complete bot replies; wording may vary, facts must not."""
import hashlib
import re
import unicodedata

VERSION = 1


def fingerprint(reply: str) -> str | None:
    if not isinstance(reply, str):
        raise TypeError('An original reply string is required')
    if not reply.strip():
        return None  # A silent wait or veto is not an outgoing message.
    text = unicodedata.normalize('NFKD', reply).casefold()
    text = ''.join(c for c in text if unicodedata.category(c) not in ('Mn', 'Cf'))
    text = re.sub(r'(?<=\d)[\s]+(?=\d{3}\b)', '', text)
    text = ' '.join(''.join(c if c.isalnum() else ' ' for c in text).split())
    if not text:
        raise ValueError('A reply cannot consist only of formatting or symbols')
    return hashlib.sha256(('reply-v1\0' + text).encode()).hexdigest()
