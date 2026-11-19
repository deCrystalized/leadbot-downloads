"""Native office authority reuses the accepted form and permanent create slot.

No browser, CRM, Telegram or actual model transport is exercised here.
"""
import copy
import hashlib
import hmac
from pathlib import Path
from dataclasses import replace
import unittest
import uuid
from unittest.mock import patch

import native_execution
import native_execution_protocol as wire
import test_native_startup240 as fixture
import test_workflow as crm_fixture
import test_native_execution239 as ingress_fixture
import personal_workflow
from assistant_store import digest
from native_workflow import NativeWorkflow
from research_startup import HTTPStartup


def proposal():
    return dict(revision='revision255',form_reference='a'*64,dir='kp',
        lead=dict(comment='Источник-привязанный комментарий'),prep={},territory={},
        sel={},readiness='ready',flags=[],allowLive=False,followup={})


def command(op='reserve_office', value=None):
    value=proposal()if value is None else value
    args=dict(cid=str(uuid.uuid4()),source_sha256='b'*64,kind='create_crm',
        operation_id='create255',revision=value['revision'],proposal=value,
        snapshot_hash=wire.sha(wire.encode(value)))
    if op=='consume_office':args['grant_id']='c'*32
    return dict(v=1,command_id=str(uuid.uuid4()),operation=op,principal_id=str(uuid.uuid4()),
        operator_id=str(uuid.uuid4()),run_id=str(uuid.uuid4()),generation=1,arguments=args)


class NativeOfficeProtocol255Tests(unittest.TestCase):
    def test_exact_office_packet_is_distinct_from_old_claim_reply_tunnel(self):
        value=command()
        self.assertEqual(wire.check(value),value)
        for op in ('reserve_action','consume_action'):
            bad=copy.deepcopy(value);bad['operation']=op
            if op=='consume_action':bad['arguments']['grant_id']='c'*32
            with self.subTest(op=op),self.assertRaises(ValueError):wire.check(bad)

    def test_office_signature_and_announcement_bind_the_exact_operation(self):
        key=b'synthetic-office-protocol-key-255'
        value=command();raw,headers=wire.request(key,value,now=1793532000)
        lower={k.lower():v for k,v in headers.items()}
        self.assertEqual(wire.verify(key,raw,lower,now=1793532000)[0],value)
        for marker in (None,'0','other'):
            changed=dict(lower)
            if marker is None:changed.pop(wire.OFFICE_HEADER)
            else:changed[wire.OFFICE_HEADER]=marker
            with self.subTest(marker=marker),self.assertRaises(ValueError):
                wire.verify(key,raw,changed,now=1793532000)
        legacy=copy.deepcopy(value);legacy['operation']='inspect'
        legacy['arguments']={k:value['arguments'][k]for k in ('cid','source_sha256')}
        raw,headers=wire.request(key,legacy,now=1793532000)
        lower={k.lower():v for k,v in headers.items()};lower[wire.OFFICE_HEADER]='1'
        with self.assertRaises(ValueError):wire.verify(key,raw,lower,now=1793532000)

    def test_changed_snapshot_or_foreign_revision_and_caller_fields_are_rejected(self):
        base=command()
        for name,change in [
            ('snapshot',lambda a:a.update(snapshot_hash='c'*64)),
            ('revision',lambda a:a.update(revision='foreign')),
            ('callerflag',lambda a:a.update(execution_allowed=True)),
            ('reply',lambda a:a.update(reply='Не является ответом клиенту')),
            ('otherkind',lambda a:a.update(kind='notify_created')),
        ]:
            bad=copy.deepcopy(base);change(bad['arguments'])
            with self.subTest(name=name),self.assertRaises(ValueError):wire.check(bad)

    def test_credential_keys_are_rejected_even_when_nested_and_hash_matches(self):
        for key in ('Authorization','api_key','apiKey','access-token','identity_proof','nonce','JWT'):
            value=proposal();value['lead']['attributes']=[{key:'synthetic-only'}]
            with self.subTest(key=key),self.assertRaises(ValueError):wire.check(command(value=value))

    def test_no_history_tunnel_live_bypass_or_unready_proposal(self):
        for field,value in [('advertiserCtx',{'messages':[]}),('allowLive',True),
                            ('readiness','review'),('flags',['review']),('form_reference','not-accepted')]:
            other=proposal();other[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):wire.check(command(value=other))

    def test_office_directory_budget_does_not_raise_old_reference_budget(self):
        value=proposal();value['prep']['appl']=[{'id':'1','text':'x'*20000}]
        packet=command(value=value);raw,headers=wire.request(b'synthetic-office-envelope-key-255',packet,now=1793532000)
        self.assertGreater(len(raw),wire.MAX_REQUEST)
        self.assertLessEqual(len(raw),wire.MAX_OFFICE_REQUEST)
        self.assertEqual(headers['X-LB-Exec-Office'],'1')
        self.assertEqual(wire.request_limit(dict(operation='inspect')),16000)
        value['prep']['appl'][0]['text']='x'*wire.MAX_PROPOSAL
        with self.assertRaises(ValueError):wire.check(command(value=value))

    def test_nonfinite_or_excessive_nesting_cannot_enter_office_journal(self):
        value=proposal();branch=value['lead']
        for _ in range(25):branch['more']={};branch=branch['more']
        with self.assertRaises(ValueError):wire.check(command(value=value))
        bad=command();bad['arguments']['proposal']['lead']['price']=float('nan')
        with self.assertRaises(ValueError):wire.check(bad)


