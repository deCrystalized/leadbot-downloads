"""Installed unified policy + real GigaChat, synthetic text only, no customer writes."""
import json
import shlex
import sqlite3
import sys
import time
import unittest
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,'/opt/leadbot/brain')
import assistant_policy
import gigachat_api
import leadchat
import server

settings={}
for name in ('/etc/leadbot.env','/etc/leadbot-personal.env'):
    for line in Path(name).read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1);settings[k]=shlex.split(v)[0] if v else ''
manifest=json.loads((ROOT/'test-artifacts/deploy-manifest.json').read_text())
assert assistant_policy.VERSION==manifest['policy_version']
assert settings['LEADBOT_MODEL_PROVIDER']=='gigachat'
assert settings['LEADBOT_EXECUTION_CHANNEL']=='personal_extension'
assert not server._legacy_transport_allowed()
with urllib.request.urlopen('http://127.0.0.1:8788/api/health',timeout=5) as response:
    health=json.load(response)
assert health['model_provider']=='gigachat' and health['legacy_server_sender'] is False
for module in (assistant_policy,gigachat_api,leadchat,server):
    assert Path(module.__file__).resolve().parent==Path('/opt/leadbot/brain')
suite=unittest.TestSuite()
for pattern in ('test_unified_legacy82.py','test_neural_review81.py'):
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
result=unittest.TextTestRunner().run(suite)
assert result.wasSuccessful()

def post(url,body):
    req=urllib.request.Request(url,data=json.dumps(body).encode(),method='POST',
        headers={'Content-Type':'application/json','X-Leadbot-Token':settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(req,timeout=28) as response:return json.load(response)

# A unique synthetic probe establishes a fresh provider call, not a cache-only success.
stamp=str(time.time_ns())
t0=time.monotonic()
probe=post('http://127.0.0.1:8081/internal/leadbot/completion',dict(
    system='Ответь только JSON-объектом {"probe":"ok"}.',task='Синтетическая проверка соединения '+stamp,max_tokens=64))
assert probe['ok'] and json.loads(probe['text'])=={'probe':'ok'}
assert probe['model'].startswith('GigaChat') and probe['cached'] is False
provider_ms=round((time.monotonic()-t0)*1000)
samples=[('pc','kp','Компьютерный мастер','Компьютер не включается в Чите.'),
         ('sport','mnc','Мастер на час','В Чите нужно установить турник.'),
         ('bt','bt','Ремонт техники','В Чите кофемашина перестала включаться.')]
results=[]
for name,direction,title,text in samples:
    body=dict(chat='synthetic-unified82-'+name+'-'+stamp,request_id='probe-'+name+'-'+stamp,
        city='Чита',direction=direction,partner='7',channel='avito',account_title='Денис',
        ad_identity='Денис',origin='С1',item_title=title,wording_mode='neural_review',
        dialog=[dict(id='in-1',role='user',content=text)])
    out=post('http://127.0.0.1:8788/api/leadchat/answer',body)
    draft=out['meta']['draft']
    assert out['reply']=='' and out['needs_operator']
    assert out['meta']['auto_enabled'] is False and out['meta']['lead_ready'] is False
    assert draft['policy_version']==manifest['policy_version'] and not draft.get('validation')
    assert draft['reply'].startswith('Здравствуйте!')
    results.append(dict(case=name,reply=draft['reply'],source=draft['response_source'],model=draft.get('model',''),
        model_status=draft.get('model_status')))
# A successful provider draft can deliberately fall back to the approved
# wording. That source must stay visible instead of being called model text.
assert any(row['model'].startswith('GigaChat') and row['source'] in ('model','server_template') for row in results)
db=sqlite3.connect('file:/opt/leadbot/data/assistant.sqlite3?mode=ro',uri=True)
assert db.execute("SELECT count(*) FROM personal_sessions WHERE expires>? AND execution_mode='auto'",(time.time(),)).fetchone()[0]==0
print(json.dumps(dict(policy=assistant_policy.VERSION,installed_unit_tests=result.testsRun,
    fresh_provider=probe['model'],provider_ms=provider_ms,previews=results,customer_sends=0,
    crm_writes=0,real_sessions_started=0,auto_enabled=False),ensure_ascii=False))
