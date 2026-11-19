"""Register explicitly reviewed browser evidence locally; no network or CRM writes."""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from manual_program_guard import assert_development_dialogues, assert_development_phones

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    parser.add_argument('--annotation', required=True)
    args = parser.parse_args()
    assert re.fullmatch(r'\d+-\d+', args.batch)
    folder = ROOT / ('test-artifacts/human-practice/manual-batch' + args.batch)
    annotation = (folder / args.annotation).resolve()
    assert annotation.parent == folder.resolve() and annotation.suffix == '.json'
    read = lambda p: json.loads(p.read_text())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    review = read(annotation)
    assert review['manually_read_full_source_and_actual_ax'] is True
    assert review['read_only'] is True and review['browser_id'] == '2'
    plan = read(folder / 'crm-phone-plan-private.json')
    item = next(r for r in plan if r['case'] == review['case'])
    assert not item['completed']
    assert_development_dialogues([item['cid']])
    assert_development_phones(item['phones'])
    search = folder / review['search_ax']
    assert search.parent == folder and search.is_file()
    search_text = search.read_text()
    assert 'Мамонтов Георгий' in search_text and 'Заявки клиентов' in search_text
    cards_path = folder / 'crm-verification-private.json'
    lookup_path = folder / 'crm-phone-lookups-private.json'
    cards = read(cards_path) if cards_path.exists() else []
    lookups = read(lookup_path) if lookup_path.exists() else []
    assert not any(r['case'] == item['case'] for r in lookups)
    # Read only prior local review identifiers. A related card seen before
    # can complete this phone lookup without inflating the global card count.
    prior_ids = set()
    def previous_identifiers(row):
        value = row.get('request_id', row.get('crm_id', row.get('id')))
        if value is not None:
            assert re.fullmatch(r'\d+', str(value)), 'Unknown prior card identifier'
            prior_ids.add(str(value))
        elif 'cards' in row:
            for card in row['cards']:
                previous_identifiers(card)
        else:
            raise AssertionError('Unknown prior CRM review schema')
    for path in folder.parent.glob('manual-batch*/crm-verification-private.json'):
        for row in read(path):
            previous_identifiers(row)
    now = datetime.now(timezone.utc).isoformat()
    new = review['cards']
    added = []
    rechecked = []
    ids = [str(r['request_id']) for r in new]
    assert len(ids) == len(set(ids))
    for card in new:
        path = folder / card['ax_evidence']
        assert path.parent == folder and path.is_file()
        assert '№' + str(card['request_id']) in path.read_text()
        contacts = {card['phone'], *card.get('additional_phones', [])}
        assert contacts.intersection(item['phones'])
        assert_development_phones(contacts)
        assert card['findings'] and card['source_creation_link']
        previous = next((r for r in cards
                         if str(r.get('request_id', r.get('crm_id', r.get('id')))) == str(card['request_id'])), None)
        if previous is not None:
            assert previous['case'] == item['case'], 'Previously reviewed card belongs to another case'
            assert str(card['request_id']) in item['previously_read_card_ids']
            # Keep the original review intact. The new annotation and lookup
            # retain the fresh evidence without granting a second card credit.
            rechecked.append(dict(request_id=str(card['request_id']), ax_evidence=path.name,
                                  ax_sha256=sha(path), findings=card['findings'],
                                  source_creation_link=card['source_creation_link']))
            continue
        card.update(case=item['case'], cid=item['cid'], read_at_utc=now,
                    read_via='CUA IAB browser2 fullAX; all multiline comments manually read; read-only',
                    account_binding_evidence=search.name, full_card_read=True,
                    full_multiline_comment_read=True, current_card_not_creation_snapshot=True,
                    current_crm_used_as_historical_input=False, ax_sha256=sha(path),
                    global_unique_credit=str(card['request_id']) not in prior_ids,
                    crm_writes=0, customer_sends=0, gold_admitted=False,
                    global_duplicate_absence_proven=False, bank_payment_proof=False)
        cards.append(card)
        added.append(card)
    assert new or review.get('visible_no_records') is True and 'Ничего не найдено' in search_text
    lookups.append(dict(case=item['case'], at=now, search_domain=item['dir'],
                        search_ax=search.name, search_ax_sha256=sha(search),
                        search_format='full+7number', no_date_status_author_filter=True,
                        actual_cards_read=ids, identity_confirmed=review['identity_confirmed'],
                        previously_reviewed_cards_rechecked=rechecked,
                        annotation=annotation.name, annotation_sha256=sha(annotation),
                        lookup_completed=True, claim_absence_of_other_orders=False, writes=0))
    item.update(completed=True, actual_cards_read=ids)
    done = sum(bool(r['completed']) for r in plan)
    paths = [ROOT / 'test-artifacts/current-pilot/active-goal-checkpoint.json',
             ROOT / 'test-artifacts/current-pilot/live-chain-state.json',
             ROOT.parents[1] / 'outputs/LeadBot-manual-program-progress-2026-10-17.json']
    progress = [read(p) for p in paths]
    assert len({p['actual_crm_cards_read'] for p in progress}) == 1
    total = progress[0]['actual_crm_cards_read'] + sum(r['global_unique_credit'] for r in added)
    updates = {cards_path: cards, lookup_path: lookups, folder / 'crm-phone-plan-private.json': plan}
    for path, state in zip(paths, progress):
        state.update(updated_at=now, actual_crm_cards_read=total, crm_browser_available=True)
        state['batch' + args.batch.split('-')[0] + '_crm_progress'] = dict(
            actual_cards_read=len(cards), phone_contexts_completed=done,
            phone_contexts_total=len(plan), fully_completed=False)
        updates[path] = state
    for path, value in updates.items():
        temporary = path.with_suffix(path.suffix + '.review-tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temporary.chmod(0o600)
        os.replace(temporary, path)
    print(json.dumps(dict(registered_case=item['case'], actual_cards=ids,
                          cumulative_actual_crm=total, batch_cards=len(cards),
                          phone_contexts_done=done, phone_contexts_total=len(plan), crm_writes=0)))


if __name__ == '__main__':
    main()