class NativeOfficeFraming255Tests(unittest.TestCase):
    def test_actual_handler_forwards_large_office_bytes_and_explicit_announcement(self):
        value=proposal();value['prep']['appl']=[dict(id='1',text='x'*20000)]
        raw=wire.encode(command(value=value))
        h=ingress_fixture.NativeHTTPIngress239Tests().handler(raw)
        h.headers['X-LB-Exec-Office']='1'
        with patch.object(native_execution,'serve',return_value=(202,b'{"ok":true}',{}))as serve:
            h.do_POST()
        expected={k:'synthetic-framing-only'for k in wire.AUTH_HEADERS};expected[wire.OFFICE_HEADER]='1'
        serve.assert_called_once_with(raw,expected)
        self.assertEqual(h.codes,[202]);self.assertEqual(h.rfile.tell(),len(raw))

    def test_unannounced_oversized_or_duplicate_office_header_does_not_read_body(self):
        for markers in ([],['wrong'],['1','1']):
            h=ingress_fixture.NativeHTTPIngress239Tests().handler(b'x'*16001)
            for marker in markers:h.headers['X-LB-Exec-Office']=marker
            with patch.object(native_execution,'serve')as serve:h.do_POST()
            serve.assert_not_called();self.assertEqual(h.rfile.tell(),0)
            self.assertIn(h.codes[0],(400,413))


class NativeOfficeStartup255Tests(unittest.TestCase):
    def test_office_flag_is_separate_and_requires_native_actions_and_accepted_forms(self):
        base=HTTPStartup(Path('/private/jobs'),Path('/private/key'),Path('/private/lock'))
        self.assertFalse(base.native_office_enabled)
        active=dict(enabled=True,network_enabled=True,allowed_cids=('synthetic',),
            owner_auto_enabled=True,native_execution_enabled=True,native_actions_enabled=True,
            intake_form_enabled=True,native_office_enabled=True)
        self.assertTrue(replace(base,**active).native_office_enabled)
        for changed in [dict(native_office_enabled='true'),dict(native_actions_enabled=False),
                        dict(native_execution_enabled=False),dict(owner_auto_enabled=False),
                        dict(intake_form_enabled=False)]:
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                replace(base,**dict(active,**changed))


