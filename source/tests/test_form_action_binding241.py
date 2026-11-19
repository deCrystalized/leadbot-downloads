"""Actual browser action route must bind its accepted form, not a prior UI check."""
import copy
import unittest

from assistant_store import digest
import test_owner_auto241 as fixture


class FormActionBinding241Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.OwnerAuto241Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;cid='accepted-form-action241'
        f.sim.command(dict(op='ready',cid=cid));f.ctx=f.sim.contexts[cid];f.body['ctx']=f.ctx
        f.sim.service.intake_form_enabled=True
        prepared,code=f.sim.app.handle(dict(f.body,action='form_preview',wording_mode='neural_auto',
                                           _trusted_research_profile='sol_only'))
        self.assertEqual(code,200,prepared);self.assertTrue(prepared.get('pending_model'),prepared)
        f.body.update(request_id=prepared['request_id'],revision=prepared['revision'])
        started,code=f.research();self.assertEqual(code,200,started)
        f.sim.command(dict(op='run_workers'))
        accepted,code=f.research('research_finalize',started['research_job_id'])
        self.assertEqual(code,200,accepted);self.assertTrue(accepted.get('intake_form_ready'),accepted)
        self.proposal=f.sim.command(dict(op='proposal',cid=cid))
        self.proposal['lead'].update(copy.deepcopy(accepted['form_extraction']['lead']))
        self.proposal['lead']['service_comment']='https://lead.test/chats/'+cid
        self.proposal['form_reference']=accepted['form_reference']

    def authorize(self,proposal):
        f=self.f;f.sim.identity();f.body.update(f.sim.last_identity)
        planned,code=f.sim.app.handle(dict(f.body,action='personal_plan',mine_count=0))
        self.assertEqual(code,200,planned);self.assertEqual(planned['step'],'prepare_crm',planned)
        op=dict(kind='create_crm',revision=planned['revision'],operation_id=planned['operation_id'],
                proposal=proposal,snapshot_hash=digest(proposal))
        return f.sim.app.handle(dict(f.body,action='personal_authorize',mine_count=0,operation=op))

    def test_current_accepted_form_gets_one_grant_without_any_customer_action(self):
        out,code=self.authorize(self.proposal)
        self.assertEqual(code,200,out);self.assertTrue(out['execution_allowed'])
        self.assertEqual(len(self.f.sim.requests),2)

    def test_invalid_reference_cannot_skip_separate_crm_check(self):
        proposal=copy.deepcopy(self.proposal);proposal['form_reference']='f'*64
        out,code=self.authorize(proposal)
        self.assertEqual(code,403,out);self.assertFalse(out['execution_allowed'])

    def test_changed_work_cannot_skip_separate_crm_check(self):
        proposal=copy.deepcopy(self.proposal);proposal['lead']['problem']='Другой непроверенный ремонт'
        out,code=self.authorize(proposal)
        self.assertEqual(code,403,out);self.assertFalse(out['execution_allowed'])


if __name__=='__main__':unittest.main()
