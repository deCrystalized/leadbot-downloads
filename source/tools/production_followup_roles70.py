"""Installed question-role and closure checks; synthetic previews only."""
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
import extension_assistant
for module in (assistant_policy,assistant_store,extension_assistant):
    assert Path(module.__file__).resolve().parent==Path('/opt/leadbot/brain')
assert assistant_policy.VERSION==manifest['policy_version']
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_followup_answer_roles70.py')
result=unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful()
settings={}
for file in ('/etc/leadbot.env','/etc/leadbot-personal.env'):
    for line in Path(file).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1);settings[k]=shlex.split(v)[0] if v else ''


def preview(name,rows,action,*,image=False,request_action='preview'):
    ms=[dict(id=str(i),direction=d,body=b) for i,(d,b) in enumerate(rows)]
    if image:ms.insert(1,dict(id='old-image',direction='in',body='',attachments=[dict(kind='image',url='https://example.invalid/image.jpg')]))
    ctx=dict(convId='synthetic-followup70-'+name,city='Оренбург',dir='mnc',partner='7',channel='avito',
        accountTitle='Иван МНЧ',itemTitle='Мастер на час',messages=ms)
    req=urllib.request.Request('http://127.0.0.1:8788/api/extension/assistant',
        data=json.dumps(dict(owner=settings['LEADBOT_PERSONAL_OWNER_ID'],action=request_action,ctx=ctx)).encode(),
        headers={'Content-Type':'application/json','X-Leadbot-Token':settings['LEADBOT_SERVICE_TOKEN']})
    with urllib.request.urlopen(req,timeout=20) as response:out=json.load(response)
    assert out['ok'] is True and out['auto_enabled'] is False
    if request_action=='preview':assert out['action']==action
    assert out['policy_version']==manifest['policy_version']
    assert not out.get('pending_model') and not out.get('validation')
    return out


base=[('in','Нужно прикрутить шкаф, стена кирпичная')]
for name,question in [('presence','Вы тут?'),('relevance','Актуально?')]:
    out=preview(name,base+[('out','Через час-полтора удобно?'),('out',question),('in','Да конечно')],'question')
    assert not out.get('existing_visit_evidence')
out=preview('decline',base+[('out','Когда удобно, чтобы я приехал?'),('in','Нет тогда')],'wait',image=True)
assert out['crm_flags']['customer_declined'] is True
out=preview('decline-after-visit',base+[('out','К 12 удобно?'),('in','Да'),('in','Нет тогда')],'handoff')
assert 'договорённость' in out['reason']
out=preview('staff-claim',base+[('out','К 12 удобно?'),('out','Вы тут?'),('in','Да'),
    ('out','Хорошо, записал вас — до встречи'),('in','Ок')],'handoff')
assert not out.get('existing_visit_evidence') and out['staff_booking_claim']['crm_write_confirmed'] is False
out=preview('staff-claim-form',base+[('out','К 12 удобно?'),('out','Вы тут?'),('in','Да'),
    ('out','Хорошо, записал вас — до встречи'),('in','Ок')],'handoff',request_action='checklist')
assert out['staff_booking_claim']['crm_write_confirmed'] is False
assert out['staff_booking_claim']['source']=='staff_statement_unverified'
assert 'проверяет' in out['operator_review'] and out['manual_creation']['available'] is True
out=preview('document-charge',base+[('in','Цены бешеные, в договоре поставили планка 550 руб это моя, за одну дырку 3000 руб и еще приписка')],'handoff',image=True)
assert 'ОКК' in out['reason']
assert out['existing_price_complaint_evidence'][0]['source']=='client_report_unverified'
out=preview('contact-closure',base+[('in','У вас есть контактный телефон?'),('out','В шапке профиля есть'),('in','ок')],'wait')
out=preview('refusal-closure',base+[('out','К сожалению, не смогу вам помочь'),('in','Принято')],'wait',image=True)
print(json.dumps(dict(installed_new_unit_tests=result.testsRun,authenticated_preview_checks=8,authenticated_normal_form_checks=1,
    policy_version=manifest['policy_version'],customer_history_uploaded=False,customer_sends=0,crm_writes=0,auto_enabled=False)))
