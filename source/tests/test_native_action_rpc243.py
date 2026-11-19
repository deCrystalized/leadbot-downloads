"""Private source-bound action references, with no actual claim/send transport."""
import copy
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

import native_execution
import native_execution_protocol as wire
import test_native_workflow241 as fixture
from research_startup import HTTPStartup


class NativeActionRPC243Tests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.NativeActionAuthority241Tests();self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.f=self.case.f;self.queue=[];self.key=b'synthetic-private-native-action-key'
        # The old browser fixture supplies a UI-only advertiser name. The
        # private native caller sends only CID/source references; that name
        # must not be imported into its revision or asserted as source data.
        self.f.ctx.pop('adIdentity',None)
        self.gateway=self.gateway_instance(True)

    def gateway_instance(self,enabled):
        return native_execution.Gateway(self.f.sim.root/'action-commands',key=lambda:self.key,
            app_factory=lambda _:self.f.app,schedule=self.queue.append,clock=lambda:1793532000,
            actions_enabled=enabled)

    def command(self,operation,action,**extra):
        source=self.f.app.research.prepare_source(self.f.app,self.f.body)['ctx']['sourceSnapshotSha256']
        return dict(v=1,command_id=str(uuid.uuid4()),operation=operation,
            principal_id=fixture.simulation.PRINCIPAL,operator_id=fixture.simulation.ACTOR,
            run_id=self.f.run_id,generation=self.f.generation,
            arguments=dict(cid=self.f.ctx['convId'],source_sha256=source,**action,**extra))

    def send(self,command,gateway=None):
        raw,headers=wire.request(self.key,command,now=1793532000)
        code,result,signed=(gateway or self.gateway).handle(raw,{k.lower():v for k,v in headers.items()})
        self.assertTrue(signed)
        return wire.verify_response(self.key,result,headers['X-LB-Exec-Nonce'],code,
                                    signed['X-LB-Exec-Signature']),code

    def execute(self,command,gateway=None):
        result,code=self.send(command,gateway)
        self.assertEqual(code,202,result)
        while self.queue:self.queue.pop(0)()
        with self.gateway.connect()as db:
            row=db.execute('SELECT *FROM commands WHERE id=?',(command['command_id'],)).fetchone()
        self.assertEqual(row['state'],'done',dict(row))
        return wire.decode(row['response'],wire.MAX_RESPONSE)['data'],row['status']

    def test_claim_reserve_consume_receipt_has_no_actual_assignment_or_delivery(self):
        action=self.case.operation();reserved,status=self.execute(self.command('reserve_action',action))
        self.assertEqual(status,200,reserved);self.assertFalse(reserved['execution_allowed'])
        started,status=self.execute(self.command('consume_action',action,grant_id=reserved['grant_id']))
        self.assertEqual(status,200,started);self.assertTrue(started['execution_allowed'])
        self.assertFalse(started['customer_effect_confirmed']);self.assertEqual(started['kind'],'claim')
        self.assertEqual(started['source_sha256'],self.command('reserve_action',action)['arguments']['source_sha256'])
        self.assertEqual(started['operation_id'],action['operation_id'])
        self.assertEqual(self.f.ctx['assigneeId'],'');self.assertEqual(self.f.sim.requests,[])
        self.assertEqual(self.case.rows()[0]['state'],'started')

    def test_reply_text_is_only_original_current_native_draft(self):
        action,draft=self.case.reply()
        grant,status=self.execute(self.command('reserve_action',action));self.assertEqual(status,200,grant)
        out,status=self.execute(self.command('consume_action',action,grant_id=grant['grant_id']))
        self.assertEqual(status,200,out);self.assertEqual(out['reply'],draft['reply'])
        self.assertEqual(out['draft_id'],action['draft_id']);self.assertFalse(out['customer_effect_confirmed'])
        self.assertEqual(len(self.f.sim.requests),2)

    def test_archived_consumption_is_observation_not_a_second_execution(self):
        action=self.case.operation();grant,_=self.execute(self.command('reserve_action',action))
        command=self.command('consume_action',action,grant_id=grant['grant_id'])
        self.execute(command)
        observed,code=self.send(command)
        self.assertEqual(code,200,observed);self.assertTrue(observed['requires_current_validation'])
        self.assertFalse(observed['can_send_or_create']);self.assertNotIn('execution_allowed',observed)
        twice,status=self.execute(self.command('consume_action',action,grant_id=grant['grant_id']))
        self.assertEqual(status,409);self.assertFalse(twice['execution_allowed'])
        self.assertEqual(len(self.case.rows()),1)

    def test_gateway_default_capability_and_rehearsal_cannot_mint_action(self):
        action=self.case.operation()
        denied,status=self.execute(self.command('reserve_action',action),self.gateway_instance(False))
        self.assertEqual(status,409);self.assertEqual(denied['code'],'native_actions_disabled')
        self.f.mode='rehearsal'
        denied,status=self.execute(self.command('reserve_action',action))
        self.assertEqual(status,409);self.assertEqual(denied['code'],'native_rehearsal_has_no_action_authority')
        self.assertEqual(self.case.rows(),[])

    def test_stopped_run_before_consume_keeps_reservation_unstarted(self):
        action=self.case.operation();grant,_=self.execute(self.command('reserve_action',action))
        command=self.command('consume_action',action,grant_id=grant['grant_id']);self.f.live=False
        self.send(command)
        while self.queue:self.queue.pop(0)()
        self.assertEqual(self.case.rows()[0]['state'],'reserved');self.assertEqual(self.f.sim.requests,[])

    def test_same_id_client_edit_cannot_consume_old_source(self):
        action=self.case.operation();grant,_=self.execute(self.command('reserve_action',action))
        command=self.command('consume_action',action,grant_id=grant['grant_id'])
        self.f.ctx['messages'][0]['body']='Секунду, уточню.';self.f.sim.sync(self.f.ctx['convId'])
        self.send(command)
        while self.queue:self.queue.pop(0)()
        self.assertEqual(self.case.rows()[0]['state'],'reserved');self.assertEqual(self.f.sim.requests,[])

    def test_protocol_rejects_body_text_credentials_flags_crm_and_followup_tunnel(self):
        action=self.case.operation();base=self.command('reserve_action',action)
        for field,value in [('reply','caller text'),('headers',{}),('api_key','synthetic'),
                            ('actions_enabled',True),('proposal',{}),('draft_id','unneeded')]:
            changed=copy.deepcopy(base);changed['arguments'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):wire.check(changed)
        for kind in ('create_crm','link_crm','notify','close'):
            changed=copy.deepcopy(base);changed['arguments']['kind']=kind
            with self.subTest(kind=kind),self.assertRaises(ValueError):wire.check(changed)
        self.assertEqual(self.case.rows(),[])

    def test_browser_only_advertiser_hint_does_not_become_native_source_authority(self):
        self.f.ctx['adIdentity']='Несверенное имя из панели'
        old_action=self.case.operation()
        denied,status=self.execute(self.command('reserve_action',old_action))
        self.assertEqual(status,409);self.assertEqual(denied['code'],'stale')
        self.assertEqual(self.case.rows(),[])


class NativeActionStartup243Tests(unittest.TestCase):
    def test_trusted_action_startup_flag_needs_explicit_native_execution_and_owner_auto(self):
        base=HTTPStartup(Path('/private/research'),Path('/private/key'),Path('/private/lock'))
        self.assertFalse(base.native_actions_enabled)
        for changes in [dict(native_actions_enabled=True),dict(native_actions_enabled='true'),
                        dict(enabled=True,allowed_cids=('synthetic',),native_execution_enabled=True,
                             native_actions_enabled=True)]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(base,**changes)
        valid=replace(base,enabled=True,network_enabled=True,allowed_cids=('synthetic',),
            native_execution_enabled=True,owner_auto_enabled=True,native_actions_enabled=True)
        self.assertTrue(valid.native_actions_enabled)
