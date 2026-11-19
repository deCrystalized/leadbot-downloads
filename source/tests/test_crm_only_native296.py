"""Native CRM-only admission uses trusted configuration, not browser flags."""
import copy
from contextlib import ExitStack
from dataclasses import replace
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import native_execution
import research_runtime
from research_startup import HTTPStartup, configure_http
from research_server import configure_server
from extension_assistant import _parse
import personal_workflow
import test_native_office255 as office
import test_native_startup240 as startup
import test_research_server209 as server


class TrustedCRMOnly296Tests(unittest.TestCase):
    def configured_fixture(self):
        f=startup.NativeStartup240Tests();f.setUp();self.addCleanup(f.doCleanups)
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.object(research_runtime,'_factory',None))
        stack.enter_context(patch.object(research_runtime,'_services',{}))
        stack.enter_context(patch.object(native_execution,'_gateway',None))
        stack.enter_context(patch.dict(os.environ,{'LEADBOT_ASSISTANT_DB':str(f.sim.root/'startup-assistant.sqlite3')}))
        stack.enter_context(patch('operator_identity.key',side_effect=AssertionError('No startup credential read')))
        f.commands=[];f.network=[]
        def forbidden(*args,**kwargs):
            f.network.append('unexpected provider connection')
            raise AssertionError('No model connection in startup proof')
        f.forbidden_connection=forbidden
        f.settings=HTTPStartup(f.sim.root/'configured',f.sim.root/'missing-api-key',f.sim.root/'startup.lock',
            enabled=True,network_enabled=True,allowed_cids=('old-a',),proposal_enabled=True,
            intake_form_enabled=True,owner_auto_enabled=True,native_execution_enabled=True,
            native_actions_enabled=True,native_office_enabled=True,native_notifications_enabled=False,
            native_crm_only_enabled=True)
        return f

    def test_typed_startup_defaults_off_and_rejects_inconsistent_modes(self):
        base=HTTPStartup(Path('/private/jobs'),Path('/private/key'),Path('/private/lock'))
        self.assertFalse(base.native_crm_only_enabled)
        active=replace(base,enabled=True,network_enabled=True,allowed_cids=('authored',),
            owner_auto_enabled=True,native_execution_enabled=True,native_actions_enabled=True,
            intake_form_enabled=True,native_office_enabled=True,native_crm_only_enabled=True)
        for change in (dict(native_crm_only_enabled='true'),dict(native_office_enabled=False),
                       dict(native_notifications_enabled=True),dict(owner_auto_enabled=False)):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(active,**change)

    def test_actual_configure_http_preserves_mode_in_principal_service(self):
        f=self.configured_fixture()
        result=configure_http(f.settings,corpus_factory=f.base.corpus_factory,source_guard=lambda ids:None,
            native_context=f.base.native_context,schedule=f.sim.work.append,native_schedule=f.commands.append,
            connection_factory=f.forbidden_connection)
        self.assertTrue(result['configured'])
        gateway=native_execution._gateway
        self.assertTrue(gateway.app_factory.base.native_crm_only_enabled)
        self.assertTrue(gateway.app_factory(startup.simulation.PRINCIPAL).research.native_crm_only_enabled)
        self.assertFalse(gateway.notifications_enabled)
        self.assertEqual(f.network,[]);self.assertEqual(f.commands,[]);self.assertEqual(f.sim.requests,[])

    def test_private_json_configuration_passes_explicit_mode_to_actual_factory(self):
        f=self.configured_fixture()
        fixture=server.ServerSourceTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.config.update(network_enabled=True,owner_auto_enabled=True,native_execution_enabled=True,
            native_actions_enabled=True,intake_form_enabled=True,native_office_enabled=True,
            native_crm_only_enabled=True,native_notifications_enabled=False)
        fixture.write(fixture.path,fixture.config)
        # These are two separate owned startup configurations, not two live
        # gateways in the same serving process. Preserve the existing guard.
        with patch.object(native_execution,'_gateway',None):
            result=configure_server(fixture.path,native_context=f.base.native_context,
                schedule=f.sim.work.append,native_schedule=f.commands.append,connection_factory=f.forbidden_connection)
            self.assertTrue(result['configured'])
            self.assertTrue(native_execution._gateway.app_factory.base.native_crm_only_enabled)
            self.assertFalse(native_execution._gateway.notifications_enabled)
        self.assertEqual(f.network,[]);self.assertEqual(f.sim.requests,[])


