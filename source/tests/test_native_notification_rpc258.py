"""Actual native office grants/original command journal; loopback is simulated."""
import base64
import copy
import hashlib
import json
import unittest
import uuid
from dataclasses import replace
from unittest.mock import patch

import native_execution
import native_execution_protocol as wire
from native_notification_client import NotificationClient
from research_startup import HTTPStartup
import test_native_office255 as office_fixture
import test_research_server209 as server_fixture


def result_for(p):
    text=p['crm_request_id']+' - '+p['source_code']+' '+{'kp':'КП','bt':'БТ','mnc':'МНЧ'}[p['direction']]
    actual=dict(ok=True,message_id=887,native_intent=p['intent_id'],chat_id='-100123',reply_to=71,
                text_sha256=hashlib.sha256(text.encode()).hexdigest())
    raw=wire.encode(actual)
    return dict(ok=True,telegram_confirmed=True,
        **{k:p[k]for k in ('work_id','crm_request_id','source_sha256','snapshot_hash','form_reference','card_sha256')},
        intent_id=p['intent_id'],chat_id=actual['chat_id'],topic_id=71,message_id=887,
        text_sha256=actual['text_sha256'],original_http=dict(status=200,content_type='application/json',
            sha256=wire.sha(raw),body=base64.b64encode(raw).decode()))


