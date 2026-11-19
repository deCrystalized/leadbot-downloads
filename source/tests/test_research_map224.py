"""Exact map epochs are data bindings, never a substitute for software identity."""
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import assistant_policy as policy
import research_workflow as workflow
import test_research_bridge203 as fixture


class ResearchMap224Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ResearchBridgeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.brain=Path(self.f.tmp.name)/'private-brain'
        shutil.copytree(Path(workflow.__file__).parent,self.brain,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for module,name in ((workflow,'research_workflow.py'),(policy,'assistant_policy.py')):
            p=patch.object(module,'__file__',str(self.brain/name));p.start();self.addCleanup(p.stop)
        self.map=self.brain/'filial_zones.json'

    def change_map(self):
        data=json.loads(self.map.read_text());data['снято']='isolated-test-new-map-epoch'
        self.map.write_text(json.dumps(data,ensure_ascii=False))

    def fresh(self):
        f=self.f
        out,code=f.app.handle(dict(owner='owner',ctx=f.ctx,action='preview',wording_mode='neural_review',_trusted_research_profile='sol_only'))
        self.assertEqual(code,200,out);self.assertTrue(out.get('pending_model'),out)
        f.body.update(request_id=out['request_id'],revision=out['revision']);return out

    def test_software_identity_survives_a_map_only_change_but_exact_map_binding_does_not(self):
        before=self.f.service.code_version;self.change_map()
        self.assertEqual(self.f.service._runtime_version(),before)
        with self.assertRaises(workflow.PendingSourceChanged):self.f.service._context(self.f.app,self.f.body)
        self.assertEqual(self.f.requests,[])

    def test_unsubmitted_old_preview_retires_without_provider_then_fresh_preview_binds_new_map(self):
        f=self.f;old=f.prepared['request_id'];self.change_map()
        out,code=f.call('research_status');self.assertEqual(code,200,out);self.assertTrue(out.get('refresh_preview'),out)
        fresh=self.fresh();self.assertNotEqual(fresh['request_id'],old)
        binding,current,_,_=f.service._context(f.app,f.body)
        self.assertEqual(binding['map'],current['map_version']);self.assertEqual(f.requests,[])
        with f.service.jobs.connect()as db:self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_real_software_edit_still_stops_even_a_fresh_preview(self):
        p=self.brain/'research_pipeline.py';p.write_text(p.read_text()+'\n# isolated software edit\n')
        with self.assertRaises(workflow.JobError)as caught:self.f.service._context(self.f.app,self.f.body)
        self.assertEqual(caught.exception.check,'runtime_or_profile_changed');self.assertEqual(self.f.requests,[])

    def test_map_change_during_context_preparation_cannot_be_admitted(self):
        f=self.f;original=f.service.corpus_factory
        def changing():self.change_map();return original()
        with patch.object(f.service,'corpus_factory',side_effect=changing):
            with self.assertRaises(workflow.PendingSourceChanged):f.service._context(f.app,f.body)
        self.assertEqual(f.requests,[])

    def test_map_change_after_durable_grant_keeps_original_attempt_closed(self):
        f=self.f;f.service.admit(f.app,f.body,max_calls=4,seconds=300)
        out,code=f.call('research_start');self.assertEqual(code,200,out);job=out['research_job_id']
        self.change_map();f.work.pop(0)()
        status=f.service.jobs.status('owner',job)
        self.assertNotIn(status['state'],('accepted','awaiting_root'));self.assertEqual(f.requests,[])

    def test_reply_preview_cache_identity_changes_with_exact_map_bytes(self):
        f=self.f
        f.app.store.release_dialog(f.scope,f.ctx['convId'],f.prepared['request_id'])
        before=self.fresh();f.app.store.release_dialog(f.scope,f.ctx['convId'],before['request_id'])
        self.change_map();after=self.fresh();self.assertNotEqual(before['request_id'],after['request_id'])
        _,payload=f.app.store.request(f.scope,after['request_id'])
        self.assertEqual(payload['research_map_sha256'],f.service._map_version());self.assertEqual(f.requests,[])

    def test_map_change_during_preview_cannot_stage_its_old_decision(self):
        f=self.f;f.app.store.release_dialog(f.scope,f.ctx['convId'],f.prepared['request_id'])
        original=f.app.experience_context
        def changing(*args,**kwargs):
            result=original(*args,**kwargs);self.change_map();return result
        with patch.object(f.app,'experience_context',side_effect=changing):
            out,code=f.app.handle(dict(owner='owner',ctx=f.ctx,action='preview',wording_mode='neural_review',_trusted_research_profile='sol_only'))
        self.assertFalse(out['ok']);self.assertEqual(code,400);self.assertEqual(f.requests,[])

    def test_old_map_draft_cannot_be_finished_even_after_a_previous_context_check(self):
        f=self.f;f.app.store.release_dialog(f.scope,f.ctx['convId'],f.prepared['request_id'])
        self.fresh();_,payload=f.app.store.request(f.scope,f.body['request_id']);self.change_map()
        with self.assertRaises(ValueError):f.app.finish(f.scope,payload)
        self.assertEqual(f.requests,[])

    def test_new_geometry_cannot_be_called_active_while_old_geometry_is_cached(self):
        data=json.loads(self.map.read_text());data['areas'][0]['name']+=' isolated new content'
        self.map.write_text(json.dumps(data,ensure_ascii=False))
        with self.assertRaises(workflow.JobError)as caught:self.f.service._context(self.f.app,self.f.body)
        self.assertEqual(caught.exception.check,'map_reload_required');self.assertEqual(self.f.requests,[])

    def test_new_preview_cannot_bypass_changed_map_content_reload_guard(self):
        f=self.f;f.app.store.release_dialog(f.scope,f.ctx['convId'],f.prepared['request_id'])
        data=json.loads(self.map.read_text());data['карты']['kp']='isolated-new-layer'
        self.map.write_text(json.dumps(data,ensure_ascii=False))
        out,code=f.app.handle(dict(owner='owner',ctx=f.ctx,action='preview',wording_mode='neural_review',_trusted_research_profile='sol_only'))
        self.assertEqual(code,400,out);self.assertFalse(out['ok']);self.assertEqual(f.requests,[])