class NativeCRMOnly296Tests(unittest.TestCase):
    def make(self,crm_only=True):
        original=startup.NativeStartup240Tests.setUp
        def configured(f):
            original(f)
            # Trusted fixture configuration before any form preview or job.
            f.base.intake_form_enabled=f.app.research.intake_form_enabled=True
            f.base.native_crm_only_enabled=f.app.research.native_crm_only_enabled=crm_only
        b=office.NativeOfficeRPC255Tests()
        with patch.object(startup.NativeStartup240Tests,'setUp',configured):b.setUp()
        self.addCleanup(b.doCleanups)
        b.value['followup']=dict(required=False,telegram_ready=False,mode='crm_only',code='С1')
        return b

    def test_accepted_form_mode_is_bound_and_native_grant_consumes_once_without_telegram(self):
        b=self.make()
        self.assertEqual(b.accepted['completion_mode'],'crm_only')
        calls=len(b.f.sim.requests)
        grant,status=b.execute(b.packet());self.assertEqual(status,200,grant)
        self.assertTrue(grant['ok']);self.assertFalse(grant['execution_allowed'])
        consume=b.packet('consume_office',grant_id=grant['grant_id'])
        started,status=b.execute(consume);self.assertEqual(status,200,started)
        self.assertTrue(started['execution_allowed']);self.assertFalse(started['customer_effect_confirmed'])
        again,status=b.execute(b.packet('consume_office',grant_id=grant['grant_id']))
        self.assertFalse(again['execution_allowed'])
        self.assertEqual(len(b.grants()),1);self.assertEqual(b.grants()[0]['id'],grant['grant_id'])
        self.assertEqual(len(b.f.sim.requests),calls)
        self.assertFalse(b.gateway.notifications_enabled)

    def test_legacy_server_refuses_browser_selected_crm_only_even_with_real_form(self):
        b=self.make(False)
        self.assertEqual(b.accepted['completion_mode'],'telegram')
        out,status=b.execute(b.packet());self.assertEqual(status,409,out)
        self.assertFalse(out['ok']);self.assertEqual(b.grants(),[])

    def test_changing_server_mode_does_not_reuse_a_form_accepted_in_the_other_mode(self):
        b=self.make(False)
        b.f.app.research.native_crm_only_enabled=True
        out,status=b.execute(b.packet());self.assertGreaterEqual(status,400,out)
        self.assertFalse(out['ok']);self.assertEqual(b.grants(),[])

    def test_crm_only_requires_an_explicit_matching_nonnotification_snapshot(self):
        b=self.make()
        for followup in ({},{'mode':'crm_only','required':True,'telegram_ready':False},
                         {'mode':'crm_only','required':False,'telegram_ready':True},
                         {'mode':'telegram','required':False,'telegram_ready':False}):
            value=copy.deepcopy(b.value);value['followup']=followup
            out,status=b.execute(b.packet(value=value))
            with self.subTest(followup=followup):
                self.assertEqual(status,409,out);self.assertFalse(out['ok']);self.assertEqual(b.grants(),[])

    def test_all_crm_bases_must_still_be_checked_and_no_live_order_may_be_bypassed(self):
        b=self.make()
        for field,value in [('unchecked',[{'dir':'mnc'}]),('found',[{'id':'123'}]),('live',True)]:
            proposal=copy.deepcopy(b.value);proposal['prep'][field]=value
            out,status=b.execute(b.packet(value=proposal))
            with self.subTest(field=field):
                self.assertEqual(status,409,out);self.assertFalse(out['ok']);self.assertEqual(b.grants(),[])

    def test_fresh_client_source_change_stops_the_old_proposal_without_new_grant(self):
        b=self.make()
        b.f.ctx['messages'][-1]['body']+=' Не согласен оформлять заявку.'
        b.f.sim.sync(b.f.ctx['convId'])
        out,status=b.execute(b.packet());self.assertGreaterEqual(status,400,out)
        self.assertFalse(out['ok']);self.assertEqual(b.grants(),[])

    def test_browser_personal_check_does_not_inherit_native_crm_only_authority(self):
        b=self.make()
        prepared=b.f.app.research.prepare_source(b.f.app,b.f.body)
        _,messages,known,revision=_parse(prepared['ctx'])
        result=personal_workflow.check_crm(messages,known,dict(prepared['ctx'],workflowRevision=revision),b.value)
        self.assertFalse(result['ready']);self.assertIn('отписка',' '.join(result['reasons']))


if __name__=='__main__':unittest.main()
