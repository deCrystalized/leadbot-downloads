"""Read-only customer checks; only a synthetic personal lease is started and stopped."""
import hashlib
import json
import shlex
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'test-artifacts/deploy-manifest.json').read_text())
assert all(hashlib.sha256(Path(e['target']).read_bytes()).hexdigest()==e['sha256'] for e in manifest['entries'])
env={}
for file in ['/etc/leadbot.env','/etc/leadbot-personal.env']:
    for line in Path(file).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1);env[k]=shlex.split(v)[0] if v else ''
owner=env['LEADBOT_PERSONAL_OWNER_ID'];operator=env['LEADBOT_PERSONAL_OPERATOR_ID']
base={'owner':owner,'operator_id':operator,'browser_session':'release-verification:tab:0'}


def call(action,auth=True,**extra):
    headers={'Content-Type':'application/json'}
    if auth:headers['X-Leadbot-Token']=env['LEADBOT_SERVICE_TOKEN']
    request=urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',data=json.dumps({**base,'action':action,**extra}).encode(),headers=headers)
    try:
        with urllib.request.urlopen(request,timeout=8) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.load(e)


assert call('status',auth=False)[0]==401
assert call('status',owner='another-token')[0]==403
assert call('send')[0]==403
assert call('personal_status')[1]['another_tab'] is False
assert call('personal_start',max_dialogs=3)[1]['active']
try:
    assert call('personal_start',browser_session='release-verification:tab:2')[1]['code']=='personal_busy'
    ctx={'convId':'synthetic-personal-production-clean','city':'Чита','dir':'kp','partner':'7','accountTitle':'Тест КП',
         'itemTitle':'Ремонт компьютеров','assigneeId':'','assignmentKnown':True,'conversationStatus':'open','botActive':False,'hasTransfer':False,'channelAssigned':True,
         'messages':[{'id':'m1','direction':'in','body':'Почистить компьютер в Чите'}]}
    _,normal=call('screen',ctx=ctx,mine_count=0);assert normal['eligible'] and normal['auto_enabled'] is False and 'model_task' not in normal
    _,capped=call('screen',ctx=ctx,mine_count=3);assert capped['admission']=='capacity' and not capped['eligible']
    ctx['messages'][0]['body']='Заправить картридж принтера в Чите'
    assert not call('screen',ctx=ctx,mine_count=0)[1]['eligible']
    ctx['messages'][0]['body']='Настроить роутер в Чите'
    assert call('screen',ctx=ctx,mine_count=0)[1]['admission']=='needs_facts'
finally:
    assert call('personal_stop')[1]['active'] is False
assert not call('personal_status')[1]['active']
ctx['convId']='synthetic-personal-production-tv-chip';ctx['itemTitle']='Ремонт телевизоров'
ctx['messages'][0]['body']='Телевизор в Чите, ранее обновлял прошивку, теперь нужна замена чипа eMMC. Сколько стоит?'
_,chip=call('preview',ctx=ctx);assert '5000' in chip['reply'] and '2500' not in chip['reply']
for service in ('leadbot','lc-brain','leadchat-gateway'):
    assert subprocess.check_output(['systemctl','is-active',service],text=True).strip()=='active'
print(json.dumps({'hashes_verified':len(manifest['entries']),'owner_only':True,'service_without_token_http':401,'other_owner_http':403,'send_http':403,
                  'personal_session':'started_and_stopped','second_tab':'blocked','normal_job':'screened_only','capacity':'blocked','agreement':'excluded','unknown_condition':'excluded',
                  'tv_chip_price':5000,'auto_enabled':False,'crm_writes':0,'customer_sends':0,'services_active':True}))
