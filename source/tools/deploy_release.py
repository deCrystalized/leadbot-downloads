"""Run as root on the bot host. Verify baselines, backup, install; no channel settings."""
import argparse
import grp
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'test-artifacts/deploy-manifest.json').read_text())
entries=manifest['entries']
required={'leadbot/brain/assistant_store.py','leadbot/brain/assistant_policy.py',
          'leadbot/brain/extension_assistant.py','leadbot/brain/personal_workflow.py',
          'leadbot/brain/own_visit.py'}
missing=required-{item['source'] for item in entries}
if missing:raise SystemExit('Incomplete runtime manifest: '+', '.join(sorted(missing)))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for item in entries:
 source=(ROOT/item['source']).resolve()
 if not source.is_relative_to(ROOT) or not source.is_file():raise SystemExit('Invalid staged source: '+str(item['source']))
 if sha(source)!=item.get('sha256'):raise SystemExit('Staged source changed: '+str(item['source']))
 target=Path(item['target']);expected=item.get('baseline_sha256')
 if expected and (not target.exists() or sha(target)!=expected):raise SystemExit('Baseline changed: '+str(target))
 if expected is None and target.exists() and target.name!='index.js':raise SystemExit('New file already exists: '+str(target))
print('Baseline verified:',len(entries),'files')
if '--apply' not in __import__('sys').argv:raise SystemExit(0)
backup=Path('/root/leadbot-release-backups')/time.strftime('%Y%m%d-%H%M%S');backup.mkdir(parents=True,mode=0o700)
protected=[Path('/etc/lead-centre/leadbot-assistant.env'),Path('/etc/systemd/system/lc-brain.service.d/assistant.conf')]
if manifest.get('personal_owner_id'):
 protected += [Path('/etc/leadbot-personal.env'),Path('/etc/systemd/system/leadbot.service.d/personal.conf'),Path('/etc/systemd/system/lc-brain.service.d/personal.conf')]
state=[]
for item in entries+[{'target':str(p)} for p in protected]:
 target=Path(item['target']);row={'target':str(target),'existed':target.exists()}
 if target.exists():
  saved=backup/str(target).lstrip('/');saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved);row['saved']=str(saved)
 state.append(row)
(backup/'restore.json').write_text(json.dumps(state,indent=2));os.chmod(backup/'restore.json',0o600)
try:
 for item in entries:
  source=ROOT/item['source'];target=Path(item['target']);target.parent.mkdir(parents=True,exist_ok=True)
  temp=target.with_name(target.name+'.release-tmp');shutil.copyfile(source,temp);os.chmod(temp,0o644)
  if str(target).startswith('/opt/lead-centre/'):
   import pwd
   os.chown(temp,pwd.getpwnam('lc').pw_uid,grp.getgrnam('lc').gr_gid)
  os.replace(temp,target)
 secret=''
 for line in Path('/etc/leadbot.env').read_text().splitlines():
  if line.startswith('LEADBOT_SERVICE_TOKEN='):secret=shlex.split(line.split('=',1)[1])[0]
 if not secret:raise RuntimeError('Missing service token')
 envfile=protected[0];envfile.write_text('LEADBOT_SERVICE_TOKEN='+json.dumps(secret)+'\n');os.chmod(envfile,0o640);os.chown(envfile,0,grp.getgrnam('lc').gr_gid)
 dropin=protected[1];dropin.parent.mkdir(exist_ok=True);dropin.write_text('[Service]\nEnvironmentFile=/etc/lead-centre/leadbot-assistant.env\n')
 if manifest.get('personal_owner_id'):
  owner=manifest['personal_owner_id'];operator=manifest['personal_operator_id']
  import re
  if not re.fullmatch(r'[A-Za-z0-9_-]{4,60}',owner) or not re.fullmatch(r'[a-f0-9-]{36}',operator):raise RuntimeError('Invalid personal binding')
  personal=protected[2]
  lines=personal.read_text().splitlines() if personal.exists() else []
  settings={'LEADBOT_PERSONAL_OWNER_ID':owner,'LEADBOT_PERSONAL_OPERATOR_ID':operator,'LEADBOT_ASSISTANT_WORDING':'reviewed'}
  if manifest.get('unified_personal_brain') is True:
   settings.update(LEADBOT_MODEL_PROVIDER='gigachat',LEADBOT_EXECUTION_CHANNEL='personal_extension')
  if 'personal_auto_available' in manifest:settings['LEADBOT_PERSONAL_AUTO_AVAILABLE']='1' if manifest['personal_auto_available'] is True else '0'
  lines=[line for line in lines if line.split('=',1)[0] not in settings]
  personal.write_text('\n'.join(lines+[k+'='+v for k,v in settings.items()])+'\n');os.chmod(personal,0o640);os.chown(personal,0,grp.getgrnam('lc').gr_gid)
  for p in protected[3:]:p.parent.mkdir(parents=True,exist_ok=True);p.write_text('[Service]\nEnvironmentFile=/etc/leadbot-personal.env\n')
 subprocess.run(['systemctl','daemon-reload'],check=True)
 subprocess.run(['systemctl','restart','leadbot','lc-brain'],check=True)
 import urllib.request
 for attempt in range(12):
  try:
   with urllib.request.urlopen('http://127.0.0.1:8788/api/health',timeout=2) as r:
    if r.status==200:break
  except Exception:time.sleep(1)
 else:raise RuntimeError('LeadBot failed health check')
 body=json.dumps({'owner':manifest.get('personal_owner_id') or 'synthetic-release-smoke','action':'status'}).encode()
 req=urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',data=body,headers={'Content-Type':'application/json','X-Leadbot-Token':secret})
 # Cold registry/store initialization was measured at4.7s on the bot host.
 # Keep the readiness conditions strict while allowing one bounded15s read.
 with urllib.request.urlopen(req,timeout=15) as r:status=json.load(r)
 if not status.get('ok') or status.get('auto_enabled') is not False:raise RuntimeError('Assistant status check failed')
 for service in ('leadbot','lc-brain'):
  if subprocess.check_output(['systemctl','is-active',service]).decode().strip()!='active':raise RuntimeError(service+' inactive')
 print(json.dumps({'installed':True,'backup':str(backup),'files':len(entries),'auto_enabled':False}))
except BaseException:
 for item in reversed(state):
  target=Path(item['target'])
  if item['existed']:shutil.copy2(item['saved'],target)
  elif target.exists():target.unlink()
 subprocess.run(['systemctl','daemon-reload']);subprocess.run(['systemctl','restart','leadbot','lc-brain'])
 raise
