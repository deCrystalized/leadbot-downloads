"""Separate native Run capability from old browser availability; no effects."""
import os
import unittest
from unittest.mock import patch

import test_native_workflow241 as native_fixture
import test_owner_auto241 as browser_fixture
from native_workflow import NativeWorkflow


class NativeBrowserCutover248Tests(unittest.TestCase):
    def setUp(self):
        self.n = native_fixture.NativeActionAuthority241Tests()
        self.n.setUp()
        self.addCleanup(self.n.doCleanups)

    def test_actual_native_run_reserves_and_consumes_with_legacy_browser_auto_off(self):
        n = self.n
        with patch.dict(os.environ, {'LEADBOT_PERSONAL_AUTO_AVAILABLE': '0'}):
            operation = n.operation()
            grant = n.broker.reserve(n.f.body, operation)
            self.assertTrue(grant['ok'], grant)
            result = n.broker.consume(n.f.body, operation, grant['grant_id'])
            self.assertTrue(result['execution_allowed'], result)
            self.assertFalse(result['customer_effect_confirmed'])
            self.assertFalse(n.broker.consume(n.f.body, operation, grant['grant_id'])['ok'])
        self.assertEqual(n.f.sim.requests, [])

    def test_native_default_disabled_owner_disabled_and_stopped_run_still_deny(self):
        n = self.n
        with patch.dict(os.environ, {'LEADBOT_PERSONAL_AUTO_AVAILABLE': '0'}):
            operation = n.operation()
            self.assertFalse(NativeWorkflow(n.f.app).reserve(n.f.body, operation)['ok'])
            n.f.app.research.owner_auto_enabled = False
            self.assertFalse(n.broker.reserve(n.f.body, operation)['ok'])
            n.f.app.research.owner_auto_enabled = True
            grant = n.broker.reserve(n.f.body, operation)
            self.assertTrue(grant['ok'], grant)
            n.f.live = False
            self.assertFalse(n.broker.consume(n.f.body, operation, grant['grant_id'])['ok'])
        self.assertEqual(n.f.sim.requests, [])

    def test_legacy_browser_authorization_stays_disabled(self):
        f = browser_fixture.OwnerAuto241Tests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.sim.identity()
        f.body.update(f.sim.last_identity)
        with patch.dict(os.environ, {'LEADBOT_PERSONAL_AUTO_AVAILABLE': '0'}):
            out, code = f.sim.app.handle(dict(f.body, action='personal_authorize'))
            self.assertEqual((code, out.get('code')), (403, 'auto_disabled'))
            self.assertFalse(out['execution_allowed'])
        self.assertEqual(f.sim.requests, [])


if __name__ == '__main__':
    unittest.main()
