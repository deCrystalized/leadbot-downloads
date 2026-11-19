"""Installed-code and authenticated synthetic previews; no business writes."""
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
# Load installed modules before the isolated test file adjusts its import path.
import assistant_catalog
import assistant_policy
import assistant_prices
import assistant_qualifiers
import contact_facts

assert assistant_policy.VERSION == manifest['policy_version']
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_manual_batch14_intent.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful()
assert Path(contact_facts.__file__).resolve().parent == Path('/opt/leadbot/brain')
settings = {}
for name in ('/etc/leadbot.env', '/etc/leadbot-personal.env'):
    for line in Path(name).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            settings[key] = shlex.split(value)[0] if value else ''

def preview(name, rows, direction='mnc', title='Мастер на час', action='preview'):
    assert action in ('preview', 'checklist')
    ctx = dict(convId='synthetic-regulation-learning-' + name + '-' + action, city='Оренбург', dir=direction,
               partner='7', channel='avito', accountTitle='Иван ' + ('КП' if direction == 'kp' else 'МНЧ'),
               itemTitle=title, messages=[dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)])
    request = urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'], action=action, ctx=ctx)).encode(),
        headers={'Content-Type': 'application/json', 'X-Leadbot-Token': settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(request, timeout=10) as response:
        out = json.load(response)
    assert out.get('auto_enabled') is False and out['policy_version'] == manifest['policy_version']
    assert not out.get('pending_model') and not out.get('validation')
    return out

clog = preview('clog', [('in', 'В Оренбурге вода в унитазе медленно уходит. Какая цена?'),
                       ('out', 'Засор у вас?'), ('in', 'Да')])
assert clog['action'] == 'question' and '500' in clog['reply'] and 'погонный метр' in clog['reply']
assert clog['facts']['confirmed_clog']['question_message_id'] == '1'
company = preview('company', [('in', 'Собрать10шкафов в Оренбурге.'), ('out', 'Организация?'), ('in', 'Да')])
assert company['action'] == 'question' and re.search('сч[её]ту', company['reply'])
assert 'DOC-L0804' in company['rule_ids']
printer = preview('indicator', [('in', 'В Оренбурге принтерCanonG1411 не берет бумагу, лампочка моргает три раза.')],
                  direction='kp', title='Ремонт принтеров')
assert printer['action'] == 'question' and not re.search('несколько работ', printer['reason'], re.I)
clock = preview('conversation-clock', [('in', 'Собрать шкаф в Оренбурге'), ('out', 'Напиште в10обсудим'),
                                        ('in', 'Хорошо'), ('in', 'Цена ваша?')])
assert clock['action'] == 'question' and not re.search('существующ.*договор', clock['reason'], re.I)
deferred = preview('deferred', [('in', 'Собрать шкаф'), ('out', 'Когда принять?'),
                               ('in', 'Когда буду планировать приехать я вам напишу')])
assert deferred['action'] == 'wait' and not deferred.get('reply')
mixed = preview('mixed', [('in', 'Повесить телевизор на кронштейн, установить видео домофон.')])
assert mixed['action'] == 'handoff' and not mixed.get('reply')
clog_form = preview('clog-form', [('in', 'Вода в унитазе медленно уходит, какая цена?'),
                                ('out', 'Засор у вас?'), ('in', 'Да')], action='checklist')
assert clog_form['reviewed_policy'] and 'DOC-L0499' in clog_form['rule_ids']
mandatory = next(row for row in clog_form['results'] if row['key'] == 'mandatory_price')
assert not mandatory['done'] and 'погонный метр' in mandatory['item']
mixed_form = preview('mixed-form', [('in', 'Повесить телевизор, установить видеодомофон.')], action='checklist')
assert mixed_form['reviewed_policy'] and mixed_form['approval'] and 'DOC-L0453' in mixed_form['rule_ids']
print(json.dumps(dict(installed_unit_tests=result.testsRun, authenticated_previews=6,
                     normal_form_checklists=2,
                     policy_version=manifest['policy_version'], auto_enabled=False,
                     customer_sends=0, crm_writes=0)))
