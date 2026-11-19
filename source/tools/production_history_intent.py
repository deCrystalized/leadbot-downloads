"""Installed-only unit controls and authenticated synthetic policy/form reads."""
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
import contact_facts
import extension_assistant
import qualification_state

assert assistant_policy.VERSION == manifest['policy_version']
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_manual_batch15_intent.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful()
for module in (assistant_catalog, assistant_policy, assistant_prices, contact_facts, extension_assistant, qualification_state):
    assert Path(module.__file__).resolve().parent == Path('/opt/leadbot/brain')
settings = {}
for name in ('/etc/leadbot.env', '/etc/leadbot-personal.env'):
    for line in Path(name).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            settings[key] = shlex.split(value)[0] if value else ''


def preview(name, rows, direction='mnc', action='preview'):
    assert action in ('preview', 'checklist')
    labels = dict(mnc='МНЧ', kp='КП', bt='БТ')
    titles = dict(mnc='Мастер на час', kp='Ремонт техники', bt='Ремонт посудомоечных машин')
    ctx = dict(convId='synthetic-intent62-' + name + '-' + action, city='Оренбург', dir=direction,
               partner='7', channel='avito', accountTitle='Иван ' + labels[direction], itemTitle=titles[direction],
               messages=[dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)])
    request = urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'], action=action, ctx=ctx)).encode(),
        headers={'Content-Type': 'application/json', 'X-Leadbot-Token': settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(request, timeout=10) as response:
        out = json.load(response)
    assert out.get('auto_enabled') is False and out['policy_version'] == manifest['policy_version']
    assert not out.get('pending_model') and not out.get('validation')
    return out


checks = [
    ('photo', [('in', 'Собрать шкаф'), ('out', 'Когда удобно?'), ('in', 'Позже пришлю фото или видео')], 'mnc', 'wait', ''),
    ('tv-indicator', [('in', 'В Оренбурге телевизор не включается, лампочка загорается и потом тухнет.')], 'kp', 'question', ''),
    ('monitor', [('in', 'В Оренбурге монитор искрит у входа провода питания. Вход как в компьютерном блоке питания.')], 'kp', 'question', ''),
    ('hose', [('in', 'В Оренбурге нужно поменять сливной шланг у посудомоечной машины, сколько будет стоить?')], 'bt', 'question', 'стоим|осмотр'),
    ('kitchen', [('in', 'Кухню делаете помимо сборки? Демонтаж, врезка, частично разобрать и потом собрать.')], 'mnc', 'question', 'материал|столешниц'),
    ('company', [('in', 'Мы служба доставки, на кухне лампы мигают, проблемы с проводкой.')], 'mnc', 'question', 'сч[её]ту|наличными'),
    ('window', [('in', 'Окно купе, замок не закрывается.')], 'mnc', 'handoff', ''),
    ('visit', [('in', 'Собрать шкаф'), ('out', 'Через час-полтора удобно вам будет? И номер телефона ваш, запишу вас.'), ('in', '👌')], 'mnc', 'handoff', ''),
    ('fees', [('in', 'Заменить петли шкафа'), ('out', 'Здравствуйте'), ('in', 'Можно цену?'), ('in', '?'), ('in', 'У вас вызов платный или бесплатный'), ('in', '?')], 'mnc', 'question', 'Выезд.*бесплат.*стоим|Выезд.*бесплат.*осмотр'),
    ('maximum', [('in', 'Настроить печать на два принтера, какая цена?'), ('out', 'Краткая работа от1000рублей.'), ('in', 'Максимум сколько?')], 'kp', 'handoff', ''),
    ('model-label', [('in', 'Телевизор не включается'), ('out', 'Подскажите марку и модель'), ('in', 'Telefunken называется'), ('in', 'А остальное где посмотреть?')], 'kp', 'question', 'наклейк|сзади'),
    ('price-payment', [('in', 'В Оренбурге принтерCanonG1411 не берет бумагу.'), ('out', 'Здравствуйте'), ('in', 'Сколько стоит? Нужно наличными или можно переводом будет')], 'kp', 'question', 'наличными.*переводом'),
]
for name, rows, direction, action, pattern in checks:
    out = preview(name, rows, direction)
    assert out['action'] == action, (name, out['action'], out['reason'])
    assert not pattern or re.search(pattern, out.get('reply', ''), re.I), name
    assert action not in ('wait', 'handoff') or not out.get('reply'), name

window = preview('window-form', [('in', 'Ремонт пластикового окна, замок не закрывается.')], action='checklist')
assert window['reviewed_policy'] and window['approval'] and 'DOC-L0372' in window['rule_ids']
address = preview('address-form', [('in', 'Собрать шкаф, Оренбург, 11Б мкр-104д-9кв')], action='checklist')
assert address['reviewed_policy'] and address['facts']['address']['building'] == '104'
assert address['facts']['address']['office'] == '9'
print(json.dumps(dict(installed_unit_tests=result.testsRun, authenticated_previews=len(checks),
                     normal_form_checks=2, policy_version=manifest['policy_version'],
                     auto_enabled=False, customer_sends=0, crm_writes=0)))
