"""Real Assistant route with a session change during policy planning."""
import unittest
from unittest.mock import patch

import personal_workflow
from assistant_store import digest
import test_workflow as fixtures


class ActionSession252Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WorkflowTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.ctx=self.f.ctx();self.ctx['assigneeId']=''
        self.operation=self.f.operation(self.ctx,'claim')

    def assert_no_old_grant(self,change):
        f=self.f
        original=personal_workflow.plan
        def planned_then_changed(*args,**kwargs):
            result=original(*args,**kwargs)
            change()
            return result
        with f.auto():
            with patch.object(personal_workflow,'plan',side_effect=planned_then_changed):
                out=f.call('personal_authorize',ctx=self.ctx,operation=self.operation)
            self.assertFalse(out['ok'],out)
            self.assertFalse(out['execution_allowed'])
            with f.app.store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM workflow_grants').fetchone()[0],0)

    def test_stop_during_plan_cannot_issue_an_Auto_action_permit(self):
        self.assert_no_old_grant(lambda:self.f.call('personal_stop'))

    def test_reconnect_during_plan_cannot_inherit_the_prior_Auto_permit(self):
        self.assert_no_old_grant(lambda:self.f.call('personal_start'))

    def test_review_switch_during_plan_cannot_leave_an_Auto_permit(self):
        self.assert_no_old_grant(lambda:self.f.call('personal_mode',execution_mode='review'))

    def test_expiry_during_plan_cannot_leave_an_Auto_permit(self):
        def expire():
            with self.f.app.store.connect() as db:
                db.execute('UPDATE personal_sessions SET expires=0 WHERE scope=?',(digest('owner'),))
        self.assert_no_old_grant(expire)

    def test_final_existing_creation_gate_cannot_use_session_stopped_during_planning(self):
        f=self.f;ctx=f.ctx(ready=True);proposal=f.proposal(ctx);operation=f.operation(ctx,'create_crm',
            proposal=proposal,snapshot_hash=digest(proposal));original=personal_workflow.plan
        def planned_then_stopped(*args,**kwargs):
            result=original(*args,**kwargs);f.call('personal_stop');return result
        with f.auto():
            permit=f.call('personal_authorize',ctx=ctx,operation=operation)
            self.assertTrue(permit['execution_allowed'],permit)
            with patch.object(personal_workflow,'plan',side_effect=planned_then_stopped):
                checked=f.call('personal_check_started',ctx=ctx,revision=operation['revision'])
            self.assertFalse(checked['execution_allowed'],checked)
