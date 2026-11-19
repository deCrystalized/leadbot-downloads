"""Progress describes observations, never model approval or action authority."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_research_jobs203 as fixture
import test_research_bridge203 as bridge_fixture
import research_proposals
from assistant_store import Store
from extension_assistant import Assistant
from test_assistant import context, message


class Progress248Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.DurableResearchTests();self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def running(self):
        with self.f.jobs.connect()as db:
            db.execute("UPDATE jobs SET state='running' WHERE id=?",(self.f.job,))

    def test_queue_without_provider_is_not_described_as_model_work(self):
        status=self.f.jobs.status('owner',self.f.job)
        self.assertEqual(status['progress'],dict(stage='queued',elapsed_seconds=0))
        self.assertEqual(status['calls_spent'],0)
        self.assertFalse(status['can_send_or_create'])
        self.assertEqual(self.f.calls,[])

    def test_context_preparation_has_real_elapsed_time_without_a_model_call(self):
        self.running();self.f.now+=21
        value=self.f.jobs.status('owner',self.f.job)
        self.assertEqual(value['progress'],dict(stage='preparing_context',elapsed_seconds=21))
        self.assertEqual(value['deadline'],1300)
        self.assertEqual(value['calls_spent'],0)

    def test_provider_roles_are_visible_but_received_raw_is_not_approval(self):
        self.running();seen=[];raw=[]
        def provider(payload,timeout):
            seen.append(self.f.jobs.status('owner',self.f.job)['progress']['stage'])
            return self.f.request(payload,timeout)
        def after_raw(path):
            status=self.f.jobs.status('owner',self.f.job)
            raw.append(status['progress']['stage'])
            self.assertFalse(status['steps'][-1]['acknowledged'])
            self.assertFalse(status['can_send_or_create'])
        request=self.f.jobs.requester(self.f.job,self.f.binding,fresh=lambda:self.f.current,
                                     request=provider,after_raw=after_raw)
        request(self.f.payload(),120);self.f.now+=80
        request(self.f.payload('review'),120)
        self.assertEqual(seen,['generating','reviewing'])
        self.assertEqual(raw,['validating','validating'])
        status=self.f.jobs.status('owner',self.f.job)
        self.assertEqual(status['calls_spent'],2)
        self.assertEqual(status['deadline'],1300)

    def test_ready_stage_does_not_grant_send_and_other_owner_cannot_read_progress(self):
        from research_jobs import JobError
        with self.f.jobs.connect()as db:
            db.execute("UPDATE jobs SET state='accepted' WHERE id=?",(self.f.job,))
        status=self.f.jobs.status('owner',self.f.job)
        self.assertEqual(status['progress']['stage'],'ready')
        self.assertFalse(status['can_send_or_create'])
        with self.assertRaises(JobError):self.f.jobs.status('other',self.f.job)

    def test_unknown_or_backward_time_is_not_reported_as_zero(self):
        self.f.now-=1
        self.assertIsNone(self.f.jobs.status('owner',self.f.job)['progress']['elapsed_seconds'])


class StopOrigin248Tests(unittest.TestCase):
    def test_browser_stop_reason_is_bounded_unverified_and_changes_no_stop_authority(self):
        for supplied,expected in [('panel_closed','panel_closed'),('user_disconnect','user_disconnect'),
                                  ('arbitrary-secret-value','unreported'),(None,'unreported')]:
            with (self.subTest(supplied=supplied),tempfile.TemporaryDirectory()as tmp,
                  patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='owner',LEADBOT_PERSONAL_OPERATOR_ID='george')):
                app=Assistant(Store(Path(tmp)/'db'))
                body=dict(owner='owner',browser_session='browser:tab:248',operator_id='george')
                start,code=app.handle(dict(body,action='personal_start'))
                self.assertEqual(code,200);self.assertTrue(start['active'])
                result,code=app.handle(dict(body,action='personal_stop',stop_reason=supplied))
                self.assertEqual(code,200);self.assertFalse(result['active'])
                with app.store.connect()as db:
                    raw=db.execute("SELECT payload FROM workflow_audit WHERE kind='session' ORDER BY id DESC LIMIT 1").fetchone()[0]
                event=json.loads(raw)
                self.assertEqual(event['stop_reason'],expected)
                self.assertEqual(event['stop_reason_source'],'browser_assertion_unverified')
                self.assertNotIn('arbitrary-secret-value',raw)


class PublicProgress248Tests(unittest.TestCase):
    def test_authenticated_status_exposes_only_typed_progress_without_reserving_an_extra_call(self):
        f=bridge_fixture.ResearchBridgeTests();f.setUp();self.addCleanup(f.doCleanups)
        f.service.admit(f.app,f.body,max_calls=2,seconds=300)
        out,code=f.call('research_start')
        self.assertEqual(code,200)
        before=f.service.jobs.status('owner',out['research_job_id'])
        value,code=f.call('research_status',research_job_id=out['research_job_id'])
        self.assertEqual(code,200)
        self.assertEqual(value['progress'],before['progress'])
        self.assertEqual(set(value['progress']),{'stage','elapsed_seconds'})
        self.assertEqual(before['calls_spent'],0)
        self.assertEqual(f.requests,[])
        self.assertFalse(value['can_send_or_create'])


class OrdinaryPrice248Tests(unittest.TestCase):
    def test_first_wardrobe_price_answer_can_pass_finalize_without_human_or_template(self):
        with tempfile.TemporaryDirectory()as tmp,patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='owner'):
            app=Assistant(Store(Path(tmp)/'db'))
            ctx=context([message('Здравствуйте, скажите пожалуйста какая цена за сборку шкафа будет?',mid='price')],
                        dir='mnc',city='Чита',itemTitle='Мастер на час',accountTitle='Мастер на час')
            prepared,code=app.handle(dict(owner='owner',action='preview',ctx=ctx,wording_mode='neural_review'))
            self.assertEqual(code,200)
            scope='assistant:'+__import__('assistant_store').digest('owner')
            _,payload=app.store.request(scope,prepared['request_id'])
            reply='Здравствуйте! Точную стоимость скажу после осмотра. Схема или инструкция сборки есть?'
            candidate=dict(reply=reply,needs_operator=False,context_review=dict(
                last_intent='Узнать стоимость сборки шкафа.',latest_client_meaning='Клиент спрашивает, сколько будет стоить сборка шкафа.',
                selected_step_fits=True,evidence_ids=['price'],note='Схема ещё не указана; точная цена обсуждается на месте.'))
            result=app.finalize(scope,dict(request_id=prepared['request_id'],revision=prepared['revision'],candidate=candidate),
                                research_proposal=research_proposals.build(payload))
            self.assertEqual(result['validation'],[])
            self.assertEqual(result['reply'],reply)
            self.assertFalse(result['needs_operator'])
            self.assertEqual(result['response_source'],'model')
            self.assertFalse(result['auto_enabled'])
