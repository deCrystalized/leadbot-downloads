"""Installed modules and synthetic preview/checklist checks; no customer writes."""
import json
import re
import shlex
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'test-artifacts/deploy-manifest.json').read_text())
sys.path.insert(0, '/opt/leadbot/brain')
import assistant_catalog
import assistant_policy
import assistant_prices
import assistant_qualifiers
import assistant_store
import contact_facts
import extension_assistant
import qualification_state

for module in (assistant_catalog, assistant_policy, assistant_prices, assistant_qualifiers,
               assistant_store, contact_facts, extension_assistant, qualification_state):
    assert Path(module.__file__).resolve().parent == Path('/opt/leadbot/brain')
assert assistant_policy.VERSION == manifest['policy_version']
suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=pattern)
    for pattern in ('test_chatter_lifecycle68.py','test_address_roles68.py','test_chatter_scope68.py'))
result = unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful()
settings = {}
for name in ('/etc/leadbot.env','/etc/leadbot-personal.env'):
    for line in Path(name).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=',1)
            settings[key] = shlex.split(value)[0] if value else ''


def read(name, rows, direction='mnc', action='preview'):
    assert action in ('preview','checklist')
    ctx = dict(convId='synthetic-roles68-' + name, city='Оренбург', dir=direction,
        partner='7', channel='avito', accountTitle='Иван ' + ('КП' if direction=='kp' else 'МНЧ'),
        itemTitle='Компьютерный мастер' if direction=='kp' else 'Мастер на час',
        messages=[dict(id=str(i), direction=d, body=b) for i,(d,b) in enumerate(rows)])
    request = urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'],action=action,ctx=ctx)).encode(),
        headers={'Content-Type':'application/json','X-Leadbot-Token':settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(request,timeout=15) as response:
        out=json.load(response)
    assert out['auto_enabled'] is False and out['policy_version']==manifest['policy_version']
    assert not out.get('pending_model') and not out.get('validation')
    return out


cases = [
    ('later',[('in','Собрать шкаф'),('in','Позже отвечу')],'mnc','wait',''),
    ('resolved',[('in','Поменять автомат'),('in','Спасибо, автомат заменили, всё хорошо, спасибо')],'mnc','wait',''),
    ('limit',[('in','Нужно починить стол'),('out','Через час-полтора удобно?'),('in','Жду до 111')],'mnc','question','врем'),
    ('fee',[('in','За что ваш мастер взял 500 рублей за осмотр?')],'kp','question','полный.*номер'),
    ('refund',[('in','За что взяли 500 рублей за осмотр?'),('in','Верни лишние деньги')],'kp','handoff',''),
    ('animal',[('in','В принтере застряла мышь, не может выбраться')],'kp','handoff',''),
    ('avito',[('in','Повесить карниз'),('in','Напишите пожалуйста свой номер')],'mnc','question','Авито'),
    ('onsite',[('in','Засохла краска в принтере'),('in','Нужно ли вам забирать его или можно всё сделать дома сразу?')],'kp','question','выезжает.*адрес'),
    ('electric',[('in','Обломан провод на выключателе, нужно нарастить провод')],'mnc','question',''),
    ('pc',[('in','Сколько диагностика?'),('out','Диагностика чего?'),('in','Монитор показывает power saving mode. Диагностика ПК нужна')],'kp','question','1000'),
    ('network',[('in','Нарастить интернет-кабель')],'kp','handoff',''),
    ('unknown-wires',[('in','От компьютеров в кабинете осталось много проводов, отключить и отрезать?')],'kp','question','сетев|электрическ'),
    ('drain',[('in','Доделать кровать и раковина засорилась')],'mnc','question','500.*погонный метр'),
    ('configuration',[('in','Прошивка роутера под VPN'),('in','Можно просто настроить VPN. Без прошивки')],'kp','question',''),
    ('backing',[('in','Повесить люстру, потолок натяжной'),('out','Закладная есть?'),('in','Должна быть')],'mnc','question','проверить.*закладная'),
]
outputs={}
for name, rows, direction, action, pattern in cases:
    out=read(name,rows,direction)
    assert out['action']==action,(name,out['action'],out['reason'])
    assert not pattern or re.search(pattern,out.get('reply',''),re.I),name
    outputs[name]=out
assert outputs['resolved']['service_resolution_evidence']['crm_completion_confirmed'] is False
assert not outputs['fee']['facts']['contact_phone_to_use']
assert 'ОКК' in outputs['refund']['reason']
assert outputs['backing'].get('qualification',{}).get('support',{}).get('status')!='answered'

for name, body, role in [('meeting','Это адрес встречи: Интернационалистов 12/1, подъезд 6','meeting'),
                         ('landmark','Северо-Донецкая 1, это как ориентир','landmark')]:
    out=read(name,[('in','Починить шкаф'),('in',body)],action='checklist')
    assert out['hard_block'] is True
    assert out['facts']['worksite_address_pending'] is True
    assert not out['facts']['address'].get('building')
    assert out['facts']['address_references'][-1]['role']==role
    assert out['manual_creation']['available'] is True
print(json.dumps(dict(installed_new_unit_tests=result.testsRun,authenticated_previews=len(cases),
    authenticated_normal_form_checks=2,policy_version=manifest['policy_version'],customer_history_uploaded=False,
    customer_sends=0,crm_writes=0,auto_enabled=False)))
