"""Installed scoped-object checks; no customer history or write grants."""
import json
import shlex
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'test-artifacts/deploy-manifest.json').read_text())
sys.path.insert(0,'/opt/leadbot/brain')
import assistant_catalog
import assistant_policy
import assistant_prices
import assistant_store
import contact_facts
import extension_assistant
for module in (assistant_catalog,assistant_policy,assistant_prices,assistant_store,contact_facts,extension_assistant):
    assert Path(module.__file__).resolve().parent==Path('/opt/leadbot/brain')
assert assistant_policy.VERSION==manifest['policy_version']
suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern)
                         for pattern in ('test_catalog_object_roles71.py','test_graphics_assertion_roles72.py'))
result=unittest.TextTestRunner(verbosity=1).run(suite);assert result.wasSuccessful()
settings={}
for file in ('/etc/leadbot.env','/etc/leadbot-personal.env'):
    for line in Path(file).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1);settings[k]=shlex.split(v)[0] if v else ''


def read(name,rows,action='preview',direction='kp'):
    ctx=dict(convId='synthetic-object71-'+name,city='Оренбург',dir=direction,partner='7',channel='avito',
        accountTitle='Иван '+('КП' if direction=='kp' else 'МНЧ'),itemTitle='Компьютерная помощь' if direction=='kp' else 'Мастер на час',
        messages=[dict(id=str(i),direction=d,body=t) for i,(d,t) in enumerate(rows)])
    req=urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'],action=action,ctx=ctx)).encode(),
        headers={'Content-Type':'application/json','X-Leadbot-Token':settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(req,timeout=20) as response:out=json.load(response)
    assert out['ok'] is True and out['auto_enabled'] is False and out['policy_version']==manifest['policy_version']
    assert not out.get('pending_model') and not out.get('validation')
    return out


symptom='Подарили рабочую видеокарту, нет картинки, экран чёрный'
unknown=[('in',symptom+' Сколько будет стоить?')]
out=read('host-unknown',unknown)
assert out['action']=='question' and 'компьютер' in out['reply'].lower() and '5000' not in out['reply']
host=[('in',symptom),('out','Видеокарта вставлена в ПК?'),('in','Да конечно')]
out=read('host-diagnostic',host+[('in','Сколько стоит диагностика?')])
assert out['action']=='question' and '1000' in out['reply'] and 'бесплат' in out['reply'] and '5000' not in out['reply']
out=read('host-diagnostic-refined',host+[('in','Сколько это стоит?'),('out','Диагностика?'),('in','Да')])
assert out['action']=='question' and '1000' in out['reply'] and 'бесплат' in out['reply']
out=read('card-repair',[('in','Нужен ремонт видеокарты, пайка')])
assert out['action']=='question' and '5000' in out['reply'] and 'DOC-L0152' in out['rule_ids']
out=read('tv-server',[('in','Телевизор Philips пишет что не может найти сервера')])
assert out['action']=='question' and not any(r['rule_id']=='pc-server' for r in out['service']['items'])
out=read('tv-furniture',[('in','Сколько стоит сборка ТВ тумбы?')],direction='mnc')
assert out['action']=='question' and {r['rule_id'] for r in out['service']['items']}=={'furniture'}
for name,body in [('question','Видеокарта установлена в компьютере?'),('hypothesis','Если видеокарта установлена в компьютере, но нет изображения, почему?')]:
    out=read('role-'+name,[('in',symptom),('in',body)])
    assert out['action']=='question' and out['facts']['graphics_scope']['kind']=='device_uncertain'
    assert '5000' not in out['reply'] and '1000' not in out['reply']
out=read('host-form',host,action='checklist')
assert out['facts']['graphics_scope']['kind']=='host_diagnostic' and 'DOC-L0152' not in out['rule_ids']
assert out['facts']['graphics_scope']['message_id']=='2' and out['manual_creation']['available'] is True
out=read('unknown-form',unknown,action='checklist')
assert any(r['key']=='graphics_host' and r['done'] is False for r in out['results'])
assert out['manual_creation']['available'] is True and '5000' not in out['reason']
print(json.dumps(dict(installed_object_unit_tests=result.testsRun,authenticated_previews=8,authenticated_normal_form_checks=2,
    policy_version=manifest['policy_version'],customer_history_uploaded=False,customer_sends=0,crm_writes=0,auto_enabled=False)))