class NativeOfficeRPC255Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.NativeStartup240Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f
        f.base.intake_form_enabled=True;f.app.research.intake_form_enabled=True
        f.ctx=f.sim.command(dict(op='ready',cid=f.ctx['convId']))
        f.ctx.pop('adIdentity',None);f.sim.sync(f.ctx['convId'])
        # A native caller carries only the CID. Browser-only display/time
        # hints cannot enter a form revision which the private RPC will use.
        f.body=fixture.body(f,f.app,dict(convId=f.ctx['convId']))
        prepared,code=f.app.handle(dict(f.body,action='form_preview',wording_mode='neural_auto',
                                       _trusted_research_profile='sol_only'))
        self.assertEqual(code,200,prepared);self.assertTrue(prepared.get('pending_model'),prepared)
        f.body.update(request_id=prepared['request_id'],revision=prepared['revision'])
        started,code=f.call('research_start');self.assertEqual(code,200,started)
        f.body['research_job_id']=started['research_job_id'];f.workers()
        self.accepted,code=f.call('research_finalize')
        self.assertEqual(code,200,self.accepted)
        self.assertTrue(self.accepted.get('intake_form_ready'),self.accepted)
        self.plan=NativeWorkflow(f.app,enabled=True).plan(f.body)
        self.assertEqual(self.plan['step'],'prepare_crm',self.plan)
        self.value=crm_fixture.WorkflowTests().proposal(f.ctx)
        self.value['revision']=self.plan['revision']
        self.value['form_reference']=self.accepted['form_reference']
        self.value['lead'].update(copy.deepcopy(self.accepted['form_extraction']['lead']))
        self.value['lead']['service_comment']='https://lead.test/chats/'+f.ctx['convId']
        self.key=b'synthetic-private-native-office-key'
        self.queue=[];self.gateway=self.gateway_instance()

    def gateway_instance(self, enabled=True):
        return native_execution.Gateway(self.f.sim.root/'office255',key=lambda:self.key,
            app_factory=lambda _:self.f.app,clock=lambda:1793532000,
            schedule=self.queue.append,actions_enabled=True,office_enabled=enabled)

    def packet(self,op='reserve_office',value=None,**extra):
        value=copy.deepcopy(self.value if value is None else value)
        source=self.f.app.research.prepare_source(self.f.app,self.f.body)['ctx']['sourceSnapshotSha256']
        return dict(v=1,command_id=str(uuid.uuid4()),operation=op,
            principal_id=fixture.simulation.PRINCIPAL,operator_id=fixture.simulation.ACTOR,
            run_id=self.f.run_id,generation=self.f.generation,
            arguments=dict(cid=self.f.ctx['convId'],source_sha256=source,kind='create_crm',
                operation_id=self.plan['operation_id'],revision=self.plan['revision'],
                proposal=value,snapshot_hash=digest(value),**extra))

    def send(self,packet,gateway=None):
        raw,headers=wire.request(self.key,packet,now=1793532000)
        code,result,signed=(gateway or self.gateway).handle(raw,{k.lower():v for k,v in headers.items()})
        self.assertTrue(signed)
        out=wire.verify_response(self.key,result,headers['X-LB-Exec-Nonce'],code,signed['X-LB-Exec-Signature'])
        return out,code

    def execute(self,packet,gateway=None):
        out,code=self.send(packet,gateway);self.assertEqual(code,202,out)
        while self.queue:self.queue.pop(0)()
        with self.gateway.connect()as db:
            row=db.execute('SELECT *FROM commands WHERE id=?',(packet['command_id'],)).fetchone()
        self.assertEqual(row['state'],'done')
        return wire.decode(row['response'],wire.MAX_RESPONSE)['data'],row['status']

    def grants(self):
        with self.f.app.store.connect()as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='native_workflow_grants'").fetchone()
            return list(db.execute('SELECT *FROM native_workflow_grants'))if exists else []

    def test_actual_accepted_form_gets_one_short_create_permit_not_a_created_order(self):
        grant,code=self.execute(self.packet())
        self.assertEqual(code,200,grant);self.assertFalse(grant['execution_allowed'])
        started,code=self.execute(self.packet('consume_office',grant_id=grant['grant_id']))
        self.assertEqual(code,200,started);self.assertTrue(started['execution_allowed'])
        self.assertFalse(started['customer_effect_confirmed'])
        self.assertEqual(started['kind'],'create_crm')
        self.assertEqual(started['form_reference'],self.accepted['form_reference'])
        self.assertEqual(started['snapshot_hash'],digest(self.value))
        self.assertEqual(self.grants()[0]['state'],'started')
        self.assertEqual(len(self.f.sim.requests),2)
        self.assertFalse(self.f.ctx.get('crmRequestId'))

    def test_office_default_disabled_does_not_read_source_or_reserve(self):
        gateway=self.gateway_instance(False)
        packet=self.packet()
        gateway.app_factory=lambda _:(_ for _ in ()).throw(AssertionError('Disabled office must not read source'))
        out,code=self.execute(packet,gateway)
        self.assertEqual(code,409);self.assertEqual(out['code'],'native_office_disabled')
        self.assertEqual(self.grants(),[]);self.assertEqual(len(self.f.sim.requests),2)

    def test_original_form_reference_and_work_are_verified_again_before_create(self):
        for kind in ('reference','work'):
            value=copy.deepcopy(self.value)
            if kind=='reference':value['form_reference']='f'*64
            else:
                value['lead']['problem']='Другой непроверенный ремонт'
                value['lead']['comment']+='\nДругой непроверенный ремонт'
            out,code=self.execute(self.packet(value=value))
            self.assertEqual(code,409,out);self.assertFalse(out['execution_allowed'])
        self.assertEqual(self.grants(),[]);self.assertEqual(len(self.f.sim.requests),2)

    def test_existing_crm_and_territory_guards_cannot_be_replaced_by_form_acceptance(self):
        for section,key in [('prep','live'),('territory','approval')]:
            value=copy.deepcopy(self.value);value[section][key]=True
            out,code=self.execute(self.packet(value=value))
            self.assertEqual(code,409,out);self.assertEqual(out['code'],'crm_gate')
        self.assertEqual(self.grants(),[])

    def test_archived_original_consume_is_observation_not_another_permission(self):
        grant,_=self.execute(self.packet())
        original=self.packet('consume_office',grant_id=grant['grant_id'])
        self.execute(original)
        observed,code=self.send(original)
        self.assertEqual(code,200);self.assertTrue(observed['requires_current_validation'])
        self.assertFalse(observed['can_send_or_create']);self.assertNotIn('execution_allowed',observed)
        twice,code=self.execute(self.packet('consume_office',grant_id=grant['grant_id']))
        self.assertEqual(code,409,twice);self.assertFalse(twice['execution_allowed'])
        again,code=self.execute(self.packet())
        self.assertEqual(code,409,again);self.assertEqual(len(self.grants()),1)
        self.assertEqual(self.grants()[0]['state'],'started')

    def test_stop_or_new_client_source_before_consume_keeps_grant_unstarted(self):
        grant,_=self.execute(self.packet())
        original=self.packet('consume_office',grant_id=grant['grant_id'])
        self.f.ctx['messages'][0]['body']+=' Подождите, сейчас уточню.'
        self.f.sim.sync(self.f.ctx['convId'])
        self.send(original)
        while self.queue:self.queue.pop(0)()
        self.assertEqual(self.grants()[0]['state'],'reserved')
        with self.gateway.connect()as db:
            self.assertEqual(db.execute('SELECT state FROM commands WHERE id=?',
                (original['command_id'],)).fetchone()[0],'uncertain')
        self.f.live=False
        observed,code=self.send(original)
        self.assertFalse(observed['can_send_or_create']);self.assertNotIn('execution_allowed',observed)
        self.assertEqual(self.grants()[0]['state'],'reserved')

    def test_expired_create_reservation_is_not_renewed_and_browser_slot_is_permanent(self):
        grant,_=self.execute(self.packet())
        with self.f.app.store.connect()as db:
            db.execute('UPDATE native_workflow_grants SET expires=0 WHERE id=?',(grant['grant_id'],))
        out,code=self.execute(self.packet())
        self.assertEqual(code,409,out);self.assertEqual(len(self.grants()),1)
        out,code=self.execute(self.packet('consume_office',grant_id=grant['grant_id']))
        self.assertEqual(code,409,out);self.assertFalse(out['execution_allowed'])
        self.assertEqual(self.grants()[0]['expires'],0)

    def test_prior_browser_create_once_also_blocks_office_without_new_grant(self):
        with self.f.app.store.connect()as db:
            personal_workflow.grant_schema(db)
            db.execute('INSERT INTO workflow_grants(scope,chat,slot,sid,revision,expires,epoch,reviewed)VALUES(?,?,?,?,?,?,?,?)',
                ('old-browser',self.f.ctx['convId'],'create_once','old',self.plan['revision'],0,1,0))
        out,code=self.execute(self.packet())
        self.assertEqual(code,409,out);self.assertEqual(out['code'],'prior_browser_action')
        self.assertEqual(self.grants(),[])

    def test_credential_reflection_or_duplicate_json_is_rejected_before_command_journal(self):
        value=copy.deepcopy(self.value);value['lead']['comment']+=self.key.decode()
        packet=self.packet(value=value);raw,headers=wire.request(self.key,packet,now=1793532000)
        code,out,signed=self.gateway.handle(raw,{k.lower():v for k,v in headers.items()})
        self.assertEqual(code,403);self.assertEqual(signed,{})
        self.assertFalse(wire.decode(out,wire.MAX_RESPONSE)['ok'])
        raw=b'{"v":1,"v":1}'
        stamp,nonce='1793532000','n'*32
        signed=hmac.new(self.key,wire._message(raw,stamp,nonce),hashlib.sha256).hexdigest()
        code,_,_=self.gateway.handle(raw,dict(zip(wire.AUTH_HEADERS,(stamp,nonce,signed)),
                                            **{wire.OFFICE_HEADER:'1'}))
        self.assertEqual(code,403)
        with self.gateway.connect()as db:
            self.assertEqual(db.execute('SELECT count(*)FROM commands').fetchone()[0],0)
        self.assertEqual(self.queue,[]);self.assertEqual(self.grants(),[])

