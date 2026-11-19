"""Installed-source unit checks and authenticated synthetic read-only requests."""
import json
import shlex
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT/'test-artifacts/deploy-manifest.json').read_text())
sys.path.insert(0, '/opt/leadbot/brain')
import assistant_policy
import assistant_catalog
import contact_facts
import personal_media
for module in (assistant_policy, assistant_catalog, contact_facts, personal_media):
    assert Path(module.__file__).resolve().parent == Path('/opt/leadbot/brain')
assert assistant_policy.VERSION == manifest['policy_version']
suite=unittest.TestSuite()
for pattern in ('test_history_batch24_scope78.py',):
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
result=unittest.TextTestRunner().run(suite)
assert result.wasSuccessful() and result.testsRun==19
settings={}
for file in ('/etc/leadbot.env','/etc/leadbot-personal.env'):
    for line in Path(file).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key,value=line.split('=',1);settings[key]=shlex.split(value)[0] if value else ''

def read(name,pairs,action='preview'):
    ctx=dict(convId='synthetic-scope78-'+name,city='Москва',dir='bt',channel='avito',partner='7',
             accountTitle='Иван БТ',itemTitle='Ремонт техники',origin='С1',adIdentity='Иван',
             messages=[dict(id=str(i),direction=d,body=t,created_at=f'2026-10-19T10:00:{i:02d}+00:00')
                       for i,(d,t) in enumerate(pairs)])
    request=urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'],action=action,ctx=ctx)).encode(),
        headers={'Content-Type':'application/json','X-Leadbot-Token':settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(request,timeout=15) as response:
        out=json.load(response)
    assert out['ok'] and out['policy_version']==manifest['policy_version'] and out['auto_enabled'] is False
    assert not out.get('pending_model') and not out.get('validation')
    return out

ordinary=read('ordinary',[('in','Профессиональная рожковая кофемашина Nuova Simonelli, две группы')],'checklist')
assert not ordinary['approval'] and not ordinary['refuse'] and not any(r['key']=='coffee_vending' for r in ordinary['results'])
vendor=read('vendor',[('in','Кофейный торговый автомат с терминалом оплаты не работает')])
assert vendor['action']=='handoff' and 'OWNER-COFFEE-VENDING-20261019' in vendor['rule_ids']
unclear=read('unclear',[('in','Промышленная кофемашина не работает')],'checklist')
assert any(r['key']=='coffee_vending' and not r['done'] and 'терминал' in r['item'] for r in unclear['results'])
form=read('form',[('in','Кофейный торговый автомат с терминалом оплаты не работает')],'checklist')
assert 'согласован' in form['approval'] and any(s['id']=='OWNER-COFFEE-VENDING-20261019' for s in form['sources'])
print(json.dumps(dict(policy=manifest['policy_version'],installed_new_unit_tests=result.testsRun,
    authenticated_previews=1,authenticated_normal_form_checks=3,crm_reads=0,crm_writes=0,
    customer_sends=0,real_sessions_started=0,auto_enabled=False)))
