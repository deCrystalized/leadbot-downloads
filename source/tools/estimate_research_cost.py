"""Print hypothetical Sol/Astra costs; never call a provider or change runtime."""
import argparse
import json
from pathlib import Path
import sys
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
from api_costs import scenario, cost


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replies', type=int, default=10)
    parser.add_argument('--extra-search-calls', type=int, default=0)
    parser.add_argument('--cache', choices=('none','hit','write'), default='none')
    parser.add_argument('--profile', choices=('sol_only','sol_astra'), default='sol_only')
    parser.add_argument('--conversion', type=Decimal, help='Hypothetical created orders/dialogue, e.g.0.3; not a measured rate')
    parser.add_argument('--rub-per-usd', type=Decimal, help='Your assumed effective rate; not a fetched FX quote')
    args = parser.parse_args()
    result = scenario(replies=args.replies, extra_search_calls=args.extra_search_calls,cache_mode=args.cache)
    reviewer = 'gpt-6.1-sol' if args.profile == 'sol_only' else 'gpt-6-astra'
    per_reply = cost('gpt-6.1-sol',result['inputs']['sol'])*(1+args.extra_search_calls)+cost(reviewer,result['inputs']['astra'])
    per_dialogue = per_reply*args.replies
    result.update(profile=args.profile,reviewer_model=reviewer,reply_usd=str(per_reply),dialogue_usd=str(per_dialogue))
    if args.conversion is not None:
        if not 0 < args.conversion <= 1:parser.error('conversion must be greater than0 and at most1')
        result.update(assumed_conversion=str(args.conversion),per_created_order_usd=str(per_dialogue/args.conversion))
    if args.rub_per_usd is not None:
        if args.rub_per_usd <= 0:parser.error('assumed FX rate must be positive')
        result.update(assumed_rub_per_usd=str(args.rub_per_usd),dialogue_rub=str(per_dialogue*args.rub_per_usd))
        if args.conversion is not None:result['per_created_order_rub']=str(per_dialogue*args.rub_per_usd/args.conversion)
    print(json.dumps(result, ensure_ascii=False, indent=2))