class NativeNotificationRPC258Tests(unittest.TestCase):
    def setUp(self):
        self.base=office_fixture.NativeOfficeRPC255Tests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        b=self.base;b.value['followup']=dict(required=True,telegram_ready=True,code='С76')
        grant,_=b.execute(b.packet())
        self.consume=b.packet('consume_office',grant_id=grant['grant_id']);b.execute(self.consume)
        self.calls=[];self.after_raw=False;self.lost=False;self.plan_hook=None
        def plan(payload,persist):
            if self.plan_hook:self.plan_hook()
            result=dict(ok=True,prepared=True,work_id=payload['work_id'],intent_id=payload['intent_id'],telegram_confirmed=False)
            persist(200,'application/json',wire.encode(result))
            return result
        self.plan=plan
        def notify(payload,persist,send_before):
            self.assertLessEqual(send_before,1793532005)
            self.calls.append(payload);result=result_for(payload)
            if self.lost:raise ValueError('Synthetic possible send lost')
            persist(200,'application/json',wire.encode(result))
            with self.gateway.connect()as db:
                self.assertIsNotNone(db.execute('SELECT raw FROM notifications').fetchone()[0])
            if self.after_raw:raise ValueError('Synthetic crash after raw persistence')
            return result
        self.notify=notify
        self.gateway=self.instance()

    def instance(self,**changes):
        b=self.base
        kwargs=dict(key=lambda:b.key,app_factory=lambda _:b.f.app,clock=lambda:1793532000,
            schedule=b.queue.append,actions_enabled=True,office_enabled=True,
            notifications_enabled=True,notify=self.notify,notification_plan=self.plan)
        kwargs.update(changes)
        return native_execution.Gateway(b.f.sim.root/'office255',**kwargs)

    def packet(self,**changes):
        value={k:v for k,v in self.consume.items()if k!='arguments'}
        value.update(command_id=str(uuid.uuid4()),operation='notify_office')
        old=self.consume['arguments']
        value['arguments']=dict(cid=old['cid'],source_sha256=old['source_sha256'],work_id='a'*64,
            notification_id=str(uuid.uuid4()),create_command_id=self.consume['command_id'],crm_request_id='1234567',
            snapshot_hash=old['snapshot_hash'],form_reference=old['proposal']['form_reference'],
            card_sha256='b'*64,dispatch_before=1793532090)
        value['arguments'].update(changes);return value

    def execute(self,value,gateway=None):
        gateway=gateway or self.gateway
        out,code=self.base.send(value,gateway);self.assertEqual(code,202,out)
        while self.base.queue:self.base.queue.pop(0)()
        with gateway.connect()as db:row=db.execute('SELECT * FROM commands WHERE id=?',(value['command_id'],)).fetchone()
        return row

    def test_exact_consumed_create_uses_existing_source_code_and_one_service_post(self):
        packet=self.packet();row=self.execute(packet)
        self.assertEqual(row['state'],'done');out=wire.decode(row['response'],wire.MAX_RESPONSE)['data']
        self.assertTrue(out['telegram_confirmed']);self.assertEqual(out['crm_request_id'],'1234567')
        self.assertEqual(self.calls[0]['source_code'],'С76');self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.base.f.sim.requests),2) # no additional model steps.
        duplicate=self.execute(self.packet());self.assertEqual(duplicate['state'],'uncertain');self.assertEqual(len(self.calls),1)

    def test_possible_send_unknown_is_not_reissued_after_gateway_restart(self):
        self.lost=True;packet=self.packet();self.assertEqual(self.execute(packet)['state'],'uncertain')
        self.gateway=self.instance();out,code=self.base.send(packet,self.gateway)
        self.assertEqual(code,200);self.assertEqual(out['command_state'],'uncertain');self.assertEqual(len(self.calls),1)

    def test_original_raw_after_crash_recovers_without_a_second_notification_or_key(self):
        self.after_raw=True;packet=self.packet();self.assertEqual(self.execute(packet)['state'],'uncertain')
        self.gateway=self.instance(notify=lambda *a:(_ for _ in ()).throw(AssertionError('No second send')))
        out,code=self.base.send(packet,self.gateway)
        self.assertEqual(code,200);self.assertEqual(out['command_state'],'done')
        self.assertTrue(out['original_result']['data']['telegram_confirmed']);self.assertEqual(len(self.calls),1)

    def test_original_successful_evidence_survives_stop_but_does_not_grant_close(self):
        self.after_raw=True;packet=self.packet();self.execute(packet);self.base.f.live=False
        out,_=self.base.send(packet,self.gateway)
        self.assertTrue(out['source_or_run_not_current']);self.assertTrue(out['original_result']['data']['telegram_confirmed'])
        self.assertFalse(out['can_send_or_create']);self.assertEqual(len(self.calls),1)

    def test_stopped_or_changed_source_never_calls_notification_bridge(self):
        self.base.f.live=False;row=self.execute(self.packet())
        self.assertEqual(row['state'],'uncertain');self.assertEqual(self.calls,[])

    def test_stop_during_route_planning_never_permits_physical_service_send(self):
        self.plan_hook=lambda:setattr(self.base.f,'live',False)
        row=self.execute(self.packet())
        self.assertEqual(row['state'],'uncertain');self.assertEqual(self.calls,[])

    def test_new_client_message_during_route_planning_prevents_service_send(self):
        def changed():
            self.base.f.ctx['messages'][0]['body']+=' Секунду, ещё уточню.'
            self.base.f.sim.sync(self.base.f.ctx['convId'])
        self.plan_hook=changed
        row=self.execute(self.packet())
        self.assertEqual(row['state'],'uncertain');self.assertEqual(self.calls,[])

    def test_broker_success_flag_without_persisted_original_receipt_is_not_delivery(self):
        self.gateway=self.instance(notify=lambda payload,persist,before:result_for(payload))
        row=self.execute(self.packet())
        self.assertEqual(row['state'],'uncertain')

    def test_wrong_original_create_form_or_snapshot_cannot_call_the_broker(self):
        for changes in [dict(create_command_id=str(uuid.uuid4())),dict(form_reference='f'*64),dict(snapshot_hash='f'*64)]:
            with self.subTest(changes=changes):
                self.assertEqual(self.execute(self.packet(**changes))['state'],'uncertain')
        self.assertEqual(self.calls,[])

    def test_expired_notification_does_not_renew_old_CRM_or_model_window(self):
        self.assertEqual(self.execute(self.packet(dispatch_before=1793531999))['state'],'uncertain');self.assertEqual(self.calls,[])

    def test_disabled_notice_does_not_open_app_or_network(self):
        gateway=self.instance(notifications_enabled=False,app_factory=lambda _:(_ for _ in ()).throw(AssertionError('No source read')))
        row=self.execute(self.packet(),gateway);self.assertEqual(row['state'],'done');self.assertEqual(row['status'],409);self.assertEqual(self.calls,[])

    def test_protocol_rejects_browser_booleans_text_targets_and_nonfinite_fields(self):
        for k,v in [('telegram_confirmed',True),('text','invented'),('chat','-100123'),('dispatch_before',float('inf'))]:
            with self.subTest(key=k),self.assertRaises(ValueError):wire.check(self.packet(**{k:v}))

    def test_startup_notification_flag_is_explicit_and_requires_office(self):
        from pathlib import Path
        s=HTTPStartup(Path('/x'),Path('/k'),Path('/l'))
        self.assertFalse(s.native_notifications_enabled)
        with self.assertRaises(ValueError):replace(s,native_notifications_enabled=True)


