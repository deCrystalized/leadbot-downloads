"""Read usage-only receipts locally; no key, provider, tokenizer or runtime changes.

The no-write comparison holds every token count and output fixed. It is an
accounting counterfactual, not a measured result of a different API request.
"""
import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from api_costs import RATES, PRICE_DATE, cost


def _empty():
    return dict(calls=0, unknown_calls=0, input_tokens=0, output_tokens=0,
        reasoning_tokens_known=0, reasoning_count_unknown_calls=0,
        cached_tokens=0, cache_write_tokens=0, known_usd=Decimal(0),
        input_usd=Decimal(0), output_usd=Decimal(0),
        no_write_same_usage_usd=Decimal(0))


def analyze(records):
    if not isinstance(records, list):
        raise ValueError('Expected usage receipt list')
    seen, groups = {}, {}
    for row in records:
        if (not isinstance(row, dict) or not isinstance(row.get('response_id'), str)
                or not row['response_id'] or row.get('role') not in ('research', 'review')
                or not isinstance(row.get('series'), str) or not row['series']):
            raise ValueError('Exact response, series and model role required')
        core = {k: row.get(k) for k in ('response_id', 'series', 'role', 'model', 'usage', 'usd', 'tier')}
        encoded = json.dumps(core, sort_keys=True, allow_nan=False)
        if row['response_id'] in seen:
            if seen[row['response_id']] != encoded:
                raise ValueError('Conflicting duplicate response identity')
            continue
        seen[row['response_id']] = encoded
        # Unknown returned tiers must never be priced as ordinary Standard.
        if row.get('tier') not in ('default', 'standard'):
            expected = None
        else:
            expected = cost(row.get('model'), row.get('usage'))
        group = groups.setdefault((row['series'], row['role']), _empty())
        group['calls'] += 1
        if expected is None:
            group['unknown_calls'] += 1
            continue
        if row.get('usd') is None or Decimal(row['usd']) != expected:
            raise ValueError('Receipt amount does not match verified usage and tariff')
        usage = row['usage']
        inputs, outputs = usage['input_tokens'], usage['output_tokens']
        details = usage['input_tokens_details']
        cached, written = details['cached_tokens'], details['cache_write_tokens']
        incoming, cache_read, _, outgoing = map(Decimal, RATES[row['model']])
        scale_in = Decimal(2) if inputs > 272000 else Decimal(1)
        scale_out = Decimal('1.5') if inputs > 272000 else Decimal(1)
        output_usd = Decimal(outputs) * outgoing * scale_out / 1000000
        group['known_usd'] += expected
        group['input_usd'] += expected - output_usd
        group['output_usd'] += output_usd
        group['input_tokens'] += inputs
        group['output_tokens'] += outputs
        group['cached_tokens'] += cached
        group['cache_write_tokens'] += written
        reasoning = (usage.get('output_tokens_details') or {}).get('reasoning_tokens')
        if reasoning is None:
            group['reasoning_count_unknown_calls'] += 1
        else:
            group['reasoning_tokens_known'] += reasoning
        group['no_write_same_usage_usd'] += (
            (Decimal(inputs-cached)*incoming + Decimal(cached)*cache_read)*scale_in/1000000
            + output_usd)
    rows = []
    for (series, role), values in sorted(groups.items()):
        values['input_fraction_of_known_cost'] = (
            values['input_usd']/values['known_usd'] if values['known_usd'] else None)
        values['complete'] = values['unknown_calls'] == 0
        rows.append(dict(series=series, role=role, **values))
    known = sum((r['known_usd'] for r in rows), Decimal(0))
    unknown = sum(r['unknown_calls'] for r in rows)
    return dict(schema=1, price_snapshot=PRICE_DATE, calls=len(seen),
        unknown_calls=unknown, complete=unknown == 0, known_usd=known, groups=rows,
        reasoning_already_in_output=True, invoice=False, paid_calls_made=0,
        counterfactual='No-write amount assumes identical usage/output, unchanged cache reads and no future reuse benefit. Not observed savings.',
        source_body_or_key_read=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipts', type=Path, help='Usage-only JSON containing per_call; never a credential or full model request')
    args = parser.parse_args()
    raw = args.receipts.read_bytes()
    value = json.loads(raw)
    result = analyze(value['per_call'])
    result['usage_document_sha256'] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
