"""Exact USD estimates from a dated price snapshot, never invented API usage.

Usage receipts are supplied by a trusted transport. This module does not call
a provider, authorize a purchase, change a model or count visible words as tokens.
"""
from decimal import Decimal
import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path

PRICE_DATE = '2026-10-26'
PRICE_SOURCE = 'https://developers.openai.com/api/docs/models/'
RATES = {
    'gpt-6.1-sol': ('2', '0.10', '2.50', '10'),
    'gpt-6-astra': ('10', '1', '12.50', '50'),
}
_UNSET = object()


def _count(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('Token counts must be nonnegative integers')
    return value


def cost(model, usage, *, tier='standard', cache_ttl='30m'):
    if model not in RATES or tier != 'standard' or cache_ttl not in ('30m', '12h'):
        raise ValueError('No confirmed rate for this model/tier')
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise ValueError('Expected a usage receipt')
    details = usage.get('input_tokens_details')
    if (not all(k in usage for k in ('input_tokens', 'output_tokens'))
            or not isinstance(details, dict)
            or not all(k in details for k in ('cached_tokens', 'cache_write_tokens'))):
        return None  # Absence of usage is not a zero-dollar request.
    total, output = _count(usage['input_tokens']), _count(usage['output_tokens'])
    cached, written = _count(details['cached_tokens']), _count(details['cache_write_tokens'])
    if cached + written > total:
        raise ValueError('Cache categories overlap or exceed total input')
    reasoning = (usage.get('output_tokens_details') or {}).get('reasoning_tokens')
    if reasoning is not None and _count(reasoning) > output:
        raise ValueError('Reasoning tokens exceed total output')
    uncached = total - cached - written
    incoming, cache_read, cache_write, outgoing = map(Decimal, RATES[model])
    lifetimes = details.get('cache_write_tokens_details')
    if lifetimes is not None:
        if not isinstance(lifetimes,dict) or not all(k in lifetimes for k in ('ttl_30m_tokens','ttl_12h_tokens')):
            return None
        short, long = _count(lifetimes['ttl_30m_tokens']), _count(lifetimes['ttl_12h_tokens'])
        if short+long != written:
            raise ValueError('Cache write lifetime counts do not partition writes')
    else:
        short, long = (written,0) if cache_ttl=='30m' else (0,written)
    long_input = Decimal(2) if total > 272000 else Decimal(1)
    long_output = Decimal('1.5') if total > 272000 else Decimal(1)
    # Output tokens already include reasoning; adding it again overcharges.
    return ((uncached * incoming + cached * cache_read + (short+2*long) * cache_write) * long_input
            + output * outgoing * long_output) / Decimal(1000000)


class UsageLedger:
    def __init__(self, path=None):
        self.receipts = {}
        self.path = Path(path) if path is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                db.execute('CREATE TABLE IF NOT EXISTS api_usage_receipts (response_id TEXT PRIMARY KEY, receipt TEXT NOT NULL)')
            self.path.chmod(0o600)

    def add(self, response_id, model, usage, *, status='completed', cache_ttl='30m', scope=None, service_tier=_UNSET,
            funding='api'):
        if funding not in ('api', 'chatgpt_plan'):
            raise ValueError('Unknown funding mode; no API fallback')
        if not isinstance(response_id, str) or not response_id.strip() or len(response_id) > 200:
            raise ValueError('A stable transport response/attempt identity is required')
        if status not in ('completed', 'incomplete', 'failed', 'refused'):
            raise ValueError('Unknown receipt status')
        if service_tier is not _UNSET and service_tier is not None and not isinstance(service_tier,str):
            raise ValueError('Service tier must come from a provider receipt')
        # Old explicitly hypothetical calculations keep their dated Standard
        # premise. A real receipt with missing/other tier never inherits it.
        amount = cost(model, usage, cache_ttl=cache_ttl) if service_tier is _UNSET or service_tier=='default' else None
        if funding == 'chatgpt_plan':
            amount = None  # Plan allocation/limits are not a measured Standard API bill or zero cost.
        if scope is not None and (not isinstance(scope,dict) or set(scope) != {'owner','dialogue','role'}
                or any(not isinstance(v,str) or not v or len(v)>200 for v in scope.values())):
            raise ValueError('Invalid dialogue billing scope')
        value = dict(model=model, usage=copy.deepcopy(usage), status=status, cache_ttl=cache_ttl,
                     scope=copy.deepcopy(scope), price_date=PRICE_DATE,
                     known_usd=str(amount) if amount is not None else None)
        if service_tier is not _UNSET:
            value['service_tier'] = service_tier
        if funding != 'api':
            value['funding'] = funding  # Keep old API receipts byte-compatible for durable recovery.
        if self.path is not None:
            with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT receipt FROM api_usage_receipts WHERE response_id=?',(response_id,)).fetchone()
                if row and json.loads(row[0]) != value:
                    raise ValueError('Response identity collision')
                db.execute('INSERT OR IGNORE INTO api_usage_receipts VALUES(?,?)',
                           (response_id,json.dumps(value,ensure_ascii=False,sort_keys=True)))
            return
        if response_id in self.receipts and self.receipts[response_id] != value:
            raise ValueError('Response identity collision')
        self.receipts[response_id] = value

    def summary(self, *, owner=None, dialogue=None):
        if dialogue is not None and not owner:
            raise ValueError('Private dialogue summary requires an owner')
        if self.path is not None:
            with closing(sqlite3.connect(self.path, timeout=5)) as db:
                receipts = [json.loads(r[0]) for r in db.execute('SELECT receipt FROM api_usage_receipts')]
        else:
            receipts = list(self.receipts.values())
        if owner is not None:
            receipts = [r for r in receipts if r.get('scope') and r['scope']['owner']==owner
                        and (dialogue is None or r['scope']['dialogue']==dialogue)]
        unknown = sum(r['known_usd'] is None for r in receipts)
        known = sum((Decimal(r['known_usd']) for r in receipts
                     if r['known_usd'] is not None), Decimal(0))
        groups, roles = {}, {}
        for r in receipts:
            scope = r['scope']
            if scope is None:
                continue
            key = (scope['owner'],scope['dialogue'])
            group = groups.setdefault(key,dict(owner=key[0],dialogue=key[1],calls=0,unknown_calls=0,known_usd=Decimal(0)))
            group['calls'] += 1
            if r['known_usd'] is None:group['unknown_calls'] += 1
            else:group['known_usd'] += Decimal(r['known_usd'])
            role=roles.setdefault(scope['role'],dict(role=scope['role'],calls=0,unknown_calls=0,known_usd=Decimal(0)))
            role['calls']+=1
            if r['known_usd'] is None:role['unknown_calls']+=1
            else:role['known_usd']+=Decimal(r['known_usd'])
        by_dialogue = [dict(g,known_usd=str(g['known_usd'])) for _,g in sorted(groups.items())]
        by_role = [dict(g,known_usd=str(g['known_usd'])) for _,g in sorted(roles.items())]
        verified=sum(r.get('service_tier')=='default' for r in receipts)
        standard=all('service_tier'not in r or r['service_tier']=='default' for r in receipts)
        subscription_calls = sum(r.get('funding') == 'chatgpt_plan' for r in receipts)
        api_unknown = sum(r.get('funding', 'api') == 'api' and r['known_usd'] is None for r in receipts)
        return dict(calls=len(receipts), known_usd=str(known), unknown_calls=unknown, by_dialogue=by_dialogue,
                    by_role=by_role,verified_tier_calls=verified,
                    by_funding=dict(api=len(receipts)-subscription_calls,chatgpt_plan=subscription_calls),
                    api_cost_complete=not api_unknown,subscription_cost_allocated=False,
                    complete=not unknown, price_date=PRICE_DATE,
                    tier='mixed_or_subscription' if subscription_calls else ('standard' if standard else 'unconfirmed'),
                    excludes='Infrastructure, tools, taxes, currency conversion; not an invoice')


def scenario(*, replies, extra_search_calls=0, cache_mode='none'):
    """An explicit hypothetical workload, not a measured production mean."""
    if not 1 <= _count(replies) <= 1000 or not 0 <= _count(extra_search_calls) <= 20:
        raise ValueError('Scenario outside supported range')
    if cache_mode not in ('none', 'hit', 'write'):
        raise ValueError('Unknown cache scenario')
    details = dict(cached_tokens=8000 if cache_mode == 'hit' else 0,
                   cache_write_tokens=8000 if cache_mode == 'write' else 0)
    planner = dict(input_tokens=10000, output_tokens=2000, input_tokens_details=details)
    reviewer = dict(input_tokens=12000, output_tokens=1000, input_tokens_details=details)
    sol = cost('gpt-6.1-sol', planner)
    astra = cost('gpt-6-astra', reviewer)
    each = sol * (1 + extra_search_calls) + astra
    return dict(reply_usd=str(each), dialogue_usd=str(each * replies), measured=False,
                replies=replies, sol_calls_per_reply=1 + extra_search_calls,
                astra_calls_per_reply=1, output_includes_reasoning=True,
                cache_mode=cache_mode, inputs=dict(sol=planner, astra=reviewer),
                tier='standard', price_date=PRICE_DATE)
