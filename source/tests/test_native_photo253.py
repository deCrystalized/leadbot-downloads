"""Native visual source/launch boundaries; synthetic pixels and no API/socket."""
import copy
import hashlib
import unittest

import test_native_startup240 as fixture
import test_research_media204 as media


class NativePhoto253Tests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.NativeStartup240Tests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.ctx['messages'][0]['attachments'] = [dict(id='photo253', type='image')]
        self.case.sim.sync(self.case.ctx['convId'])
        self.reads = 0
        self.mutation = None

        def image(*args):
            self.reads += 1
            if self.mutation:
                self.mutation()
            return dict(data=media.PNG, mime='image/png', sha256=hashlib.sha256(media.PNG).hexdigest())

        self.case.base.native_context.client.image = image
        self.case.preview()

    def test_stop_during_last_original_read_is_rechecked_before_context_returns(self):
        self.mutation = lambda: setattr(self.case, 'live', False)
        with self.assertRaises(ValueError):
            self.case.app.research._context(self.case.app, self.case.body)
        self.assertGreater(self.reads, 0)
        self.assertEqual(self.case.sim.requests, [])

    def test_same_original_and_full_launch_remain_bound_without_model_call(self):
        binding, current, payload, _ = self.case.app.research._context(
            self.case.app, self.case.body)
        self.assertEqual(payload['research_purpose'], 'visual_observation_v1')
        self.assertEqual(current['media']['images'][0]['sha256'], hashlib.sha256(media.PNG).hexdigest())
        self.assertEqual(binding['profile'], 'sol_only')
        self.assertEqual(self.case.sim.requests, [])

    def test_generation_change_during_original_read_is_not_adopted(self):
        self.mutation = lambda: setattr(self.case, 'generation', self.case.generation + 1)
        with self.assertRaises(ValueError):
            self.case.app.research._context(self.case.app, self.case.body)
        self.assertGreater(self.reads, 0)
        self.assertEqual(self.case.sim.requests, [])

    def test_rehearsal_switch_during_original_read_revokes_original_auto_binding(self):
        self.mutation = lambda: setattr(self.case, 'mode', 'rehearsal')
        with self.assertRaises(ValueError):
            self.case.app.research._context(self.case.app, self.case.body)
        self.assertGreater(self.reads, 0)
        self.assertEqual(self.case.sim.requests, [])

    def test_explicit_visual_prepare_refuses_a_reply_plan_before_start(self):
        from unittest.mock import patch
        import native_execution
        import native_execution_protocol as wire
        import uuid

        service = self.case.app.research
        prepared = service.prepare_source(self.case.app, self.case.body)
        gateway = native_execution.Gateway(self.case.sim.root / 'visual-commands',
            key=lambda:b'synthetic-visual-command-test-key-253',
            app_factory=self.case.apps, schedule=lambda _:None)
        command = wire.check(dict(v=1,command_id=str(uuid.uuid4()),operation='prepare',
            principal_id=fixture.simulation.PRINCIPAL,operator_id=fixture.simulation.ACTOR,
            run_id=self.case.run_id,generation=self.case.generation,
            arguments=dict(cid=self.case.ctx['convId'],
                source_sha256=prepared['ctx']['sourceSnapshotSha256'],purpose='visual_observation_v1')))
        with patch.object(self.case.app,'handle',return_value=(dict(ok=True,pending_model=True),200)) as handle:
            result,status=gateway._dispatch(command)
        self.assertEqual(status,409)
        self.assertEqual(result['code'],'native_visual_plan_changed')
        handle.assert_called_once()
        self.assertEqual(self.case.sim.requests, [])

    def test_visual_prepare_protocol_is_bounded_and_does_not_grant_an_effect(self):
        import native_execution_protocol as wire
        import uuid
        value = dict(v=1,command_id=str(uuid.uuid4()),operation='prepare',
            principal_id=fixture.simulation.PRINCIPAL,operator_id=fixture.simulation.ACTOR,
            run_id=self.case.run_id,generation=self.case.generation,
            arguments=dict(cid=self.case.ctx['convId'],source_sha256='a'*64,
                           purpose='visual_observation_v1'))
        self.assertEqual(wire.check(value), value)
        for field in ('reply','execution_allowed','url'):
            bad=copy.deepcopy(value);bad['arguments'][field]='injected'
            with self.assertRaises(wire.ExecutionError):wire.check(bad)
        bad=copy.deepcopy(value);bad['operation']='consume_action'
        with self.assertRaises(wire.ExecutionError):wire.check(bad)
        self.assertEqual(self.case.sim.requests, [])


if __name__ == '__main__':
    unittest.main()
