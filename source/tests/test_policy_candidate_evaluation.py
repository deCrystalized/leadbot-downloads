import copy
import hmac
import unittest

from leadbot.brain.policy_attestations import Attestation
from leadbot.brain.policy_candidate_evaluation import EvaluationError, REVIEW_DOMAIN, ReviewedRun, compare, review_verifier
from leadbot.brain.source_protocol import encode, sha


class CandidateEvaluationTests(unittest.TestCase):
    def setUp(self):
        cases = {
            key: dict(source_sha256=sha(key.encode()), gold_sha256=sha(('gold-' + key).encode()),
                      groups=[group])
            for key, group in (('critical', 'crm'), ('routine-1', 'routine'), ('routine-2', 'routine'))
        }
        self.plan = dict(baseline_build='a' * 64, candidate_build='b' * 64, active_policy='c' * 64,
                         cases=cases, critical_groups={'crm': 1, 'routine': 2},
                         max_total_microusd=None, max_case_ms=None)
        self.before = {'critical': True, 'routine-1': False, 'routine-2': False}
        self.after = {'critical': True, 'routine-1': True, 'routine-2': True}

    def run_result(self, plan_raw, build, grades):
        return dict(plan_sha256=sha(plan_raw), build_sha256=build, policy_sha256=self.plan['active_policy'],
                    cases={
                        key: dict(source_sha256=case['source_sha256'], gold_sha256=case['gold_sha256'],
                                  original_sha256=sha((build + key).encode()), passed=grades[key],
                                  policy_ok=True, actions_ok=True, elapsed_ms=25, usage_microusd=5)
                        for key, case in self.plan['cases'].items()})

    def original(self, build, case_id):
        return (build + case_id).encode()

    def evaluate(self, edit=None, *, read_original=None):
        frozen = encode(self.plan)
        before = self.run_result(frozen, self.plan['baseline_build'], self.before)
        after = self.run_result(frozen, self.plan['candidate_build'], self.after)
        if edit:
            edit(after)
        reviewed = {'trusted-baseline': encode(before), 'trusted-candidate': encode(after)}
        return compare(frozen, sha(frozen), 'trusted-baseline', 'trusted-candidate',
                       verify_review=reviewed.__getitem__, read_original=read_original or self.original)

    def test_candidate_improves_with_no_critical_regression(self):
        result = self.evaluate()
        self.assertTrue(result['comparison_passed'])
        self.assertEqual((result['baseline']['passed'], result['candidate']['passed']), (1, 3))
        self.assertEqual(result['critical_groups']['crm'], {'cases': 1, 'baseline': 1, 'candidate': 1})

    def test_aggregate_improvement_does_not_hide_critical_regression(self):
        self.after['critical'] = False
        result = self.evaluate()
        self.assertEqual(result['candidate']['passed'], 2)
        self.assertFalse(result['comparison_passed'])
        self.assertEqual(result['reasons'], ['critical_group_regression:crm'])

    def test_equal_quality_and_rule_or_action_violation_block(self):
        self.after = self.before.copy()
        self.assertEqual(self.evaluate()['reasons'], ['no_overall_improvement'])
        self.after.update({'routine-1': True, 'routine-2': True})
        result = self.evaluate(lambda run: run['cases']['routine-1'].update(policy_ok=False, actions_ok=False))
        self.assertFalse(result['comparison_passed'])
        self.assertIn('candidate_rule_or_action_violation', result['reasons'])

    def test_unknown_cost_is_reported_and_blocks_a_configured_cost_gate(self):
        def missing_cost(run):
            run['cases']['routine-1']['usage_microusd'] = None

        result = self.evaluate(missing_cost)
        self.assertTrue(result['comparison_passed'])
        self.assertEqual(result['candidate']['unknown_usage_cases'], 1)
        self.assertEqual(result['candidate']['known_usage_microusd'], 10)
        self.plan.update(max_total_microusd=100, max_case_ms=20)
        self.assertEqual(self.evaluate(missing_cost)['reasons'],
                         ['cost_limit_unverified_or_exceeded', 'latency_limit_unverified_or_exceeded'])

    def test_changed_policy_roster_or_source_are_refused(self):
        for edit in (
            lambda run: run.update(policy_sha256='d' * 64),
            lambda run: run['cases'].pop('critical'),
            lambda run: run['cases']['critical'].update(source_sha256='d' * 64),
            lambda run: run['cases']['critical'].update(original_sha256=''),
        ):
            with self.subTest(edit=edit), self.assertRaises(EvaluationError):
                self.evaluate(edit)

    def test_changed_plan_or_insufficient_frozen_coverage_are_refused(self):
        frozen = encode(self.plan)
        edited = copy.deepcopy(self.plan)
        edited['max_case_ms'] = 500
        with self.assertRaises(EvaluationError):
            compare(encode(edited), sha(frozen), None, None, verify_review=lambda _: self.fail('Not approved'),
                    read_original=lambda *_: self.fail('Unapproved originals must not be opened'))
        self.plan['critical_groups']['crm'] = 2
        with self.assertRaisesRegex(EvaluationError, 'coverage'):
            self.evaluate()

    def test_verifier_is_required_for_both_roles(self):
        frozen = encode(self.plan)
        verified = encode(self.run_result(frozen, self.plan['baseline_build'], self.before))

        def verify(receipt):
            if receipt != 'trusted-baseline':
                raise PermissionError('Unknown evaluator')
            return verified

        with self.assertRaises(PermissionError):
            compare(frozen, sha(frozen), 'trusted-baseline', 'candidate-self-report', verify_review=verify,
                    read_original=lambda *_: self.fail('Unverified originals must not be opened'))

    def test_same_frozen_source_cannot_inflate_group_coverage(self):
        cases = self.plan['cases']
        cases['routine-2']['source_sha256'] = cases['routine-1']['source_sha256']
        with self.assertRaisesRegex(EvaluationError, 'source appears more than once'):
            self.evaluate()

    def test_original_receipt_cannot_be_reused_across_cases_or_builds(self):
        reused = {
            'candidate_case': sha((self.plan['candidate_build'] + 'routine-2').encode()),
            'baseline_case': sha((self.plan['baseline_build'] + 'routine-1').encode()),
        }
        for reuse, digest in reused.items():
            with self.subTest(reuse=reuse), self.assertRaisesRegex(EvaluationError, 'original.*reused'):
                self.evaluate(lambda run: run['cases']['routine-1'].update(original_sha256=digest))

    def test_frozen_source_or_gold_cannot_stand_in_for_original_receipt(self):
        for field in ('source_sha256', 'gold_sha256'):
            digest = self.plan['cases']['routine-1'][field]
            with self.subTest(field=field), self.assertRaisesRegex(EvaluationError, 'original.*source or gold'):
                self.evaluate(lambda run: run['cases']['routine-1'].update(original_sha256=digest))

    def test_unique_digest_without_matching_original_is_not_proof(self):
        with self.assertRaisesRegex(EvaluationError, 'Original execution bytes'):
            self.evaluate(lambda run: run['cases']['routine-1'].update(original_sha256='e' * 64))
        for evidence in (None, b'', b'changed bytes', self.original(self.plan['baseline_build'], 'routine-1')):
            def original(build, case_id):
                if (build, case_id) == (self.plan['candidate_build'], 'routine-1'):
                    return evidence
                return self.original(build, case_id)

            with self.subTest(evidence=evidence), self.assertRaisesRegex(EvaluationError, 'Original execution bytes'):
                self.evaluate(read_original=original)

    def signed(self, raw, *, scope='intake', issued_at=100):
        claims = encode(dict(issued_at=issued_at, run_sha256=sha(raw)))
        message = REVIEW_DOMAIN + scope.encode() + b'\0independent-reviewer\0' + claims
        return ReviewedRun(raw, Attestation('independent-reviewer', claims,
                                             hmac.digest(b'r' * 32, message, 'sha256')))

    def test_two_independently_signed_original_runs_can_be_compared(self):
        frozen = encode(self.plan)
        before = self.signed(encode(self.run_result(frozen, self.plan['baseline_build'], self.before)))
        after = self.signed(encode(self.run_result(frozen, self.plan['candidate_build'], self.after)))
        verify = review_verifier('intake', {'independent-reviewer': b'r' * 32}, max_age=10, clock=lambda: 105)
        result = compare(frozen, sha(frozen), before, after, verify_review=verify, read_original=self.original)
        self.assertTrue(result['comparison_passed'])
        self.assertEqual(result['reviewed_runs'],
                         {'baseline_sha256': sha(before.raw), 'candidate_sha256': sha(after.raw)})

    def test_tampered_bytes_other_scope_and_stale_or_future_receipts_are_refused(self):
        verify = review_verifier('intake', {'independent-reviewer': b'r' * 32}, max_age=10, clock=lambda: 105)
        original = self.signed(b'original')
        for invalid in (ReviewedRun(b'tampered', original.attestation),
                        self.signed(b'original', scope='complaints'),
                        self.signed(b'original', issued_at=94),
                        self.signed(b'original', issued_at=106)):
            with self.subTest(invalid=invalid), self.assertRaises(EvaluationError):
                verify(invalid)

    def test_review_cannot_be_self_authorized_by_an_unconfigured_issuer(self):
        verify = review_verifier('intake', {'another-reviewer': b's' * 32}, max_age=10, clock=lambda: 105)
        with self.assertRaisesRegex(EvaluationError, 'Unknown reviewer'):
            verify(self.signed(b'original'))
