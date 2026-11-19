"""Read-only installed checks of shared request facts and visit withdrawal."""
import json
import shlex
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'test-artifacts/deploy-manifest.json').read_text())
sys.path.insert(0, '/opt/leadbot/brain')
import assistant_policy
import contact_facts

assert assistant_policy.VERSION == manifest['policy_version']
assert Path(contact_facts.__file__).resolve().parent == Path('/opt/leadbot/brain')
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_crm_access66.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful()
settings = {}
for name in ('/etc/leadbot.env', '/etc/leadbot-personal.env'):
    for line in Path(name).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            settings[key] = shlex.split(value)[0] if value else ''


def check(name, rows, action='checklist'):
    ctx = dict(convId='synthetic-crm-access66-' + name, city='Ленинск-Кузнецкий', dir='mnc', partner='7',
               channel='avito', accountTitle='Иван МНЧ', itemTitle='Услуги мастера на час',
               messages=[dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)])
    request = urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'], action=action, ctx=ctx)).encode(),
        headers={'Content-Type': 'application/json', 'X-Leadbot-Token': settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(request, timeout=10) as response:
        out = json.load(response)
    assert out['auto_enabled'] is False and out['policy_version'] == manifest['policy_version']
    return out


arrival = check('arrival-typo', [('in', 'Ленина10, кв20. Только позвоните как подъедите, я спущусь открою')])['facts']
assert arrival['call_timing'] == 'upon_arrival' and arrival['call_before_visit']
foot = check('entrance', [('in', 'Ул. Топкинская, 10/2, кв.52. Подъезд один - со стороны Ретро клуба. Домофона нет, нужно будет позвонить как подойдете, встретим.')])['facts']
assert foot['call_timing'] == 'upon_arrival' and foot['intercom_present'] is False
assert foot['address']['entrance'] == '1' and foot['address']['office'] == '52'
assert any('со стороны Ретро клуба' in x for x in foot['comment_lines'])
quiet = check('quiet', [('in', 'Борисовка24, подъезд1, этаж2, квартира2. Режим тишины с 13 до 15')])['facts']
assert quiet['address']['entrance'] == '1' and quiet['address']['floor'] == '2'
assert any('с 13 до 15' in x for x in quiet['comment_lines'])
code = check('code', [('in', 'Ленинский53к4, КВ168, подъезд3, этаж9. Домофон так же 168')])['facts']
assert code['address']['intercom'] == '168' and code['address']['office'] == '168'
withdrawn = check('withdrawal', [('in', 'Нужна замена проводки'), ('out', 'К 11 удобно?'), ('in', 'Хорошо'),
                                ('out', 'К 11 не смогу'), ('out', 'Давайте в10 спишгся обсудим по времени'),
                                ('in', 'Хорошо')], action='preview')
assert not withdrawn.get('existing_visit_evidence') and withdrawn['action'] != 'create_lead'
print(json.dumps(dict(installed_new_unit_tests=result.testsRun, authenticated_normal_form_checks=4,
                     authenticated_preview_checks=1, policy_version=manifest['policy_version'],
                     customer_sends=0, crm_writes=0, auto_enabled=False)))
