"""17 October branch notice: independent CRM route and approval boundaries."""
import unittest
from unittest.mock import patch

import assistant_catalog
import assistant_policy
import contact_facts
import personal_workflow
from extension_assistant import _parse
from test_assistant import context, message


class KrasnoyarskPlumbingTests(unittest.TestCase):
    def decision(self, text, **extra):
        ctx = context([message(text)], dir="mnc", city="Красноярск", accountTitle="Григорий МНЧ", itemTitle="Сантехник")
        ctx.update(extra)
        _, rows, known, _ = _parse(ctx)
        return assistant_policy.assess(rows, known, contact_facts.collect(rows, known))

    def test_normal_plumbing_route_and_notice_are_versioned(self):
        result = self.decision("В Красноярске заменить смеситель")
        route = result["crm_route"]
        self.assertEqual(route["city_id"], "709")
        self.assertEqual(route["physical_city"], "Красноярск")
        self.assertEqual(route["lead_hours"], [1, 1.5])
        self.assertTrue(route["client_convenient_time_allowed"])
        self.assertIn(route["rule_id"], result["rule_ids"])
        self.assertEqual(assistant_policy.retrieve("", refs=[route["rule_id"]])[0]["date"], "2026-10-17")

    def test_approval_order_never_becomes_automatic_permission(self):
        for extra in ({}, {"branchApproval": True, "branchRefused": "709", "auto_enabled": True}):
            result = self.decision("В Красноярске заменить стояк отопления", **extra)
            self.assertEqual(result["action"], "handoff")
            steps = result["crm_route"]["approval_steps"]
            self.assertEqual([r["city_id"] for r in steps], ["709", "3"])
            self.assertEqual(steps[1]["requires"], "verified_refusal_from_709")
            self.assertLess(result["reason"].index("Сначала"), result["reason"].index("После подтверждённого отказа"))
            self.assertTrue(result["crm_route"]["approval_operator_required"])
            self.assertFalse(assistant_policy.AUTO_ENABLED)

    def test_other_work_cities_and_profiles_keep_their_route(self):
        self.assertNotIn("crm_route", self.decision("В Красноярске повесить полку"))
        service = assistant_catalog.choose("Заменить смеситель", {"direction": "mnc"})
        for known in ({"direction": "mnc", "city": "Омск"}, {"direction": "kp", "city": "Красноярск"}, {"direction": "bt", "city": "Красноярск"}):
            self.assertIsNone(assistant_policy.crm_branch_route(known, service))
        self.assertIsNone(assistant_policy.crm_branch_route({"direction": "mnc", "city": "Красноярск", "channel": "max_user"}, service))

    def test_early_territory_handoff_keeps_ordered_operator_route(self):
        geo = {"status": "needs_confirmation", "reason": "Территория требует согласования с филиалом", "rule_ids": []}
        with patch.object(assistant_policy, "geography", return_value=geo):
            out = self.decision("В Красноярске заменить смеситель")
        self.assertEqual(out["action"], "handoff")
        self.assertEqual([s["city_id"] for s in out["crm_route"]["approval_steps"]], ["709", "3"])
        self.assertIn("После подтверждённого отказа", out["reason"])
        self.assertIn(assistant_policy.KRASNOYARSK_PLUMBING_RULE, out["rule_ids"])

    def test_mixed_work_is_not_silently_sent_to_single_branch(self):
        result = self.decision("В Красноярске заменить смеситель и установить розетку")
        self.assertEqual(result["action"], "handoff")
        self.assertTrue(result["crm_route"]["mixed_work"])

    def test_live_crm_directory_exact_id_and_work_are_required(self):
        route = self.decision("В Красноярске заменить смеситель")["crm_route"]
        prep = {"cityId": "709", "cityText": "Красноярск сантехника", "cities": [{"id": "709", "text": "Красноярск сантехника"}], "applId": "13", "appl": [{"id": "13", "text": "Сантехника"}]}
        self.assertEqual(personal_workflow.branch_route_check(route, prep, {"cityId": "709"}), [])
        for changes in ({"cityId": "3", "cityText": "Красноярск"}, {"cityId": "3", "cityText": "Красноярск (Сантехника)"}, {"cities": []}, {"appl": [{"id": "13", "text": "Электрика"}]}, {"cityText": "Красноярск сантехника -"}):
            self.assertTrue(personal_workflow.branch_route_check(route, {**prep, **changes}, {"cityId": "709"}))
        self.assertTrue(personal_workflow.branch_route_check(route, prep, {"cityId": "3"}))

    def test_full_crm_check_rejects_generic_branch(self):
        text = "В Красноярске заменить смеситель. Адрес: улица Ленина, дом 1."
        ctx = context([message(text)], dir="mnc", city="Красноярск", accountTitle="Григорий МНЧ", itemTitle="Сантехник")
        _, rows, known, revision = _parse(ctx)
        ctx["workflowRevision"] = revision
        proposal = {"revision": revision, "lead": {"addr": contact_facts.collect(rows, known)["address"]}, "prep": {"cityId": "3", "cityText": "Красноярск", "cities": [{"id": "709", "text": "Красноярск сантехника"}]}, "territory": {}, "sel": {"cityId": "3"}}
        out = personal_workflow.check_crm(rows, known, ctx, proposal)
        self.assertFalse(out["ready"])
        self.assertFalse(out["execution_allowed"])
        self.assertTrue(any("709" in reason for reason in out["reasons"]))
        proposal["territory"] = {"ok": True, "approval": True}
        out = personal_workflow.check_crm(rows, known, ctx, proposal)
        self.assertFalse(out["ready"])
        self.assertTrue(any("После подтверждённого отказа" in reason for reason in out["reasons"]))
