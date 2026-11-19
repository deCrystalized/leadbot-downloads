import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_policy
import personal_assistant
from assistant_store import Store
from extension_assistant import Assistant


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LEADBOT_PERSONAL_OWNER_ID": "owner", "LEADBOT_PERSONAL_OPERATOR_ID": "george", "LEADBOT_PERSONAL_AUTO_AVAILABLE": "1"})
        self.env.start();self.app = Assistant(Store(self.tmp.name + "/db"))
        self.base = {"owner": "owner", "operator_id": "george", "browser_session": "mode-test:tab:1"}
        self.lease = self.call("personal_start")

    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def call(self, action, **extra):
        return self.app.handle({**self.base, "action": action, **extra})[0]

    def activation(self, **extra):
        return dict(execution_mode="auto", confirmed=True, client_version="2.7.0", policy_ack=assistant_policy.VERSION, activation_nonce=self.lease["activation_nonce"], **extra)

    def test_deployment_flag_and_request_flags_do_not_activate_a_session(self):
        self.assertTrue(self.lease["auto_available"]);self.assertFalse(self.lease["auto_enabled"])
        for flags in [{"auto_enabled": True}, {"execution_mode": "auto"}, {"confirmed": True}]:
            self.assertFalse(self.call("personal_status", **flags)["auto_enabled"])
        self.assertEqual(self.call("personal_authorize", auto_enabled=True)["code"], "auto_disabled")

    def test_only_current_explicit_activation_can_enable_and_reconnect_always_reviews(self):
        enabled = self.call("personal_mode", **self.activation())
        self.assertTrue(enabled["auto_enabled"]);self.assertGreater(enabled["mode_epoch"], self.lease["mode_epoch"])
        self.assertFalse(self.call("personal_mode", **self.activation())["ok"])
        self.assertFalse(self.call("personal_mode", execution_mode="review")["auto_enabled"])
        self.assertFalse(self.call("personal_start")["auto_enabled"])

    def test_missing_wrong_old_nonce_policy_client_and_confirmation_are_rejected(self):
        for change in [{"activation_nonce": ""}, {"activation_nonce": "x"*30}, {"policy_ack": "old"}, {"client_version": "2.6.0"}, {"client_version": "bad"}, {"confirmed": False}]:
            self.assertFalse(self.call("personal_mode", **{**self.activation(), **change})["ok"])

    def test_another_browser_or_operator_cannot_use_the_owner_nonce(self):
        for change in [{"browser_session": "mode-test:tab:2"}, {"operator_id": "colleague"}, {"owner": "colleague"}]:
            out, _ = self.app.handle({**self.base, "action": "personal_mode", **self.activation(), **change})
            self.assertFalse(out["ok"])

    def test_policy_change_kill_switch_and_stop_end_auto(self):
        self.assertTrue(self.call("personal_mode", **self.activation())["auto_enabled"])
        with patch.object(assistant_policy, "VERSION", "future-policy"):
            self.assertFalse(self.call("personal_heartbeat")["auto_enabled"])
        self.lease = self.call("personal_start");self.call("personal_mode", **self.activation())
        with patch.dict(os.environ, {"LEADBOT_PERSONAL_AUTO_AVAILABLE": "0"}):
            self.assertFalse(self.call("personal_status")["auto_enabled"])
        self.assertFalse(self.call("personal_stop")["auto_enabled"])

    def test_session_migration_defaults_existing_lease_to_review(self):
        temp = Store(self.tmp.name + "/old")
        with temp.connect() as db:
            db.execute("CREATE TABLE personal_sessions(scope TEXT PRIMARY KEY,sid TEXT,operator TEXT,expires REAL,max_dialogs INTEGER)")
        out = personal_assistant.session(temp, "owner", "personal_start", self.base)
        self.assertFalse(out["auto_enabled"]);self.assertGreater(len(out["activation_nonce"]), 20)

    def test_mode_reset_is_audited_without_activation_nonce(self):
        self.call("personal_mode", **self.activation())
        with patch.object(assistant_policy, "VERSION", "changed"):
            self.assertEqual(self.call("personal_heartbeat")["mode_reset_reason"], "Регламент изменился")
        audit = self.call("personal_audit")
        text = __import__("json").dumps(audit, ensure_ascii=False)
        self.assertIn("Регламент изменился", text)
        self.assertNotIn(self.lease["activation_nonce"], text)
        self.assertNotIn("activation_nonce", text)

    def test_withdrawn_primary_paragraphs_cannot_be_retrieved(self):
        withdrawn = [s for s in assistant_policy.registry()["sources"] if s.get("active_primary") is False]
        self.assertGreaterEqual(len(withdrawn), 31)
        ids = {s["id"] for s in withdrawn}
        for source in withdrawn:
            found = assistant_policy.retrieve(source["text"], refs=[source["id"]])
            self.assertFalse(ids & {s["id"] for s in found})

    def test_upgrade_removes_an_existing_positive_conversation_limit(self):
        with self.app.store.connect() as db:
            db.execute("UPDATE personal_sessions SET max_dialogs=5")
        status = self.call("personal_status")
        self.assertEqual(status["max_dialogs"], 0)
        self.assertFalse(status["auto_enabled"])
