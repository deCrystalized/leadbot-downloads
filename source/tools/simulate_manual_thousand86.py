"""Causal replay of the development1000; no network, delivery or CRM writes.

Actual earlier operator replies remain historical evidence. New drafts are not
pretended to have been sent or answered by that historical customer. This is
not a counterfactual customer simulation or independent accuracy assessment.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'leadbot/brain'))
sys.path.insert(0, str(ROOT / 'tools'))
from assistant_store import Store
from extension_assistant import Assistant, _parse
from contact_cities import city_by_slug
import assistant_policy as policy
import assistant_prices
import contact_phone
import leadchat
import personal_workflow
import qualification_state
from manual_program_guard import assert_development_dialogues, assert_development_phones


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instant(value):
    if not value:
        return None
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def context(row, cut, common=False):
    source = row['source']
    history = row['messages'][:cut]
    assert 0 < cut <= len(row['messages'])
    title = source.get('account_title') or ''
    direction = next((d for label, d in [('МНЧ', 'mnc'), ('КП', 'kp'), ('БТ', 'bt')] if label in title), '')
    city = city_by_slug(source.get('city'))
    linked = bool(source.get('crm_at') and instant(source['crm_at']) <= instant(history[-1]['ts']))
    rows = []
    for m in history:
        if common and m['direction'] not in ('in', 'out'):
            continue
        media = m.get('attachments') or [dict(kind=t) for t in m.get('attachment_types') or []]
        rows.append(dict(id=m['id'], direction=m['direction'], sender_type=m.get('sender_type'),
                         body=m.get('text') or m.get('transcript') or '', created_at=m['ts'],
                         attachments=media, delivery_status=m.get('delivery') or ''))
    return dict(convId='emulation86-' + str(row['number']), city=city.name if city else source.get('city'),
                dir=direction, partner=source.get('partner'), channel=source.get('channel'),
                accountTitle=title, origin=source.get('origin'), itemTitle=source.get('item_title'),
                crmRequestId=str(source['crm_request_id']) if linked else '', messages=rows,
                accountId=source.get('account') or '', assigneeId='offline-operator',
                assignmentKnown=True, channelAssigned=True, conversationStatus='in_progress',
                botActive=False, hasTransfer=False)


def legacy_input(ctx):
    return dict(chat=ctx['convId'], city=ctx['city'], direction=ctx['dir'], partner=ctx['partner'],
                channel=ctx['channel'], account_title=ctx['accountTitle'], origin=ctx['origin'],
                item_title=ctx['itemTitle'], crm_request_id=ctx['crmRequestId'], wording_mode='reviewed',
                dialog=[dict(id=m['id'], role='user' if m['direction'] == 'in' else 'assistant',
                             content=m['body'], by='bot' if m['sender_type'] == 'bot' else 'operator',
                             attachments=m['attachments'], created_at=m['created_at'],
                             delivery_status=m['delivery_status']) for m in ctx['messages']])


def check_expectation(out, expected):
    errors = []
    if out.get('action') != expected.get('expected_action'):
        errors.append(dict(kind='action', actual=out.get('action'), expected=expected.get('expected_action')))
    for field, key, forbidden in [('reply', 'required_reply_patterns', False),
                                  ('reply', 'forbidden_reply_patterns', True),
                                  ('reason', 'required_reason_patterns', False)]:
        for pattern in expected.get(key, []):
            if bool(re.search(pattern, out.get(field) or '', re.I)) == forbidden:
                errors.append(dict(kind=key, pattern=pattern))
    return errors


def deny_network(*_a, **_k):
    raise AssertionError('Offline replay attempted a network connection')


def initialize():
    os.environ['LEADBOT_PERSONAL_OWNER_ID'] = 'offline-emulation86'
    os.environ['LEADBOT_ASSISTANT_WORDING'] = 'reviewed'
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network


def simulate(row, expected):
    actions, steps, signals = Counter(), Counter(), Counter()
    records, labelled, latencies = [], [], []
    with tempfile.TemporaryDirectory(prefix='leadbot-emulation86-') as temp:
        store = Store(str(Path(temp) / 'offline.sqlite'))
        app = Assistant(store)
        for i, m in enumerate(row['messages']):
            if m['direction'] != 'in' or not (m.get('text') or m.get('transcript') or m.get('attachments') or m.get('attachment_types')):
                continue
            ctx = context(row, i + 1)
            started = time.perf_counter()
            out, status = app.handle(dict(owner='offline-emulation86', action='preview', ctx=ctx))
            latencies.append((time.perf_counter() - started) * 1000)
            assert status == 200 and out.get('auto_enabled') is False, (row['number'], i, out)
            assert not out.get('pending_model') and not out.get('model_task')
            _, messages, known, revision = _parse(ctx)
            plan = personal_workflow.plan(messages, known, ctx, dict(operator_id='offline-operator',
                max_dialogs=0, mode_epoch=0, execution_mode='review'), 0, revision)
            assert plan['execution_allowed'] is False and plan['auto_enabled'] is False
            reply, flags = out.get('reply') or '', []
            prior = [m for m in assistant_prices.current_enquiry_messages(messages) if m['direction'] == 'out'
                     and m.get('delivery_status') not in ('failed', 'error', 'cancelled', 'canceled', 'pending', 'sending', 'queued')]
            if reply and not prior and not policy.GREETING_START.match(reply): flags.append('missing_greeting')
            if reply and prior and policy.GREETING_START.match(reply): flags.append('repeated_greeting')
            if reply and out.get('facts', {}).get('contact_phone_to_use') and policy.requests_contact(reply): flags.append('repeated_phone')
            if len(reply) > 280: flags.append('long_reply')
            if out.get('validation'): flags.append('validation_failed')
            qs = qualification_state.inspect(messages)
            if reply and re.search(r'(?:марк.{0,15}модел|модел.{0,15}марк)', reply, re.I) and qs['model']['status'] == 'answered':
                flags.append('possible_repeated_model')
            if known.get('channel', '').startswith('max') and plan['eligible']: flags.append('MAX_eligible')
            actions[out.get('action') or out.get('code')] += 1
            steps[plan['step']] += 1
            signals.update(flags)
            records.append(dict(cut=i+1, message_id=m['id'], action=out.get('action'), reply=reply,
                                reason=out.get('reason'), rule_ids=out.get('rule_ids'),
                                step=plan['step'], flags=flags, draft_id=out.get('draft_id'),
                                source=out.get('response_source'), reply_sent=False))
        for target in expected:
            if not target.get('cut') or not target.get('expected_action'):
                continue
            ctx = context(row, target['cut'])
            out, status = app.handle(dict(owner='offline-emulation86', action='preview', ctx=ctx))
            assert status == 200 and out.get('auto_enabled') is False
            labelled.append(dict(cut=target['cut'], actual=out.get('action'), expected=target['expected_action'],
                                 reply=out.get('reply'), reason=out.get('reason'),
                                 errors=check_expectation(out, target), media_seen=any(m['attachments'] for m in ctx['messages'])))
        assert records, row['number']
        # Compare exactly the fields both old and new protocols can carry;
        # service notes and extra extension receipts are not silently claimed equal.
        common = context(row, records[-1]['cut'], common=True)
        # Native has no assignment/card identity fields: use the common
        # source contract on the extension side, not the native adapter's
        # own output (that would make the comparison circular).
        extension_common = {k: common[k] for k in ('convId', 'city', 'dir', 'partner', 'channel',
            'accountTitle', 'origin', 'itemTitle', 'crmRequestId', 'messages')}
        direct, _ = app.handle(dict(owner='offline-emulation86', action='preview', ctx=extension_common))
        native = leadchat.reviewed_answer(legacy_input(common), store,
            generate=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('Model forbidden offline')))
        assert native['reply'] == '' and native['meta']['auto_enabled'] is False
        parity = {key: direct.get(key) == native['meta']['draft'].get(key)
                  for key in ['reply', 'action', 'reason', 'facts', 'rule_ids', 'policy_version']}
    return dict(number=row['number'], cid=row['cid'], turns=records, labelled=labelled,
                actions=dict(actions), steps=dict(steps), signals=dict(signals), parity=parity,
                latency_ms=latencies, source_messages=len(row['messages']),
                original_messages_unchanged=True, crm_write=False, customer_send=False)


def load_programme():
    folder = ROOT / 'test-artifacts/human-practice/manual-program-1000'
    audit = json.loads((folder / 'full-text-reading-1000-audit-20261019.json').read_text())
    roster = json.loads((folder / 'development-private.json').read_text())
    ids = {row['cid'] for row in roster}
    for batch in ('manual-batch20', 'manual-batch21-40', 'manual-batch41-60'):
        ids.update(row['cid'] for row in json.loads((folder.parent / batch / 'manual-review-private.json').read_text()))
    assert len(ids) == 1000
    assert_development_dialogues(ids)  # before loading a single source body
    rows, labels, sources = [], {}, []
    for entry in audit['source_artifacts']:
        batch = folder.parent / entry['batch']
        source = batch / 'sources-private.json'
        assert sha(source) == entry['source_sha256'], 'Audited source changed: ' + str(source)
        data = json.loads(source.read_text())
        assert all(r['cid'] in ids for r in data)
        rows += data
        sources.append(dict(path=str(source.relative_to(ROOT)), sha256=sha(source)))
        ledger = batch / 'manual-review-private.json'
        if ledger.exists():
            sources.append(dict(path=str(ledger.relative_to(ROOT)), sha256=sha(ledger)))
            for target in json.loads(ledger.read_text()):
                labels[target['case']] = [target, *target.get('additional_prefixes', [])]
    assert len(rows) == len({r['cid'] for r in rows}) == 1000
    assert {r['number'] for r in rows} == set(range(1, 1001))
    assert {r['cid'] for r in rows} == ids
    assert_development_phones(phone.value for r in rows for m in r['messages'] if m['direction'] == 'in'
                              for phone in contact_phone.find_all(m.get('text') or m.get('transcript') or ''))
    return sorted(rows, key=lambda row: row['number']), labels, sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    target = (ROOT / args.output).resolve()
    assert target.is_relative_to(ROOT / 'test-artifacts') and not target.exists()
    target.mkdir(parents=True, mode=0o700)
    rows, labels, sources = load_programme()
    runtime = sorted((ROOT / 'leadbot/brain').glob('*.py')) + sorted((ROOT / 'leadbot/brain').glob('*.json'))
    (target / 'inputs.json').write_text(json.dumps(dict(policy=policy.VERSION, sources=sources,
        tool_sha256=sha(Path(__file__)), runtime_sources=[dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in runtime],
        fulltexts=1000, holdout_opened=False, current_crm_cards_used=False), indent=2)+'\n')
    results, errors = [], []
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        tasks = {pool.submit(simulate, r, labels.get(r['number'], [])): r['number'] for r in rows}
        for task in as_completed(tasks):
            try: results.append(task.result())
            except Exception as error: errors.append(dict(case=tasks[task], error=repr(error)))
            if (len(results)+len(errors)) % 40 == 0:
                print(json.dumps(dict(dialogues=len(results), runtime_errors=len(errors),
                    seconds=round(time.perf_counter()-started, 1))), flush=True)
    results.sort(key=lambda r:r['number'])
    private = target / 'trace-private.jsonl'
    with private.open('w') as stream:
        for result in results: stream.write(json.dumps(result, ensure_ascii=False)+'\n')
    private.chmod(0o600)
    actions, steps, signals = Counter(), Counter(), Counter()
    for result in results:
        actions.update(result['actions']); steps.update(result['steps']); signals.update(result['signals'])
    labelled = [dict(case=r['number'], **t) for r in results for t in r['labelled']]
    mismatches = [r for r in labelled if r['errors']]
    failures = target / 'label-differences-private.json'
    failures.write_text(json.dumps(mismatches,ensure_ascii=False,indent=2)+'\n');failures.chmod(0o600)
    latency = sorted(t for r in results for t in r['latency_ms'])
    report = dict(policy=policy.VERSION, dialogues=len(results), source_messages=sum(r['source_messages'] for r in results),
        causal_client_turns=sum(len(r['turns']) for r in results), actions=dict(actions), steps=dict(steps),
        diagnostic_signals=dict(signals), labelled_prefixes=len(labelled), original_label_differences=len(mismatches),
        native_common_contract_matches=sum(all(r['parity'].values()) for r in results),
        runtime_errors=errors, latency_ms=dict(median=round(statistics.median(latency),2),p95=round(latency[int(len(latency)*.95)],2)),
        duration_seconds=round(time.perf_counter()-started,1), network_calls=0, model_calls=0,
        real_orders_created=0, customer_sends=0, auto_enabled=False, final_holdout_opened=False,
        manual_cycles_added=0, scope='Causal historical replay and read-only workflow planning; not counterfactual customer behavior or autonomous conversion accuracy. Raw unreviewed media remain operator work. Original labels and rules are never overwritten.')
    (target/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if errors or len(results)!=1000 or report['native_common_contract_matches']!=1000:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
