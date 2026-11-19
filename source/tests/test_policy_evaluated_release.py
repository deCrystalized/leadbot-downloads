"""Agent configuration improvements must pass paired quality evaluation."""

import copy
import hmac
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path

from leadbot.brain.policy_attestations import DOMAIN, Attestation, PolicyAttestations
from leadbot.brain.policy_bundles import (
    PARTS,
    BundleError,
    PolicyBundles,
    RuleRequirement,
)
from leadbot.brain.policy_candidate_evaluation import (
    REVIEW_DOMAIN,
    BundleEvaluationPlan,
    EvaluatedRelease,
    EvaluationError,
    ReviewedRun,
    compare,
    evaluated_release_verifier,
    review_verifier,
)
from leadbot.brain.source_protocol import decode, encode, sha


class EvaluatedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "bundles.sqlite"
        self.now, self.scope = 1000, "intake"
        self.keys = {("source", self.scope, "publisher"): b"s" * 32,
                     ("normative", self.scope, "compiler"): b"n" * 32,
                     ("release", self.scope, "releaser"): b"r" * 32}
        self.attest = PolicyAttestations(self.keys, {self.scope: frozenset({"paired-quality"})}, clock=lambda: self.now)
        self.store = PolicyBundles(self.path, self.attest.verify_requirement, self.attest.verify_release, clock=lambda: self.now)
        self.parts = {kind: ("synthetic-" + kind).encode() for kind in PARTS}
        self.requirement = RuleRequirement(self.scope, "current", None, "rules", "rules-current", sha(self.parts["rules"]), self.now)
        normative = self.sign("normative", "compiler", {"issued_at": self.now,
                              "requirement_sha256": sha(encode(asdict(self.requirement)))})
        self.store.register(self.requirement, normative)
        self.base = self.store.prepare(self.scope, "current", self.parts)
        self.base_manifest = self.manifest(self.base)
        self.store.activate(self.scope, "current", self.base, self.release(self.base, None), expected_active=None)
        self.candidate = self.store.prepare(self.scope, "current", {**self.parts, "templates": b"synthetic-improved-templates"})
        self.candidate_manifest = self.manifest(self.candidate)
        self.plan = {"baseline_build": self.base, "candidate_build": self.candidate,
                     "active_policy": sha(self.parts["rules"]),
                     "cases": {key: {"source_sha256": sha(("source-" + key).encode()),
                                     "gold_sha256": sha(("gold-" + key).encode()), "groups": [group]}
                               for key, group in (("crm", "critical"), ("question", "routine"), ("answer", "routine"))},
                     "critical_groups": {"critical": 1, "routine": 2},
                     "max_total_microusd": None, "max_case_ms": None}
        self.before = {"crm": True, "question": False, "answer": False}
        self.after = {"crm": True, "question": True, "answer": True}
        self.review_keys = {"baseline-reviewer": b"b" * 32, "candidate-reviewer": b"c" * 32}
        self.verify_review = review_verifier(self.scope, self.review_keys, max_age=300, clock=lambda: self.now)

    def manifest(self, digest):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT manifest FROM bundles WHERE digest=?", (digest,)).fetchone()[0]

    def sign(self, role, issuer, claims):
        raw = encode(claims)
        prefix = DOMAIN + b"\0".join(x.encode() for x in (role, self.scope, issuer)) + b"\0"
        return Attestation(issuer, raw, hmac.digest(self.keys[(role, self.scope, issuer)], prefix + raw, "sha256"))

    def release(self, digest, previous):
        return self.sign("release", "releaser", {"issued_at": self.now, "manifest_sha256": digest,
            "previous_manifest_sha256": previous, "checks": {"paired-quality": True}})

    @staticmethod
    def original(build, case):
        return ("synthetic-original:" + build + ":" + case).encode()

    def reviewed(self, frozen, build, verdicts, issuer):
        raw = encode({"plan_sha256": sha(frozen), "build_sha256": build, "policy_sha256": self.plan["active_policy"],
                      "cases": {key: {**{f: value[f] for f in ("source_sha256", "gold_sha256")},
                                      "original_sha256": sha(self.original(build, key)), "passed": verdicts[key],
                                      "policy_ok": True, "actions_ok": True, "elapsed_ms": 20, "usage_microusd": 1}
                                for key, value in self.plan["cases"].items()}})
        claims = encode({"issued_at": self.now, "run_sha256": sha(raw)})
        prefix = REVIEW_DOMAIN + self.scope.encode() + b"\0" + issuer.encode() + b"\0" + claims
        return ReviewedRun(raw, Attestation(issuer, claims, hmac.digest(self.review_keys[issuer], prefix, "sha256")))

    def evaluations(self):
        frozen = encode(self.plan)
        return frozen, self.reviewed(frozen, self.base, self.before, "baseline-reviewer"), self.reviewed(frozen, self.candidate, self.after, "candidate-reviewer")

    def gated(self, *, read_original=None, registry=None):
        frozen, before, after = self.evaluations()
        if registry is None:
            registry = {self.candidate: BundleEvaluationPlan(frozen, sha(frozen), self.base_manifest)}
        gate = evaluated_release_verifier(self.scope, registry, verify_release=self.attest.verify_release,
            verify_review=self.verify_review, read_original=read_original or self.original)
        self.store = PolicyBundles(self.path, self.attest.verify_requirement, gate, clock=lambda: self.now)
        receipt = EvaluatedRelease(self.release(self.candidate, self.base), before, after)
        return gate, receipt

    def activate(self, receipt):
        return self.store.activate(self.scope, "current", self.candidate, receipt, expected_active=self.base)

    def assert_held(self, receipt):
        with self.assertRaises(BundleError):
            self.activate(receipt)
        self.assertEqual(self.store.active(self.scope).manifest_sha256, self.base)

    def resign(self, run, change):
        value = decode(run.raw)
        change(value)
        raw = encode(value)
        issuer = run.attestation.issuer
        claims = encode({"issued_at": self.now, "run_sha256": sha(raw)})
        message = REVIEW_DOMAIN + self.scope.encode() + b"\0" + issuer.encode() + b"\0" + claims
        return ReviewedRun(raw, Attestation(issuer, claims, hmac.digest(self.review_keys[issuer], message, "sha256")))

    def test_critical_regression_cannot_activate_despite_signed_release_claim(self):
        self.after["crm"] = False
        frozen, before, after = self.evaluations()
        verdict = compare(frozen, sha(frozen), before, after, verify_review=self.verify_review, read_original=self.original)
        self.assertFalse(verdict["comparison_passed"])
        self.assertIn("critical_group_regression:critical", verdict["reasons"])
        _, receipt = self.gated()
        self.assert_held(receipt)

    def test_better_compatible_configuration_activates_once(self):
        _, receipt = self.gated()
        self.assertEqual(self.activate(receipt), "activated")
        self.assertEqual(self.activate(receipt), "duplicate")
        self.assertEqual(self.store.active(self.scope).manifest_sha256, self.candidate)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM publication_events").fetchone()[0], 2)

    def test_plain_release_and_unreviewed_claims_cannot_use_the_gate(self):
        _, receipt = self.gated()
        self.assert_held(receipt.release_attestation)
        self.assert_held({"comparison_passed": True})

    def test_no_overall_improvement_keeps_current_bundle_readable(self):
        self.after = dict(self.before)
        _, receipt = self.gated()
        self.assert_held(receipt)

    def test_each_independent_signature_is_required(self):
        _, receipt = self.gated()
        for field in ("baseline", "candidate"):
            run = getattr(receipt, field)
            altered = replace(run, attestation=replace(run.attestation, mac=b"0" * 32))
            with self.subTest(field=field):
                self.assert_held(replace(receipt, **{field: altered}))
        self.assert_held(replace(receipt, release_attestation=replace(receipt.release_attestation, mac=b"0" * 32)))

    def test_expired_reviews_or_releases_do_not_activate(self):
        _, receipt = self.gated()
        self.now += 301
        self.assert_held(receipt)

    def test_changed_original_execution_is_held(self):
        _, receipt = self.gated(read_original=lambda build, case: self.original(build, case) + b"changed")
        self.assert_held(receipt)

    def test_unknown_candidate_does_not_borrow_another_approved_plan(self):
        gate, receipt = self.gated()
        different = encode({**decode(self.candidate_manifest), "parts": {
            **decode(self.candidate_manifest)["parts"], "templates": "d" * 64}})
        self.assertFalse(gate(different, self.base, receipt))

    def test_wrong_predecessor_and_bootstrap_are_held(self):
        gate, receipt = self.gated()
        for previous in (None, "e" * 64):
            with self.subTest(previous=previous):
                self.assertFalse(gate(self.candidate_manifest, previous, receipt))

    def test_registry_is_frozen_and_plan_cannot_be_self_selected(self):
        frozen, _, _ = self.evaluations()
        registry = {self.candidate: BundleEvaluationPlan(frozen, sha(frozen), self.base_manifest)}
        _, receipt = self.gated(registry=registry)
        registry.clear()
        self.assertEqual(self.activate(receipt), "activated")

    def test_configuration_rejects_wrong_plan_baseline_or_scope(self):
        frozen, _, _ = self.evaluations()
        for approval in (BundleEvaluationPlan(frozen, "0" * 64, self.base_manifest),
                         BundleEvaluationPlan(frozen, sha(frozen), self.candidate_manifest),
                         BundleEvaluationPlan(frozen, sha(frozen), encode({**decode(self.base_manifest),
                             "requirement": {**decode(self.base_manifest)["requirement"], "scope": "other"}}))):
            with self.subTest(approval=approval.approved_sha256), self.assertRaises(ValueError):
                self.gated(registry={self.candidate: approval})
        with self.assertRaises(EvaluationError):
            self.gated(registry={})

    def test_rules_and_normative_requirement_must_remain_identical(self):
        original = copy.deepcopy(self.plan)
        original_hash = self.candidate
        for change in ("rules", "requirement"):
            value = decode(self.candidate_manifest)
            if change == "rules":
                value["parts"]["rules"] = "d" * 64
            else:
                value["requirement"]["version"] = "new-normative-version"
            manifest = encode(value)
            self.plan = copy.deepcopy(original)
            self.candidate = sha(manifest)
            self.plan["candidate_build"] = self.candidate
            gate, receipt = self.gated()
            with self.subTest(change=change):
                self.assertFalse(gate(manifest, self.base, receipt))
        self.plan, self.candidate = original, original_hash

    def test_configured_cost_and_latency_limits_are_not_signed_away(self):
        for field, limit in (("max_total_microusd", 2), ("max_case_ms", 10)):
            with self.subTest(field=field):
                self.plan[field] = limit
                _, receipt = self.gated()
                self.assert_held(receipt)
                self.plan[field] = None

    def test_signed_unknown_metrics_cannot_pass_configured_limits(self):
        self.plan["max_total_microusd"] = 10
        self.plan["max_case_ms"] = 100
        _, receipt = self.gated()
        for field in ("usage_microusd", "elapsed_ms"):
            changed = self.resign(receipt.candidate, lambda run, field=field: run["cases"]["crm"].update({field: None}))
            with self.subTest(field=field):
                self.assert_held(replace(receipt, candidate=changed))
        self.assertEqual(self.store.active(self.scope).manifest_sha256, self.base)


if __name__ == "__main__":
    unittest.main()
