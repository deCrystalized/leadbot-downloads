"""Grade frozen human expectations for price and qualification state, offline."""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'leadbot/brain'))
if os.environ.get('LEADBOT_OFFLINE_POLICY_DIR'):
    frozen = Path(os.environ['LEADBOT_OFFLINE_POLICY_DIR']).resolve()
    assert frozen.is_relative_to(ROOT / 'test-artifacts') and frozen.is_dir()
    sys.path.insert(0, str(frozen))
import assistant_prices
import contact_phone
import qualification_state
from contact_cities import city_by_slug


def lookup(value, path):
    for key in path.split('.'):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    parser.add_argument('--tag', choices=('baseline', 'final'), required=True)
    args = parser.parse_args()
    assert re.fullmatch(r'\d+-\d+', args.batch)
    directory = ROOT / ('test-artifacts/human-practice/manual-batch' + args.batch)
    manifest = json.loads((directory / 'frozen-review-manifest.json').read_text())
    source = directory / 'sources-private.json'
    targets = directory / 'critical-calculations-private.json'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['source_sha256']
    assert hashlib.sha256(targets.read_bytes()).hexdigest() == manifest['critical_sha256']
    bindings = json.loads((directory / 'critical-grader-bindings.json').read_text())
    assert bindings['original_targets_sha256'] == manifest['critical_sha256']
    rows = json.loads(source.read_text())
    assert_development_dialogues(row['cid'] for row in rows)
    assert_development_phones(phone.value for row in rows for m in row['messages']
                              if m['direction'] == 'in'
                              for phone in contact_phone.find_all(m.get('text') or m.get('transcript') or ''))
    rows = {row['number']: row for row in rows}
    result = []
    for target in json.loads(targets.read_text()):
        row = rows[target['case']]
        assert 0 < target['cut'] <= len(row['messages'])
        # Only the causal prefix is passed to the functions being checked.
        messages = [dict(id=m['id'], body=m.get('text') or m.get('transcript') or '',
                         direction=m['direction'], sender_type=m.get('sender_type'),
                         created_at=m['ts'], attachments=m.get('attachments') or [])
                    for m in row['messages'][:target['cut']]
                    if m['direction'] != 'note' and m.get('sender_type') not in ('system', 'avito')]
        source_row = row['source']
        city = city_by_slug(source_row.get('city'))
        title = source_row.get('account_title') or ''
        direction = next((d for label, d in (('МНЧ', 'mnc'), ('КП', 'kp'), ('БТ', 'bt')) if label in title), '')
        known = dict(city=city.name if city else source_row.get('city'), direction=direction,
                     partner=source_row.get('partner'), channel=source_row.get('channel'))
        clients = '\n'.join(m['body'] for m in messages if m['direction'] == 'in')
        actual = dict(consent=assistant_prices.consent(messages),
                      asks_current=assistant_prices.asks_current(messages),
                      answered_price_turns=assistant_prices.price_turns(messages)
                      - int(assistant_prices._unanswered_price(messages)),
                      mandatory=assistant_prices.mandatory(messages, known, clients),
                      conditional_diagnostic_question=assistant_prices.conditional_diagnostic_question(messages),
                      qualification=qualification_state.inspect(messages))
        gas_value = str(actual['qualification']['gas_type'].get('value') or '')
        actual['semantic_gas_type'] = ('electric' if re.search(r'без\s+газа|электр', gas_value, re.I)
                                       else 'gas' if re.search(r'газ', gas_value, re.I) else None)
        checked = []
        for key, wanted in target['checks'].items():
            bound = bindings.get('check_path_bindings', {}).get(key, key)
            got = lookup(actual, bound)
            checked.append(dict(original_check=key, bound_check=bound,
                                expected=wanted, actual=got, passed=got == wanted))
        result.append(dict(case=target['case'], cid=row['cid'], cut=target['cut'], checks=checked,
                           passed=all(check['passed'] for check in checked),
                           current_crm_fields_used_as_input=False, customer_sends=0, crm_writes=0))
    path = directory / (args.tag + '-calculations-private.json')
    assert args.tag != 'baseline' or not path.exists(), 'First baseline is immutable'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)
    print(json.dumps(dict(controls=len(result), passed=sum(row['passed'] for row in result),
                          failed_cases=[row['case'] for row in result if not row['passed']],
                          live_actions=0)))
    if args.tag == 'final':
        assert all(row['passed'] for row in result), 'Frozen critical calculations still fail'


if __name__ == '__main__':
    main()
