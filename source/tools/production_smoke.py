import hashlib,json,shlex,subprocess,urllib.request,urllib.error
from pathlib import Path
root=Path('/root/leadbot-assistant-release')
manifest=json.loads((root/'test-artifacts/deploy-manifest.json').read_text())
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
code,out=call({'owner':'smoke','action':'send'});assert code==403 and out['auto_enabled'] is False
ctx={'convId':'synthetic-release-smoke-tv','city':'Чита','dir':'kp','partner':'7','accountTitle':'Тест КП','itemTitle':'Ремонт телевизоров','messages':[{'id':'m1','direction':'in','body':'В телевизоре разбита матрица'}]}
_,out=call({'owner':'smoke','action':'preview','ctx':ctx});assert out['action']=='refuse' and out['auto_enabled'] is False and out['lead']['can_create_automatically'] is False
_,replay=call({'owner':'smoke','action':'preview','ctx':ctx});assert replay['cached'] is True
for city,expected in [('Феодосия','known'),('Курган','known'),('Элиста','needs_confirmation')]:
 _,geo=call({'owner':'smoke','action':'geography','city':city,'dir':'kp'});assert geo['policy']['status']==expected
print(json.dumps({'hashes_verified':len(manifest['entries']),'auth_without_token':401,'send':403,'preview':'refuse','repeat_cached':True,'auto_enabled':False,'crm_auto_create':False,'city_checks':3}))
