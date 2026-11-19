"""Installed, authenticated synthetic previews; no CRM or customer transport."""
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
import qualification_state
import contact_facts
for module in (assistant_policy, assistant_catalog, qualification_state, contact_facts):
    assert Path(module.__file__).resolve().parent == Path('/opt/leadbot/brain')
assert assistant_policy.VERSION == manifest['policy_version']
suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'), pattern='test_history_batch22_intent76.py')
result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful()
settings = {}
for file in ('/etc/leadbot.env', '/etc/leadbot-personal.env'):
    for line in Path(file).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            settings[key] = shlex.split(value)[0] if value else ''


def read(name, direction, pairs, action='preview'):
    ctx = dict(convId='synthetic-history76-'+name, city='Москва', dir=direction,
               channel='avito', partner='7', accountTitle='Иван '+('БТ' if direction=='bt' else 'КП'),
               itemTitle='Ремонт техники', origin='С1', adIdentity='Иван',
               messages=[dict(id=str(i), direction=d, body=t) for i,(d,t) in enumerate(pairs)])
    req = urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'], action=action, ctx=ctx)).encode(),
        headers={'Content-Type':'application/json', 'X-Leadbot-Token':settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(req, timeout=15) as response:
        out = json.load(response)
    assert out['ok'] and out['policy_version']==manifest['policy_version'] and out['auto_enabled'] is False
    assert not out.get('pending_model') and not out.get('validation')
    return out


assert read('combined', 'bt', [('in','Печка Дарина верх газ, духовка электричество не включается')])['action']=='refuse'
warranty = read('future-warranty', 'kp', [('in','Телевизор Samsung звук есть картинки нет'),
    ('out','Нужно смотреть на месте'), ('in','Гарантия имеется после ремонта?')])
assert warranty['action']=='question' and 'оказанные услуги' in warranty['reply'] and 'бесплат' not in warranty['reply']
assert read('real-warranty', 'kp', [('in','После вашего ремонта телевизор опять не работает, у меня гарантия')])['action']=='handoff'
progress = read('repair-progress', 'kp', [('in','Есть понимание по срокам ремонта принтера?')])
assert progress['action']=='handoff' and progress['equipment_readiness_evidence']['crm_receipt_confirmed'] is False
assert read('withdrawal', 'kp', [('in','Компьютер не включается'), ('out','Когда удобно?'),
    ('in','Спасибо, но ваша услуга уже не нужна!')])['action']=='wait'
arrival = read('arrival', 'kp', [('in','Компьютер не включается'), ('in','Позвоните когда будете у подъезда')], 'checklist')
assert arrival['facts']['call_timing']=='upon_arrival'
assert 'Позвонить при подъезде по просьбе клиента.' in arrival['facts']['comment_lines']
print(json.dumps(dict(policy=manifest['policy_version'], installed_new_unit_tests=result.testsRun,
    authenticated_previews=5, authenticated_normal_form_checks=1, customer_sends=0,
    crm_reads=0, crm_writes=0, real_sessions_started=0, auto_enabled=False)))
