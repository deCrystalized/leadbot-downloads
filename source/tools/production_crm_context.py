"""Installed source and authenticated form checks from CRM-derived controls."""
import json
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
import contact_facts
import qualification_state

assert assistant_policy.VERSION == manifest['policy_version']
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_crm_context63.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful()
for module in (assistant_catalog, assistant_prices, contact_facts, qualification_state):
    assert Path(module.__file__).resolve().parent == Path('/opt/leadbot/brain')
settings = {}
for name in ('/etc/leadbot.env', '/etc/leadbot-personal.env'):
    for line in Path(name).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            settings[key] = shlex.split(value)[0] if value else ''


def checklist(name, rows):
    ctx = dict(convId='synthetic-crm-context63-' + name, city='Оренбург', dir='mnc', partner='7',
               channel='avito', accountTitle='Иван МНЧ', itemTitle='Сборка и ремонт мебели',
               messages=[dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)])
    request = urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'], action='checklist', ctx=ctx)).encode(),
        headers={'Content-Type': 'application/json', 'X-Leadbot-Token': settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(request, timeout=10) as response:
        out = json.load(response)
    assert out['reviewed_policy'] and out['auto_enabled'] is False
    assert out['policy_version'] == manifest['policy_version']
    return out


repair = checklist('repair', [('in', 'В Оренбурге кухонный гарнитур собран, нужно отрегулировать фасады.'),
                              ('out', 'От 1500 рублей.'), ('in', 'Да, от 1500 рублей меня устраивает.')])
assert not {'instructions', 'countertop_material'}.intersection(r['key'] for r in repair['results'])
assert 'OWNER-FURNITURE-REPAIR-MIN-20261018' in repair['rule_ids']
assert next(r for r in repair['results'] if r['key'] == 'price_consent')['done']
assembly = checklist('assembly', [('in', 'В Оренбурге собрать новую кухню и отрегулировать фасады.')])
assert 'instructions' in [r['key'] for r in assembly['results']]
pending = checklist('time-not-price', [('in', 'В Оренбурге прикрутить излив к смесителю, сколько стоит?'),
                                     ('out', 'От 800 рублей.'), ('in', 'Хорошо, подумаю.'),
                                     ('out', 'Хорошо, если что — я на связи.'), ('in', 'Сегодня можете посмотреть?'),
                                     ('out', 'Через час-полтора удобно вам будет?'), ('in', 'Да, Ленина8 кв20.')])
assert pending['hard_block']
assert not next(r for r in pending['results'] if r['key'] == 'price_consent')['done']
accepted = checklist('named-price', [('in', 'В Оренбурге повесить картину.'),
                                    ('out', 'От 800 рублей.'), ('in', 'Подумаю'),
                                    ('in', 'Да, от 800 рублей меня устраивает.')])
price = next(r for r in accepted['results'] if r['key'] == 'price_consent')
assert price['done'] and {r['message_id'] for r in price['evidence']} == {'1', '3'}
unverified = checklist('named-price-unverified-quote', [('in', 'В Оренбурге прикрутить излив к смесителю.'),
                                                     ('out', 'От 800 рублей.'), ('in', 'Подумаю'),
                                                     ('in', 'Да, от 800 рублей меня устраивает.')])
assert not next(r for r in unverified['results'] if r['key'] == 'price_consent')['done']
assert unverified['hard_block'] and 'не подтверждена' in unverified['operator_review']
intercom = checklist('intercom', [('in', 'Собрать стол, Оренбург, Ленина8, кв20. Домофона нет.')])
assert intercom['facts']['intercom_present'] is False
assert any('Домофон отсутствует' in r for r in intercom['facts']['comment_lines'])
print(json.dumps(dict(installed_new_unit_tests=result.testsRun, authenticated_normal_form_checks=6,
                     policy_version=manifest['policy_version'], customer_sends=0, crm_writes=0,
                     auto_enabled=False)))
