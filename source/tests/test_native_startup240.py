"""Trusted native views, shared durable attempts and real private root control."""
import copy
import os
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import assistant_policy as policy
import auto_simulator231 as simulation
import native_execution
import native_execution_protocol as wire
import research_runtime
import test_owner_auto241 as browser_fixture
from native_execution import NativeApplications
from research_control import Controller
from research_startup import HTTPStartup, configure_http


def attach_run(case, base):
    case.run_id = str(uuid.uuid4())
    case.generation, case.mode, case.live = 1, 'auto', True
    def authority(run_id, generation, actor):
        if (not case.live or run_id != case.run_id or generation != case.generation
                or actor['operator_id'] != simulation.ACTOR):
            raise ValueError('Synthetic native run revoked')
        return dict(actor, run_id=run_id, generation=generation, mode=case.mode,
                    versions=[policy.VERSION, base.code_version, base._map_version(), base.corpus_factory().initial])
    base.native_context.client.run_authority = authority


def body(case, app, ctx):
    return dict(owner=app.research.native_authority.owner, ctx=ctx,
        native_run=dict(run_id=case.run_id, generation=case.generation, operator_id=simulation.ACTOR))


class NativeStartup240Tests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{},clear=False);env.start();self.addCleanup(env.stop)
        self.sim=simulation.Simulation();self.addCleanup(self.sim.tmp.cleanup)
        self.base=self.sim.service
        self.base.owner_auto_enabled=True
        self.base.auto_session_call_limit=12
        attach_run(self,self.base)
        self.apps=NativeApplications(self.sim.app.store,self.base)
        self.app=self.apps(simulation.PRINCIPAL)
        self.ctx=self.sim.add(str(uuid.uuid4()),'Нужно повесить полку.')
        self.body=body(self,self.app,self.ctx)

    def call(self,action,**extra):
        return self.app.handle(dict(self.body,action=action,**extra))

    def preview(self,mode='neural_auto'):
        out,code=self.call('preview',wording_mode=mode,_trusted_research_profile='sol_only')
        self.assertEqual(code,200,out);self.assertTrue(out.get('pending_model'),out)
        self.body.update(request_id=out['request_id'],revision=out['revision'])
        return out

    def workers(self):
        while self.sim.work:self.sim.work.pop(0)()

    def test_native_namespace_executes_shared_cycle_and_does_not_relax_browser_owner(self):
        self.assertNotEqual(self.body['owner'],simulation.OWNER)
        out,code=self.sim.app.handle(dict(self.body,action='preview'))
        self.assertEqual(code,403,out)
        self.preview();out,code=self.call('research_start');self.assertEqual(code,200,out)
        self.body['research_job_id']=out['research_job_id'];self.workers()
        final,code=self.call('research_finalize');self.assertEqual(code,200,final)
        self.assertTrue(final.get('draft_id'),final);self.assertEqual(final['validation'],[])
        self.assertEqual(len(self.sim.requests),2)
        self.assertEqual(self.app.research.jobs.path,self.base.jobs.path)
        self.assertEqual(self.app.research.observers._entries,{})

    def test_principals_are_process_scoped_and_cannot_supply_another_owner(self):
        other=self.apps(str(uuid.uuid4()))
        self.assertIs(self.apps(simulation.PRINCIPAL),self.app)
        self.assertNotEqual(other.research.native_authority.owner,self.body['owner'])
        bad=dict(self.body,owner=other.research.native_authority.owner,action='preview')
        out,code=self.app.handle(bad)
        self.assertEqual(code,403,out);self.assertEqual(self.sim.requests,[])
        self.assertIs(self.app.research.request,self.base.request)
        self.assertIs(self.app.research.native_context,self.base.native_context)
        self.assertEqual(self.app.research.profile,self.base.profile)

    def test_manual_rehearsal_control_sees_shared_database_as_one_job(self):
        self.mode='rehearsal';self.preview('neural_review')
        pending,code=self.call('research_start');self.assertEqual(code,200,pending)
        self.assertTrue(pending['pending_admission'])
        control=Controller(lambda:[self.base]+list(self.apps.services()))
        rows=control.handle(dict(op='pending'))['pending']
        self.assertEqual(len(rows),1)
        control.handle(dict(op='arm',bindings=[rows[0]['binding_hash']],max_calls=4,seconds=600))
        control.handle(dict(op='admit',binding_hash=rows[0]['binding_hash'],max_calls=4,seconds=300))
        started,code=self.call('research_start');self.assertEqual(code,200,started)
        self.body['research_job_id']=started['research_job_id'];self.workers()
        job=self.app.research.jobs.status(self.body['owner'],started['research_job_id'])
        self.assertEqual(job['state'],'awaiting_root')
        listing=control.handle(dict(op='jobs',owner=self.body['owner']))['jobs']
        self.assertEqual([r['job']for r in listing],[job['job_id']])
        control.handle(dict(op='decide',owner=self.body['owner'],job=job['job_id'],
                            result_sha256=job['result_sha256'],accepted=True,reviewer='unit-root'))
        final,code=self.call('research_finalize');self.assertEqual(code,200,final)
        self.assertTrue(final.get('draft_id'),final)
        self.assertEqual(len(self.sim.requests),2)

    def test_root_stop_does_not_duplicate_shared_job_events(self):
        self.preview();started,code=self.call('research_start');self.assertEqual(code,200,started)
        control=Controller(lambda:[self.base]+list(self.apps.services()))
        control.handle(dict(op='stop',owner=self.body['owner']))
        job=started['research_job_id']
        with self.base.jobs.connect()as db:
            count=db.execute("SELECT count(*)FROM events WHERE job=? AND event='series_stopped'",(job,)).fetchone()[0]
        self.assertEqual(count,1)
        self.workers();self.assertEqual(self.sim.requests,[])

    def test_native_registry_requires_actual_dependencies_and_unchanged_runtime(self):
        with self.assertRaises(ValueError):NativeApplications(self.sim.app.store,self.app.research)
        with self.assertRaises(ValueError):self.apps('arbitrary-principal')
        old=self.base.code_version;self.base.code_version='changed-runtime'
        with self.assertRaises(ValueError):self.apps(simulation.PRINCIPAL)
        self.base.code_version=old
        self.assertEqual(self.sim.requests,[])

    def test_explicit_startup_flag_constructs_registry_but_no_run_key_or_calls(self):
        with patch.object(research_runtime,'_factory',None),patch.object(research_runtime,'_services',{}),\
                patch.object(native_execution,'_gateway',None),patch.dict(os.environ,{
                    'LEADBOT_ASSISTANT_DB':str(self.sim.root/'startup-assistant.sqlite3')}),\
                patch('operator_identity.key',side_effect=AssertionError('No startup credential read')):
            commands=[]
            settings=HTTPStartup(self.sim.root/'configured',self.sim.root/'missing-api-key',
                self.sim.root/'shared-startup.lock',enabled=True,allowed_cids=('old-a',),
                proposal_enabled=True,native_execution_enabled=True)
            out=configure_http(settings,corpus_factory=self.base.corpus_factory,source_guard=lambda ids:None,
                native_context=self.base.native_context,schedule=self.sim.work.append,native_schedule=commands.append)
            self.assertTrue(out['native_server_run_available'])
            gateway=native_execution._gateway
            self.assertIsInstance(gateway.app_factory,NativeApplications)
            self.assertEqual(gateway.app_factory.services(),())
            with gateway.connect()as db:self.assertEqual(db.execute('SELECT count(*)FROM commands').fetchone()[0],0)
            self.assertEqual(commands,[]);self.assertEqual(self.sim.requests,[])

    def test_bad_native_flag_or_missing_sources_cannot_publish_factory(self):
        settings=HTTPStartup(self.sim.root/'configured',self.sim.root/'key',self.sim.root/'lock',
            enabled=True,allowed_cids=('old-a',),native_execution_enabled=True)
        with self.assertRaises(ValueError):replace(settings,native_execution_enabled=1)
        with self.assertRaises(ValueError):replace(settings,enabled=False)
        with self.assertRaises(ValueError):configure_http(settings,corpus_factory=self.base.corpus_factory,
            source_guard=lambda ids:None,native_context=None)

    def test_explicit_comparative_profile_is_not_silently_replaced_by_gateway(self):
        self.base.profile='sol_astra';self.base.owner_auto_enabled=False;self.mode='rehearsal'
        app=NativeApplications(self.sim.app.store,self.base)(simulation.PRINCIPAL)
        current=app.research.prepare_source(app,body(self,app,self.ctx))
        queue=[];key=b'synthetic-explicit-profile-test-key'
        gateway=native_execution.Gateway(self.sim.root/'profile-commands',key=lambda:key,
            app_factory=lambda principal:app,schedule=queue.append,clock=lambda:1793517000)
        value=dict(v=1,command_id=str(uuid.uuid4()),operation='prepare',principal_id=simulation.PRINCIPAL,
            operator_id=simulation.ACTOR,run_id=self.run_id,generation=self.generation,
            arguments=dict(cid=self.ctx['convId'],source_sha256=current['ctx']['sourceSnapshotSha256'],purpose='reply'))
        raw,headers=wire.request(key,value,now=1793517000)
        self.assertEqual(gateway.handle(raw,{k.lower():v for k,v in headers.items()})[0],202)
        queue.pop(0)()
        with gateway.connect()as db:
            row=db.execute('SELECT state,response FROM commands WHERE id=?',(value['command_id'],)).fetchone()
        self.assertEqual(row['state'],'done')
        response=wire.decode(row['response'],wire.MAX_RESPONSE)
        self.assertTrue(response['data'].get('pending_admission'),response)
        self.assertEqual(app.research.profile,'sol_astra')
        self.assertEqual(self.sim.requests,[])


