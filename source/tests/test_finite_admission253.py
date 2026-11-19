"""Finite admission failures remain closed and identify the failed control."""
import copy
import json
import unittest
from unittest.mock import patch
import test_research_vision214 as vision_fixture
from research_jobs import JobError
from research_publication import PublicationError


class FiniteAdmission253Tests(unittest.TestCase):
    def setUp(self):
        self.f=vision_fixture.VisionBridge214Tests('test_denial_never_activates_visual_observations')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.service=self.f.service

    def assert_stop(self,result,code):
        value,status=result
        self.assertEqual(status,403)
        self.assertEqual(value['control_reason'],code)
        self.assertEqual(value['reply'],'')
        self.assertFalse(value['auto_enabled'])
        self.assertEqual(self.f.requests,[])
        self.assertEqual(self.f.work,[])

    def admit(self):
        return self.service.admit(self.f.app,self.f.body,max_calls=2,seconds=300)

    def test_missing_grant_has_its_own_typed_reason_without_a_call(self):
        self.assert_stop(self.f.call('research_start'),'finite_admission_missing')

    def test_expired_exact_grant_is_not_reported_as_a_missing_one(self):
        self.admit();now=self.service.jobs.clock()
        self.service.jobs.clock=lambda:now+301
        self.assert_stop(self.f.call('research_start'),'finite_admission_expired')

    def test_changed_pixels_report_binding_field_names_without_regranting(self):
        self.admit()
        self.service.native_context.pixels += b'\x00'
        self.assert_stop(self.f.call('research_start'),'finite_admission_changed')
        with self.f.app.store.connect()as db:
            raw=db.execute("SELECT payload FROM workflow_audit WHERE kind='research_control_stopped' ORDER BY id DESC LIMIT 1").fetchone()[0]
        detail=json.loads(raw)
        self.assertEqual(detail['changed_binding_fields'],['task'])
        self.assertNotIn('binding',detail)

    def test_submit_checks_changed_exact_binding_inside_the_original_transaction(self):
        grant=self.admit();binding=self.service._context(self.f.app,self.f.body)[0]
        binding['task']='0'*64
        with self.assertRaises(JobError)as caught:self.service.jobs.submit(binding,grant)
        self.assertEqual(caught.exception.check,'finite_admission_changed')
        with self.service.jobs.connect()as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_unavailable_source_hold_has_a_safe_reason_and_no_committed_job(self):
        self.admit()
        with patch.object(self.service.jobs.holds,'reserve',side_effect=PublicationError('synthetic private detail')):
            result=self.f.call('research_start')
        self.assert_stop(result,'source_hold_invalid')
        self.assertNotIn('synthetic private detail',json.dumps(result))
        with self.service.jobs.connect()as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
            self.assertIsNone(db.execute('SELECT job FROM grants').fetchone()[0])

    def test_hold_io_failure_is_typed_without_exposing_the_private_path(self):
        self.admit()
        with patch.object(self.service.jobs.holds,'reserve',side_effect=PermissionError('synthetic private path')):
            result=self.f.call('research_start')
        self.assert_stop(result,'source_hold_invalid')
        with self.f.app.store.connect()as db:
            raw=db.execute("SELECT payload FROM workflow_audit WHERE kind='research_control_stopped' ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(json.loads(raw)['source_hold_failure'],'io')
        self.assertNotIn('synthetic private path',raw)

    def test_another_owner_grant_does_not_reveal_changed_fields_or_grant_authority(self):
        binding=self.service._context(self.f.app,self.f.body)[0]
        other=copy.deepcopy(binding);other.update(owner='another-owner',task='0'*64)
        self.service.jobs.admit(other,max_calls=2,seconds=300)
        error=self.service.jobs.missing_admission_error(binding)
        self.assertEqual(error.check,'finite_admission_missing')
        self.assertEqual(error.changed_fields,())
        self.assertEqual(self.f.requests,[])


if __name__=='__main__':unittest.main()
