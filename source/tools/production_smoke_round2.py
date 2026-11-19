import hashlib,json,shlex,subprocess,urllib.request,urllib.error
from pathlib import Path
root=Path('/root/leadbot-assistant-round2-release')
manifest=json.loads((root/'test-artifacts/deploy-manifest.json').read_text())
patch=json.loads(Path('/root/leadbot-assistant-round2-fix/test-artifacts/deploy-manifest.json').read_text())
merged={e['target']:e for e in manifest['entries']}
merged.update({e['target']:e for e in patch['entries']})
final=json.loads(Path('/root/leadbot-assistant-round2-final/test-artifacts/deploy-manifest.json').read_text())
merged.update({e['target']:e for e in final['entries']})
manifest['entries']=list(merged.values())
assert all(hashlib.sha256(Path(e['target']).read_bytes()).hexdigest()==e['sha256'] for e in manifest['entries'])
secret=''
for line in Path('/etc/leadbot.env').read_text().splitlines():
 if line.startswith('LEADBOT_SERVICE_TOKEN='):secret=shlex.split(line.split('=',1)[1])[0]
def call(body,auth=True):
 headers={'Content-Type':'application/json'}
 if auth:headers['X-Leadbot-Token']=secret
 req=urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',data=json.dumps(body).encode(),headers=headers)
 try:
  with urllib.request.urlopen(req,timeout=8) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.load(e)
assert call({'owner':'smoke','action':'status'},False)[0]==401
_,status=call({'owner':'smoke','action':'status'});assert status['policy_version']=='2026-10-15.4' and status['auto_enabled'] is False
code,out=call({'owner':'smoke','action':'send'});assert code==403 and out['auto_enabled'] is False
ctx={'convId':'synthetic-release-smoke-tv','city':'Чита','dir':'kp','partner':'7','accountTitle':'Тест КП','itemTitle':'Ремонт телевизоров','messages':[{'id':'m1','direction':'in','body':'В телевизоре разбита матрица'}]}
_,out=call({'owner':'smoke','action':'preview','ctx':ctx});assert out['action']=='refuse' and out['auto_enabled'] is False and out['lead']['can_create_automatically'] is False
_,replay=call({'owner':'smoke','action':'preview','ctx':ctx});assert replay['cached'] is True
for city,expected in [('Феодосия','known'),('Курган','known'),('Элиста','needs_confirmation')]:
 _,geo=call({'owner':'smoke','action':'geography','city':city,'dir':'kp'});assert geo['policy']['status']==expected
ctx2={**ctx,'convId':'synthetic-production-round2-620','dir':'mnc','partner':'620','itemTitle':'Сантехник','messages':[{'id':'m1','direction':'in','body':'В Чите поменять смеситель'}]}
_,prepared=call({'owner':'round2-smoke','action':'preview','ctx':ctx2})
assert prepared['pending_model']
_,done=call({'owner':'round2-smoke','action':'finalize','request_id':prepared['request_id'],'revision':prepared['revision'],'candidate':{'reply':'На кухне или в ванной?','needs_operator':False}})
assert done['reply'].startswith('Вы обратились к частному мастеру') and not done['validation']
_,geo=call({'owner':'smoke','action':'geography','city':'Дудинка','dir':'kp'});assert geo['policy']['crm_city']=='Норильск' and geo['policy']['far_trip']
matrix_cases=[('suspected','Телевизор не показывает, возможно матрица',False),('possible-replacement','Телевизор, может нужна замена матрицы?',False),('negated-bands','Телевизор, полос нет, матрица целая',False),('actual-bands','На телевизоре появились вертикальные полосы',True),('actual-crack','Телевизор, треснул экран',True)]
for name,text,refuse in matrix_cases:
 current={**ctx,'convId':'synthetic-round2-final-'+name,'messages':[{'id':'m1','direction':'in','body':text}]}
 _,prepared=call({'owner':'round2-final-smoke','action':'preview','ctx':current})
 assert (prepared['action']=='refuse') is refuse,(name,prepared['action'])
 if not refuse:
  assert prepared['pending_model']
  task=json.loads(prepared['model_task']['task']);question=task['decision']['next_question']['question']
  _,done=call({'owner':'round2-final-smoke','action':'finalize','request_id':prepared['request_id'],'revision':prepared['revision'],'candidate':{'reply':question,'needs_operator':False}})
  assert not done['validation'] and done['reply']
  _,valid=call({'owner':'round2-final-smoke','action':'validate','ctx':current,'draft_id':done['draft_id']});assert valid['ok'] and valid['reply']
print(json.dumps({'required_620_inserted':True,'hashes_verified':len(manifest['entries']),'auth_without_token':401,'send':403,'preview':'refuse','repeat_cached':True,'auto_enabled':False,'crm_auto_create':False,'city_checks':3,'matrix_boundary_cases_passed':len(matrix_cases),'policy_version':status['policy_version']}))