class CrossTransportAttempt240Tests(unittest.TestCase):
    def setUp(self):
        self.f=browser_fixture.OwnerAuto241Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        attach_run(self,self.f.sim.service)
        self.apps=NativeApplications(self.f.sim.app.store,self.f.sim.service)
        self.app=self.apps(simulation.PRINCIPAL)

    def native_start(self):
        b=body(self,self.app,self.f.ctx)
        out,code=self.app.handle(dict(b,action='preview',wording_mode='neural_auto',_trusted_research_profile='sol_only'))
        self.assertEqual(code,200,out);self.assertTrue(out.get('pending_model'),out)
        self.assertEqual(out['revision'],self.f.body['revision'])
        return self.app.handle(dict(b,action='research_start',request_id=out['request_id'],revision=out['revision']))

    def test_old_browser_failure_is_not_a_new_native_attempt(self):
        self.f.sim.provider_mode='transport';self.f.preview();old,code=self.f.research();self.assertEqual(code,200,old)
        self.f.sim.command(dict(op='run_workers'))
        original=self.f.sim.service.jobs.status(simulation.OWNER,old['research_job_id'])
        self.assertEqual(len(self.f.sim.requests),1)
        out,code=self.native_start();self.assertEqual(code,403,out)
        self.assertEqual(out.get('code'),'research_prior_attempt')
        self.assertEqual(len(self.f.sim.requests),1)
        self.assertEqual(len(self.f.jobs()),1)
        unchanged=self.f.sim.service.jobs.status(simulation.OWNER,old['research_job_id'])
        self.assertEqual(unchanged['deadline'],original['deadline'])
        self.assertEqual(unchanged['calls_spent'],original['calls_spent'])

    def test_reservation_without_grant_id_cannot_be_bypassed_by_native_namespace(self):
        self.f.preview()
        with patch.object(self.f.sim.service.jobs,'admit',side_effect=OSError('Synthetic crash before grant ID')):
            self.f.research()
        with self.f.sim.service.jobs.connect()as db:
            self.assertEqual(db.execute('SELECT count(*)FROM auto_admissions WHERE grant_id IS NULL').fetchone()[0],1)
        out,code=self.native_start();self.assertEqual(code,403,out)
        self.assertEqual(self.f.jobs(),[]);self.assertEqual(self.f.sim.requests,[])

    def test_legacy_manual_admission_with_unknown_purpose_is_not_permission_to_regenerate(self):
        self.f.start(auto=False);self.f.preview('neural_review')
        self.f.sim.service.admit(self.f.sim.app,self.f.body,max_calls=4,seconds=300)
        self.assertEqual(len(self.f.jobs()),1)
        out,code=self.native_start();self.assertEqual(code,403,out)
        self.assertEqual(out.get('code'),'research_prior_attempt')
        self.assertEqual(len(self.f.jobs()),1);self.assertEqual(self.f.sim.requests,[])


if __name__=='__main__':unittest.main()
