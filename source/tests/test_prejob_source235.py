"""Causal pre-admission races; actual policy/native binding, no provider network."""
import copy
import os
import unittest
from unittest.mock import patch

import auto_simulator231 as fixture
import assistant_policy
from assistant_store import digest


class PreJobSource235Tests(unittest.TestCase):
    def setUp(self):
        environment=patch.dict(os.environ,{},clear=False)
        environment.start()
        self.addCleanup(environment.stop)
        self.sim=fixture.Simulation()
        self.addCleanup(self.sim.tmp.cleanup)
        self.ctx=self.sim.add('prejob235')
        self.sim.identity()
        self.body=dict(owner=fixture.OWNER,ctx=self.ctx,**self.sim.last_identity)
        start,code=self.sim.app.handle(dict(self.body,action='personal_start'))
        self.assertEqual(code,200)
        out,code=self.sim.app.handle(dict(self.body,action='preview',wording_mode='neural_review',
                                        _trusted_research_profile='sol_only'))
        self.assertEqual(code,200)
        self.assertTrue(out['pending_model'])
        self.body.update(request_id=out['request_id'],revision=out['revision'])
        self.scope='assistant:'+digest(fixture.OWNER)

    def change(self,*,assigned=False):
        if assigned:
            self.ctx.update(assigneeId='33333333-3333-4333-8333-333333333333',conversationStatus='in_progress')
            self.ctx['messages'].append(dict(id='claim-system',direction='system',sender_type='system',
                                            body='Диалог принят другим сотрудником'))
        else:
            self.ctx['messages'].append(dict(id='clarified',direction='in',sender_type='client',
                                            body='Уточнение: полка на кухне.'))
        self.sim.sync('prejob235')

    def start(self,action='research_start'):
        self.sim.identity();self.body.update(self.sim.last_identity)
        return self.sim.app.handle(dict(self.body,action=action))

    def refreshed_without_calls(self,out,code):
        self.assertEqual(code,200,out)
        self.assertTrue(out['refresh_preview'])
        self.assertEqual(out['research_state'],'source_changed')
        self.assertFalse(out['needs_operator'])
        self.assertFalse(out['can_send_or_create'])
        self.assertEqual(self.sim.requests,[])
        self.assertEqual(self.sim.work,[])
        status,old=self.sim.app.store.request(self.scope,self.body['request_id'])
        self.assertEqual(status,'done')
        self.assertEqual(old['reply'],'')
        self.assertNotIn('model_task',old)

    def test_other_staff_assignment_between_preview_and_first_start_retires_old_request(self):
        self.change(assigned=True)
        self.refreshed_without_calls(*self.start())

    def test_new_client_message_before_admission_requires_a_new_preview_and_no_implicit_call(self):
        self.change()
        self.refreshed_without_calls(*self.start('research_status'))
        body={k:v for k,v in self.body.items()if k not in('request_id','revision')}
        fresh,code=self.sim.app.handle(dict(body,action='preview',wording_mode='neural_review',
                                           _trusted_research_profile='sol_only'))
        self.assertEqual(code,200)
        self.assertNotEqual(fresh['request_id'],self.body['request_id'])
        self.assertTrue(fresh['pending_model'])
        self.assertEqual(self.sim.requests,[])

    def test_an_unsubmitted_exact_grant_is_expired_and_cannot_cover_the_new_source(self):
        grant=self.sim.service.admit(self.sim.app,self.body,max_calls=4,seconds=300)
        self.change()
        self.refreshed_without_calls(*self.start())
        with self.sim.service.jobs.connect()as db:
            row=db.execute('select deadline,job from grants where id=?',(grant,)).fetchone()
        self.assertLessEqual(row['deadline'],self.sim.service.jobs.clock())
        self.assertIsNone(row['job'])

    def test_a_manual_hold_is_not_hidden_by_a_source_refresh(self):
        self.sim.app.store.observe(self.scope,'prejob235',self.body['revision'],takeover=True)
        self.change()
        out,code=self.start()
        self.assertEqual(code,403)
        self.assertEqual(out['code'],'research_stopped')
        self.assertNotIn('refresh_preview',out)

    def test_primary_version_change_still_stops_even_when_the_source_changes(self):
        self.change()
        with patch.object(assistant_policy,'VERSION','different-primary'):
            out,code=self.start()
        self.assertEqual(code,403)
        self.assertNotIn('refresh_preview',out)

    def test_runtime_change_still_stops_even_when_the_source_changes(self):
        self.change()
        with patch.object(self.sim.service,'_runtime_version',return_value='different-runtime'):
            out,code=self.start()
        self.assertEqual(code,403)
        self.assertNotIn('refresh_preview',out)

    def test_a_known_durable_job_is_stopped_without_automatic_refresh_or_regeneration(self):
        self.sim.service.admit(self.sim.app,self.body,max_calls=4,seconds=300)
        out,code=self.start();self.assertEqual(code,200)
        job=out['research_job_id']
        self.change()
        out,code=self.sim.app.handle(dict(self.body,action='research_status',research_job_id=job))
        self.assertEqual(code,403)
        self.assertEqual(out['code'],'research_stopped')
        self.assertNotIn('refresh_preview',out)
        self.assertEqual(self.sim.requests,[])
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,job)['state'],'stopped')

    def test_browser_forgery_does_not_create_an_authoritative_revision_refresh(self):
        forged=copy.deepcopy(self.body)
        forged['ctx']['messages'].append(dict(id='forged',direction='in',sender_type='client',body='Другая работа'))
        out,code=self.sim.app.handle(dict(forged,action='research_start'))
        self.assertEqual(code,200)
        self.assertTrue(out['pending_admission'])
        self.assertNotIn('refresh_preview',out)
        self.assertEqual(self.sim.requests,[])

    def test_a_changed_prepared_actor_is_not_hidden_by_source_refresh(self):
        status,prepared=self.sim.app.store.request(self.scope,self.body['request_id'])
        prepared['operator_binding']=[fixture.PRINCIPAL,'33333333-3333-4333-8333-333333333333']
        self.sim.app.store.stage(self.scope,self.body['request_id'],prepared)
        self.change()
        out,code=self.start()
        self.assertEqual(code,403)
        self.assertNotIn('refresh_preview',out)

    def test_a_changed_native_client_group_does_not_refresh_under_the_old_client(self):
        original=self.sim.service.native_context.client.header
        def another_client(cid,actor):
            return dict(original(cid,actor),client_group='another-client-group')
        self.change()
        with patch.object(self.sim.service.native_context.client,'header',side_effect=another_client):
            out,code=self.start()
        self.assertEqual(code,403)
        self.assertNotIn('refresh_preview',out)

    def test_concurrent_submission_is_stopped_instead_of_becoming_a_refresh(self):
        binding=self.sim.service._context(self.sim.app,self.body)[0]
        grant=self.sim.service.admit(self.sim.app,self.body,max_calls=4,seconds=300)
        original=self.sim.service._retire_changed_unsubmitted
        submitted=[]
        def competing_submit(app,body,prepared):
            submitted.append(self.sim.service.jobs.submit(binding,grant)['job_id'])
            return original(app,body,prepared)
        self.change()
        with patch.object(self.sim.service,'_retire_changed_unsubmitted',side_effect=competing_submit):
            out,code=self.start()
        self.assertEqual(code,403,out)
        self.assertEqual(out['failure_stage'],'concurrent_admission')
        self.assertNotIn('refresh_preview',out)
        self.assertEqual(self.sim.service.jobs.status(fixture.OWNER,submitted[0])['state'],'stopped')
        self.assertEqual(self.sim.requests,[])

    def test_browser_route_change_is_not_an_authenticated_source_refresh(self):
        for change_message in (False,True):
            with self.subTest(authoritative_message_also_changed=change_message):
                forged=copy.deepcopy(self.body)
                forged['ctx'].update(dir='kp',dirBasis='operator')
                if change_message:self.change()
                out,code=self.sim.app.handle(dict(forged,action='research_start'))
                self.assertEqual(code,403,out)
                self.assertNotIn('refresh_preview',out)
                self.assertEqual(self.sim.requests,[])

    def test_a_no_longer_active_auto_session_cannot_be_hidden_by_native_source_refresh(self):
        # A stored auto preview can outlive the mode being switched off.
        # This isolates that private stored state; it never enables auto.
        status,prepared=self.sim.app.store.request(self.scope,self.body['request_id'])
        prepared['wording_mode']='neural_auto'
        self.sim.app.store.stage(self.scope,self.body['request_id'],prepared)
        self.change()
        out,code=self.start()
        self.assertEqual(code,403,out)
        self.assertNotIn('refresh_preview',out)
        self.assertEqual(out['code'],'research_stopped')
        self.assertEqual(self.sim.requests,[])
