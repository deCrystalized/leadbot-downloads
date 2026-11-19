"""One finite read-only native archive slice. Reinvoke to resume the same scan."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot'/'brain'))
from native_exporter import NativeExporter
from research_server import source_components
from research_sources import private_file,strict_json,SourceConfigurationError


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--max-cases',type=int,default=100)
    parser.add_argument('--max-seconds',type=float,default=60)
    args=parser.parse_args(argv)
    raw=private_file(args.config,limit=32000);value=strict_json(raw)
    expected=hashlib.sha256(raw).hexdigest()
    def control():
        if hashlib.sha256(private_file(args.config,limit=32000)).hexdigest()!=expected:
            raise SourceConfigurationError('Source controller changed; admission revoked')
    client,index=source_components(value,control=control)
    worker=NativeExporter(client,index,Path(value['directory'])/'native-export',shared_lock=Path(value['shared_lock']),
                          preflight=client.protection_preflight)
    result=worker.run(max_cases=args.max_cases,max_seconds=args.max_seconds)
    # No customer text/phones/URLs, model calls, credentials or action authority.
    public={key:result.get(key) for key in ('processed','indexed','pending_original_or_source',
        'phase','last_completed','busy','not_due','waiting_for_model_lock','error','full_pool_verified')}
    public.update(provider_calls=0,customer_actions=0)
    print(json.dumps(public,sort_keys=True))


if __name__=='__main__':main()
