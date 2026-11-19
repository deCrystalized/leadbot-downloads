"""Causal development replay; the locked final cohort is never eligible."""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'leadbot/brain'))
if os.environ.get('LEADBOT_OFFLINE_POLICY_DIR'):
    frozen = Path(os.environ['LEADBOT_OFFLINE_POLICY_DIR']).resolve()
    assert frozen.is_relative_to(ROOT / 'test-artifacts') and frozen.is_dir()
    sys.path.insert(0, str(frozen))
from extension_assistant import Assistant
from assistant_store import Store
from contact_cities import city_by_slug
import contact_phone


def fact_mismatches(facts, expected):
    """Check only facts adjudicated before implementation, including extras."""
    def value(path):
        result = facts
        for key in path.split('.'):
            if not isinstance(result, dict):
                return None
            result = result.get(key)
        return result

    failures = []
    for path, wanted in expected.get('required_facts', {}).items():
        if value(path) != wanted:
            failures.append(('required fact mismatch', path, value(path), wanted))
    for key, forbidden in (('required_fact_patterns', False), ('forbidden_fact_patterns', True)):
        for path, pattern in expected.get(key, {}).items():
            actual = value(path)
            rendered = json.dumps(actual, ensure_ascii=False) if isinstance(actual, (list, dict)) else str(actual or '')
            matched = bool(re.search(pattern, rendered, re.IGNORECASE))
            if matched == forbidden:
                failures.append((key, path, pattern))
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    parser.add_argument('--tag', choices=('baseline', 'final'), required=True)
    parser.add_argument('--through', type=int, default=0, help='Replay an explicitly reviewed leading subset; never counts a complete party')
    parser.add_argument('--adjudications', help='Separate primary-source adjudication file in this party; original labels stay intact')
    args = parser.parse_args()
    assert re.fullmatch(r'\d+-\d+', args.batch)
    outdir = ROOT / ('test-artifacts/human-practice/manual-batch' + args.batch)
    selected = json.loads((outdir / 'selection-private.json').read_text())
    assert_development_dialogues(r['cid'] for r in selected)
    rows = json.loads((outdir / 'sources-private.json').read_text())
    assert_development_phones(phone.value for r in rows for m in r['messages'] if m['direction'] == 'in' for phone in contact_phone.find_all(m.get('text') or m.get('transcript') or ''))
    ledger = {r['case']: r for r in json.loads((outdir / 'manual-review-private.json').read_text())}
    adjudications = {}
    if args.adjudications:
        p = (outdir / args.adjudications).resolve()
        assert p.parent == outdir.resolve() and p.suffix == '.json'
        adjudicated = json.loads(p.read_text())
        assert adjudicated['original_ledger_sha256'] == hashlib.sha256((outdir / 'manual-review-private.json').read_bytes()).hexdigest()
        for row in adjudicated['resolutions']:
            assert row['primary_rule_ids'] and row['reason'] and row['reviewed'] is True
            key = (row['case'], row['cut'])
            assert key not in adjudications
            original = next(x for x in [ledger[row['case']], *ledger[row['case']].get('additional_prefixes', [])] if x['cut'] == row['cut'])
            assert original['expected_action'] == row['original_expected_action']
            adjudications[key] = row['resolved_expectation']
    assert {r['cid'] for r in rows} == {r['cid'] for r in selected}
    if args.through:
        assert min(r['number'] for r in rows) <= args.through <= max(r['number'] for r in rows)
        rows = [r for r in rows if r['number'] <= args.through]
    os.environ['LEADBOT_ASSISTANT_WORDING'] = 'reviewed'
    results = []
    additional_results = []
    mismatches = []
    with tempfile.TemporaryDirectory() as temp:
        app = Assistant(Store(str(Path(temp) / 'db')))
        for row in rows:
            number, source = row['number'], row['source']
            city = city_by_slug(source.get('city'))
            title = source.get('account_title') or ''
            direction = next((d for label, d in (('МНЧ', 'mnc'), ('КП', 'kp'), ('БТ', 'bt')) if label in title), '')
            base_ctx = {'convId': 'manual-program-' + str(number), 'city': city.name if city else source.get('city'), 'dir': direction,
                   'partner': source.get('partner'), 'accountTitle': title, 'origin': source.get('origin'),
                   'itemTitle': source.get('item_title'), 'channel': source.get('channel')}
            for extra_index, expected in enumerate([ledger[number], *ledger[number].get('additional_prefixes', [])]):
                expected = dict(expected, **adjudications.get((number, expected['cut']), {}))
                assert 0 < expected['cut'] <= len(row['messages'])
                history = row['messages'][:expected['cut']]
                linked = source.get('crm_at') and source['crm_at'] <= history[-1]['ts']
                ctx = dict(base_ctx, crmRequestId=str(source['crm_request_id']) if linked else '',
                   messages=[{'id': m['id'], 'direction': m['direction'], 'sender_type': m.get('sender_type'),
                                 'body': m.get('text') or m.get('transcript') or '', 'created_at': m['ts'],
                                 'voice_transcript': m.get('transcript') or '', 'delivery_status': m.get('delivery') or '',
                                 'attachments': m.get('attachments') or []} for m in history])
                decision, code = app.handle({'owner': 'offline-manual-program', 'action': 'preview', 'ctx': ctx})
                assert code == 200 and decision.get('auto_enabled') is False
                assert not decision.get('pending_model') and not decision.get('validation')
                if args.tag == 'final':
                    if decision['action'] != expected['expected_action']:
                        mismatches.append((number, extra_index, 'action', decision['action'], expected['expected_action'], decision.get('reason')))
                    for pattern in expected.get('required_reply_patterns', []):
                        if not re.search(pattern, decision.get('reply') or '', re.IGNORECASE):
                            mismatches.append((number, extra_index, 'required answer intent missing', pattern))
                    for pattern in expected.get('forbidden_reply_patterns', []):
                        if re.search(pattern, decision.get('reply') or '', re.IGNORECASE):
                            mismatches.append((number, extra_index, 'forbidden answer intent', pattern))
                    for pattern in expected.get('required_reason_patterns', []):
                        if not re.search(pattern, decision.get('reason') or '', re.IGNORECASE):
                            mismatches.append((number, extra_index, 'required reason missing', pattern))
                    mismatches.extend((number, extra_index, *failure) for failure in fact_mismatches(decision.get('facts') or {}, expected))
                record = {'case': number, 'cid': row['cid'], 'cut': len(history), 'ctx': ctx, 'decision': decision,
                          'current_crm_fields_used_as_input': False, 'send_authorized': False}
                (additional_results if extra_index else results).append(record)
                print(number, 'extra' if extra_index else '', decision['action'], decision.get('reply'), decision.get('reason'))
    p = outdir / (args.tag + '-proposals-private.json')
    p.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    p.chmod(0o600)
    p = outdir / (args.tag + '-additional-proposals-private.json')
    p.write_text(json.dumps(additional_results, ensure_ascii=False, indent=2) + '\n')
    p.chmod(0o600)
    assert not mismatches, mismatches


if __name__ == '__main__':
    main()
