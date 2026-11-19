"""Installed contact-role checks and authenticated synthetic form previews."""
import json
import shlex
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'test-artifacts/deploy-manifest.json').read_text())
sys.path.insert(0,'/opt/leadbot/brain')
import assistant_policy
import assistant_store
import contact_facts
import extension_assistant
for module in (assistant_policy,assistant_store,contact_facts,extension_assistant):
    assert Path(module.__file__).resolve().parent==Path('/opt/leadbot/brain')
assert assistant_policy.VERSION==manifest['policy_version']
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_contact_context69.py')
result=unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful()
settings={}
for file in ('/etc/leadbot.env','/etc/leadbot-personal.env'):
    for line in Path(file).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1);settings[k]=shlex.split(v)[0] if v else ''


def read(name,rows):
    ctx=dict(convId='synthetic-contact69-'+name,city='Оренбург',dir='mnc',partner='7',channel='avito',
        accountTitle='Иван МНЧ',itemTitle='Мастер на час',
        messages=[dict(id=str(i),direction=d,body=b) for i,(d,b) in enumerate(rows)])
    request=urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'],action='checklist',ctx=ctx)).encode(),
        headers={'Content-Type':'application/json','X-Leadbot-Token':settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(request,timeout=20) as response:out=json.load(response)
    assert out['ok'] is True and out['auto_enabled'] is False
    assert out['policy_version']==manifest['policy_version'] and out['manual_creation']['available'] is True
    assert not out.get('pending_model') and not out.get('validation')
    return out


base=[('in','Нужно отремонтировать шкаф'),('out','Адрес подскажите')]
out=read('arrival-code',base+[('in','Ленина 5, подъезд 3, код 08304'),
                             ('in','Как подъедете позвоните, там домофон не работает')])
assert out['facts']['address']['intercom']=='08304'
assert out['facts']['call_before_visit'] is True and out['facts']['call_timing']=='upon_arrival'
assert 'при подъезде' in '\n'.join(out['facts']['comment_lines'])
out=read('uncertain-entrance',base+[('in','Шоссе Космонавтов 51, 3 подъезд, кв 72'),
                                ('in','С подъездом могла наврать, там подъезд около Озона')])
assert not out['facts']['address'].get('entrance')
assert out['facts']['uncertain_address_fields'][0]['verified'] is False
assert 'Озона' in '\n'.join(out['facts']['comment_lines'])
out=read('postfix-access',base+[('in','Щетинкина 4 кв 10, 1 под 3 этаж домофон набир 10')])
assert {k:out['facts']['address'].get(k) for k in ('building','office','entrance','floor','intercom')}==dict(building='4',office='10',entrance='1',floor='3',intercom='10')
out=read('numbered-place',base+[('in','Подлипки 6 дом 315')])
assert out['facts']['address']['building']=='315'
out=read('changed-city',base+[('in','Г. Ленинск-Кузнецкий, улица Пушкина д.68, 3 этаж, домофон не работает'),
                           ('in','Г. Полысаево\nУл. Крупской д.15\nAS-Автокомплекс')])
assert out['facts']['address']['city']=='Полысаево' and out['facts']['address']['building']=='15'
assert not out['facts']['address'].get('floor') and out['facts']['intercom_working'] is None
assert out['hard_block'] is True
out=read('message-not-call',base+[('in','Ленина 5'),('in','Вы как подойдете, напишите, я спущусь открою'),('out','Сейчас позвоню')])
assert out['facts']['call_before_visit'] is False
assert 'напишите' in '\n'.join(out['facts']['comment_lines'])
print(json.dumps(dict(installed_new_unit_tests=result.testsRun,authenticated_normal_form_checks=6,
    policy_version=manifest['policy_version'],customer_history_uploaded=False,customer_sends=0,crm_writes=0,auto_enabled=False)))
