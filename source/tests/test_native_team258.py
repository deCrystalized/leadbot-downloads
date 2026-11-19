"""Actual existing Team route candidate, simulated queue and Telegram only."""
import ast
import asyncio
import hashlib
import json
from pathlib import Path
import re
import time
from types import SimpleNamespace
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


class NativeTeamReceipt258Tests(unittest.TestCase):
    def setUp(self):
        text = (ROOT / 'integrations/telegram-team/native-agent-tg258.txt').read_text()
        self.calls = []
        self.result = 701
        self.remap = {}
        self.groups = {'-100123': {'title': 'Авито-Чаты', 'forum': True}}
        self.ns = dict(json=json, re=re, time=time, hashlib=hashlib, JSON_H={'Content-Type':'application/json'},
            _s3_json=lambda *a:self.groups, _tg_old_copies=lambda c:self.remap,
            _agent_job=self.job)
        exec(compile(text, 'actual-native-agent-tg258', 'exec'), self.ns)
        self.body = dict(chat='-100123', text='1234567 - С76 МНЧ', reply_to=71,
                         conv=str(uuid.uuid4()), native_receipt=True, native_intent=str(uuid.uuid4()))

    def job(self, iam, kind, args, wait):
        self.calls.append((kind,args,wait))
        return self.result, ''

    def invoke(self, changes=None):
        body = dict(self.body, **(changes or {}))
        result = self.ns['_agent_tg']('tg_send', {'body':json.dumps(body)}, {}, 'synthetic-iam', 'synthetic', 'brain')
        return result, json.loads(result['body']) if result['statusCode']==200 else None

    def test_native_receipt_binds_actual_queue_result_target_topic_and_exact_text(self):
        response, result = self.invoke()
        self.assertEqual(response['statusCode'],200)
        self.assertEqual(result['message_id'],701)
        self.assertEqual(result['native_intent'],self.body['native_intent'])
        self.assertEqual(result['chat_id'],'-100123');self.assertEqual(result['reply_to'],71)
        self.assertEqual(result['text_sha256'],hashlib.sha256(self.body['text'].encode()).hexdigest())
        self.assertEqual(len(self.calls),1)

    def test_old_group_remap_reports_actual_recipient_instead_of_claiming_requested_group(self):
        self.groups['-123'] = {'title':'Авито-Чаты'};self.remap={'-123':'-100123'}
        _, result = self.invoke({'chat':'-123'})
        self.assertEqual(self.calls[0][1]['chat'],'-100123');self.assertEqual(result['chat_id'],'-100123')

    def test_non_positive_bool_missing_and_string_message_ids_are_not_delivery(self):
        for value in [None,True,False,0,-1,'701']:
            with self.subTest(value=value):
                self.result=value;response,_=self.invoke();self.assertEqual(response['statusCode'],503)

    def test_native_invalid_body_stops_before_queue(self):
        for change in [dict(native_receipt=1),dict(native_intent='not-uuid'),dict(reply_to=True),
                       dict(reply_to=0),dict(chat='me'),dict(text=' '+self.body['text']),dict(photos=[])]:
            with self.subTest(change=change):
                response,_=self.invoke(change);self.assertEqual(response['statusCode'],400)
        self.assertEqual(self.calls,[])

    def test_regular_existing_send_response_shape_remains_unchanged(self):
        body={k:v for k,v in self.body.items() if not k.startswith('native_')}
        r=self.ns['_agent_tg']('tg_send',{'body':json.dumps(body)}, {},'synthetic','synthetic','brain')
        self.assertEqual(json.loads(r['body']),dict(ok=True,message_id=701))

    def test_actual_agent_send_method_supplies_the_independent_message_id(self):
        source=(ROOT/'tools/telegram-agent/tg_agent.py').read_text();tree=ast.parse(source)
        agent=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Agent')
        method=next(n for n in agent.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='do')
        isolated=ast.Module(body=[ast.ClassDef(name='AgentSubset',bases=[],keywords=[],body=[method],decorator_list=[])],type_ignores=[])
        ast.fix_missing_locations(isolated);ns={};exec(compile(isolated,'actual-agent-do258','exec'),ns)
        calls=[]
        async def sent(peer,text,**kwargs):calls.append((peer,text,kwargs));return SimpleNamespace(id=987)
        obj=ns['AgentSubset']();obj.client=SimpleNamespace(send_message=sent);obj.group=lambda cid:{'peer':cid,'title':'Synthetic service group'}
        ns['log']=lambda *args:None
        result=asyncio.run(obj.do({'kind':'send','args':{'chat':'-100123','text':self.body['text'],'reply_to':71}}))
        self.assertEqual(result,987);self.assertEqual(calls[0][2]['reply_to'],71)

    def test_candidate_function_still_contains_the_original_regular_branch(self):
        old=(ROOT/'test-artifacts/current-pilot/latest-turn257/deployed-team-selected-source257.txt').read_text()
        before=next(n for n in ast.parse(old).body if isinstance(n,ast.FunctionDef) and n.name=='_agent_tg')
        after=ast.parse((ROOT/'integrations/telegram-team/native-agent-tg258.txt').read_text()).body[0]
        # Existing statements remain in order; additions add validation and a
        # native-only receipt, rather than replacing the old queue mechanism.
        old_dump=[ast.dump(n,include_attributes=False) for n in before.body]
        new_dump=[ast.dump(n,include_attributes=False) for n in after.body]
        index=iter(new_dump)
        self.assertTrue(all(any(candidate==value for candidate in index) for value in old_dump))


if __name__=='__main__':unittest.main()