class NativeNotificationLoopback258Tests(unittest.TestCase):
    def test_disabled_client_does_not_read_token_or_create_connection(self):
        c=NotificationClient(token=lambda:(_ for _ in ()).throw(AssertionError('No key')))
        with self.assertRaises(ValueError):c.prepare({},lambda *a:None)

    def test_raw_is_persisted_before_original_parse_without_retry(self):
        calls=[];saved=[];chunks=[b'not JSON',b'']
        class Response:
            status=200
            def getheader(self,*a):return 'application/json'
            def read(self,n):return chunks.pop(0)
        class Connection:
            def __init__(self,*a,**k):calls.append((a,k))
            def request(self,method,path,**kw):calls.append((method,path))
            def getresponse(self):return Response()
            def close(self):pass
        c=NotificationClient(enabled=True,token=lambda:'synthetic-loopback-token',clock=lambda:1000,connection=Connection)
        with self.assertRaises(ValueError):c.prepare({'dispatch_before':1090},lambda *a:saved.append(a))
        self.assertEqual(saved,[(200,'application/json',b'not JSON')]);self.assertEqual(len(calls),2)

    def test_reflected_service_credential_is_never_persisted(self):
        saved=[];chunks=[b'synthetic-loopback-token',b'']
        class Response:
            status=200
            def getheader(self,*a):return 'application/json'
            def read(self,n):return chunks.pop(0)
        class Connection:
            def __init__(self,*a,**k):pass
            def request(self,*a,**k):pass
            def getresponse(self):return Response()
            def close(self):pass
        c=NotificationClient(enabled=True,token=lambda:'synthetic-loopback-token',clock=lambda:1000,connection=Connection)
        with self.assertRaises(ValueError):c.prepare({'dispatch_before':1090},lambda *a:saved.append(a))
        self.assertEqual(saved,[])


class NativeNotificationFactory258Tests(unittest.TestCase):
    def setUp(self):
        self.f=server_fixture.ServerSourceTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def config(self):
        self.f.config.update(network_enabled=True,owner_auto_enabled=True,native_execution_enabled=True,
            native_actions_enabled=True,intake_form_enabled=True,native_office_enabled=True,
            native_notifications_enabled=True)
        self.f.write(self.f.path,self.f.config)

    def test_file_factory_forwards_both_explicit_office_capabilities_without_key_or_call(self):
        self.config()
        with patch('research_server.configure_http',return_value={'configured':True})as factory:
            server_fixture.configure_server(self.f.path)
        settings=factory.call_args.args[0]
        self.assertTrue(settings.native_office_enabled);self.assertTrue(settings.native_notifications_enabled)
        self.assertFalse(self.f.root.joinpath('absent-key').exists());factory.assert_called_once()

    def test_file_capability_types_are_not_normalized_or_inferred(self):
        self.config()
        for key in ('native_office_enabled','native_notifications_enabled'):
            bad=copy.deepcopy(self.f.config);bad[key]=1;self.f.write(self.f.path,bad)
            with patch('research_server.configure_http')as factory,self.assertRaises(ValueError):
                server_fixture.configure_server(self.f.path)
            factory.assert_not_called()


if __name__=='__main__':unittest.main()
