"""Replay the frozen real sample through the production reviewed-question mode locally."""
import collections
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from manual_program_guard import assert_development_groups, assert_development_phones

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'leadbot/brain'))
from extension_assistant import Assistant
from assistant_store import Store
import contact_phone

os.environ['LEADBOT_ASSISTANT_WORDING']='reviewed'
source=json.loads((ROOT/'test-artifacts/personal/real-cases-private.json').read_text())['cases']
assert_development_groups(row['client_group'] for row in source)
assert_development_phones(phone.value for row in source for message in row['ctx']['messages'] if message.get('direction') == 'in' for phone in contact_phone.find_all(message.get('body') or message.get('text') or ''))
expectations=json.loads((ROOT/'tests/real_policy_expectations.json').read_text())
parser=argparse.ArgumentParser()
parser.add_argument('--adjudications',help='Separate primary-source rechecks; preserve original targets')
args=parser.parse_args()
resolutions={}
if args.adjudications:
    p=(ROOT/'test-artifacts/personal'/args.adjudications).resolve()
    assert p.parent==(ROOT/'test-artifacts/personal').resolve() and p.suffix=='.json'
    adjudicated=json.loads(p.read_text())
    assert adjudicated['original_expectations_sha256']==hashlib.sha256((ROOT/'tests/real_policy_expectations.json').read_bytes()).hexdigest()
    for r in adjudicated['resolutions']:
        assert r['reviewed'] is True and r['primary_rule_ids'] and r['reason']
        assert r['case_id'] in {x['case_id'] for x in source}
        assert set(r['resolved_expectation']).issubset({'expected_action','expected_question'})
        resolutions[r['case_id']]=r['resolved_expectation']
# The frozen label snapshot has its own version. A new runtime must be replayed
# against the same labels, not require relabelling merely to match its version.
assert re.fullmatch(r'\d{4}-\d{2}-\d{2}\.\d+', expectations['version'])
results=[];semantic_mismatches=[]
with tempfile.TemporaryDirectory() as temp:
    app=Assistant(Store(str(Path(temp)/'db')))
    for row in source:
        out,code=app.handle({'owner':'evaluation','action':'preview','ctx':row['ctx']})
        assert code==200 and out['auto_enabled'] is False and not out.get('pending_model') and not out.get('model_task')
        assert not out.get('validation'),(row['review_number'],out.get('validation'))
        override=dict(expectations['overrides'].get(row['case_id'],{}),**resolutions.get(row['case_id'],{}))
        expected_action=override.get('expected_action',row['expected_action'])
        expected = 'question' if expected_action == 'draft' else expected_action
        if out['action'] != expected:
            semantic_mismatches.append({'number':row['review_number'],'kind':'action','expected':expected,'actual':out['action']})
        question = override.get('expected_question',row.get('expected_question')) or {}
        if expected == 'question' and question:
            normalized = re.sub(r'\s+', ' ', out.get('reply','').lower().replace('ё','е'))
            if any(not any(word.lower().replace('ё','е') in normalized for word in group) for group in question.get('groups',[])):
                semantic_mismatches.append({'number':row['review_number'],'kind':'question_meaning','expected':question.get('kind')})
        results.append({'number':row['review_number'],'case_id':row['case_id'],'category':row['category'],
                        'reply':out.get('reply',''),'action':out['action'],'needs_operator':out['needs_operator'],
                        'reason':out['reason'],'response_source':out.get('response_source','rules'),
                        'validation':out.get('validation',[]),'policy_version':out['policy_version']})
report={'completed':True,'cases':results,'model_calls':0,'auto_enabled':False,
        'policy_version':results[0]['policy_version'],'sources':dict(collections.Counter(r['response_source'] for r in results)),
        'baseline_action_and_question_mismatches':semantic_mismatches,'reviewed_baseline_corrections':len(expectations['overrides'])}
report['separate_primary_adjudications']=len(resolutions)
report['expectations_version']=expectations['version']
report['expectations_sha256']=hashlib.sha256((ROOT/'tests/real_policy_expectations.json').read_bytes()).hexdigest()
path=ROOT/'test-artifacts/personal/real-reviewed-final-private.json'
path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');os.chmod(path,0o600)
print(json.dumps({'cases':len(results),'sources':report['sources'],'auto_enabled':False,'baseline_action_and_question_mismatches':semantic_mismatches}))
assert not semantic_mismatches
