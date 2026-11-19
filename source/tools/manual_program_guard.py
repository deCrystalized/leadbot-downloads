"""Prevent development replays from opening the locked final client cohort."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / 'test-artifacts/human-practice/manual-program-1000'


def active_program_path():
    """An audited rotation keeps the original roster intact as an archive."""
    pointer = PROGRAM / 'active-validation.json'
    if not pointer.exists():
        return PROGRAM
    config = json.loads(pointer.read_text())
    directory = config['directory']
    if not re.fullmatch(r'validation-v\d+-\d{8}', directory):
        raise AssertionError('Invalid validation directory')
    active = PROGRAM / directory
    manifest = active / 'manifest.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != config['manifest_sha256']:
        raise AssertionError('Active validation manifest modified')
    return active


def _verified_roster():
    program = active_program_path()
    manifest = json.loads((program / 'manifest.json').read_text())
    roster = (program / 'final-holdout-private.json').read_bytes()
    if hashlib.sha256(roster).hexdigest() != manifest['final_manifest_sha256']:
        raise AssertionError('Final cohort modified')
    protection = json.loads((program / 'final-protected-dialogues-private.json').read_text())
    if protection['source_final_manifest_sha256'] != manifest['final_manifest_sha256']:
        raise AssertionError('Protection index does not match the final cohort')
    return roster, protection


def assert_development_dialogues(cids):
    _, protection = _verified_roster()
    if set(cids) & set(protection['protected_cids']):
        raise AssertionError('Development would expose a final validation client')


def assert_development_phones(phones):
    """Check fresh incoming identities without exposing final bodies/targets."""
    _, protection = _verified_roster()
    protected = set(protection['protected_identity_keys'])  # missing audit fails closed
    for value in phones:
        digits = re.sub(r'\D', '', str(value))
        if len(digits) not in (10, 11):
            raise AssertionError('Identity requires a complete confirmed phone')
        key = hashlib.sha256(('phone:' + digits[-10:]).encode()).hexdigest()
        if key in protected:
            raise AssertionError('Fresh development phone belongs to a final validation client')


def assert_development_digit_fragments(messages, fields=('text', 'transcript')):
    """Guard possible identities split across any number of client messages.

    These conservative candidates protect the sealed cohort; they never become
    a CRM contact or a claim that the client supplied an unambiguous phone.
    """
    candidates = set()
    for field in fields:
        run = []
        for row in messages:
            sender = row.get('sender_type') or ''
            if row.get('direction') in ('note', 'system') or sender in ('system', 'avito'):
                continue
            value = str(row.get(field) or '')
            client = (row.get('direction') == 'in' or row.get('role') in ('user', 'client')) and sender not in ('operator', 'employee', 'human', 'assistant', 'bot')
            if not client or not re.fullmatch(r'[\d\s()+.\-\u2010-\u2015]+', value) or not re.search(r'\d', value):
                run = []
                continue
            run.append(re.sub(r'\D', '', value))
            # A possible full identity has at most11 digits, not at most8
            # messages: the client may type one digit per message.
            total = ''
            for fragment in reversed(run):
                total = fragment + total
                if len(total) > 11:
                    break
                if len(total) in (10, 11):
                    candidates.add(total)
            run = run[-11:]
    assert_development_phones(candidates)
    return len(candidates)


def assert_development_groups(groups):
    """Legacy reviewed examples retain client-group hashes rather than raw IDs."""
    roster, protection = _verified_roster()
    protected = {row['client_group'] for row in json.loads(roster)} | set(protection['protected_identity_keys'])
    groups = set(groups)
    if not all(isinstance(group, str) and re.fullmatch(r'[a-f0-9]{64}', group) for group in groups):
        raise AssertionError('Missing legacy client identity')
    if groups & protected:
        raise AssertionError('Legacy development would expose a final validation client')
