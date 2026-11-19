import copy
import itertools
import json
import unittest

import research_openai as api
from api_costs import UsageLedger
from research_pipeline import pack_context, schema_matches, validate_schema, Pipeline
import test_research_pipeline218 as fixtures
import test_workflow as workflow_fixture


def compact(schema):
    # Before238 this exercises the actual unchanged representation, rather
    # than failing discovery because the new helper does not yet exist.
    return getattr(api, 'compact_wire_schema', copy.deepcopy)(schema)


def conditional():
    review = dict(type='object', properties=dict(goal=dict(type='string', minLength=1, maxLength=50),
                  fits=dict(type='boolean')), required=['goal', 'fits'], additionalProperties=False)
    common = dict(type='object', properties=dict(reply=dict(type='string', enum=['', 'OK'], maxLength=20),
                  needs_operator=dict(type='boolean'), context=review),
                  required=['reply', 'needs_operator', 'context'], additionalProperties=False)
    yes, no = copy.deepcopy(common), copy.deepcopy(common)
    for branch, fits in ((yes, True), (no, False)):
        branch['properties']['reply']['enum'] = ['OK' if fits else '']
        branch['properties']['needs_operator']['enum'] = [not fits]
        branch['properties']['context']['properties']['fits']['enum'] = [fits]
    return dict(common, anyOf=[yes, no])


def envelope(candidate):
    return dict(type='object', properties=dict(candidate=candidate), required=['candidate'], additionalProperties=False)


class WireSchema238Tests(unittest.TestCase):
    def test_redundant_parent_is_removed_only_below_response_root(self):
        source = envelope(conditional())
        result = compact(source)
        self.assertEqual(set(result['properties']['candidate']), {'anyOf'})
        self.assertEqual(result['properties']['candidate']['anyOf'], source['properties']['candidate']['anyOf'])
        self.assertEqual(result['type'], 'object')
        self.assertFalse(result['additionalProperties'])
        self.assertLess(len(json.dumps(result)), len(json.dumps(source)))

    def test_all_positive_veto_and_invalid_combinations_keep_the_same_acceptance(self):
        source = envelope(conditional())
        result = compact(source)
        validate_schema(result)
        for reply, needs, fits, goal in itertools.product(['', 'OK', 'other', None, 1], [True, False, 0],
                                                         [True, False, 1], ['', 'intent', 'x'*51]):
            value = dict(candidate=dict(reply=reply, needs_operator=needs, context=dict(goal=goal, fits=fits)))
            self.assertEqual(schema_matches(value, source), schema_matches(value, result), value)
        for value in ({}, {'candidate': {}}, {'candidate': None}, {'candidate': {'extra': True}},
                      {'candidate': {'reply': 'OK', 'needs_operator': False, 'context': {'goal': 'intent', 'fits': True, 'extra': 1}}}):
            self.assertFalse(schema_matches(value, result))

    def test_missing_branch_limit_keeps_common_constraint(self):
        source = conditional()
        del source['anyOf'][0]['properties']['context']['properties']['goal']['maxLength']
        result = compact(envelope(source))['properties']['candidate']
        self.assertIn('properties', result)
        self.assertEqual(result['properties'], source['properties'])

    def test_required_field_cannot_disappear_from_a_branch(self):
        source = conditional()
        source['anyOf'][0]['required'].remove('context')
        result = compact(envelope(source))['properties']['candidate']
        self.assertIn('properties', result)
        self.assertFalse(schema_matches({'candidate': {'reply': 'OK', 'needs_operator': False}}, envelope(result)))

    def test_additional_fields_cannot_gain_permission(self):
        source = conditional()
        source['anyOf'][0]['additionalProperties'] = True
        self.assertIn('properties', compact(envelope(source))['properties']['candidate'])

    def test_enum_boolean_and_number_are_not_equal_in_subsumption_proof(self):
        source = conditional()
        source['properties']['needs_operator']['enum'] = [True]
        source['anyOf'][0]['properties']['needs_operator']['enum'] = [1]
        self.assertIn('properties', compact(envelope(source))['properties']['candidate'])

    def test_missing_const_does_not_prove_const_null(self):
        source = conditional()
        source['properties']['context']['properties']['goal']['const'] = None
        self.assertIn('properties', compact(envelope(source))['properties']['candidate'])

    def test_pattern_is_preserved_and_never_inferred_from_the_example(self):
        source = conditional()
        source['properties']['context']['properties']['goal']['pattern'] = '^source:'
        self.assertIn('properties', compact(envelope(source))['properties']['candidate'])

    def test_nonfinite_bound_never_proves_removal(self):
        source = conditional()
        source['properties']['reply']['maxLength'] = float('nan')
        self.assertIn('properties', compact(envelope(source))['properties']['candidate'])

    def test_invalid_fractional_length_is_not_silently_repaired_into_a_valid_schema(self):
        source = conditional()
        source['properties']['reply']['maxLength'] = 20.5
        self.assertIn('properties', compact(envelope(source))['properties']['candidate'])

    def test_response_root_stays_an_object_even_with_redundant_anyof(self):
        source = conditional()
        result = compact(source)
        self.assertEqual(result['type'], 'object')
        self.assertIn('properties', result)

    def test_source_schema_and_independent_free_fields_are_not_mutated(self):
        source = envelope(conditional())
        before = copy.deepcopy(source)
        result = compact(source)
        self.assertEqual(source, before)
        for branch in result['properties']['candidate']['anyOf']:
            self.assertNotIn('enum', branch['properties']['context']['properties']['goal'])

    def test_actual_Office_contract_keeps_both_full_original_branches_and_wire_equivalence(self):
        f = workflow_fixture.WorkflowTests()
        f.setUp()
        self.addCleanup(f.tearDown)
        ctx = f.ctx()
        ctx['messages'][0]['body'] = 'Здравствуйте, не работают Word и Excel на компьютере. Можете помочь? И какая стоимость?'
        prepared = f.call('preview', ctx=ctx, wording_mode='neural_review')
        original = prepared['model_task']['response_format']['schema']
        source = api._schema('research', original)
        result = compact(source)
        actual = result['properties']['candidate']
        self.assertEqual(set(actual), {'anyOf'})
        self.assertEqual(actual['anyOf'], original['anyOf'])
        self.assertEqual(original, prepared['model_task']['response_format']['schema'])
        self.assertEqual(actual['anyOf'][0]['properties']['reply']['enum'], original['anyOf'][0]['properties']['reply']['enum'])
        self.assertEqual(actual['anyOf'][1]['properties']['reply']['enum'], [''])
        self.assertFalse(actual['anyOf'][1]['properties']['context_review']['properties']['selected_step_fits']['enum'][0])
        evidence = original['properties']['context_review']['properties']['evidence_ids']['items']['enum']
        candidate = dict(reply=actual['anyOf'][0]['properties']['reply']['enum'][0], needs_operator=False,
                         context_review=dict(last_intent='Клиент просит помощь с программами и спрашивает цену.',
                         latest_client_meaning='Word и Excel не работают; клиент спрашивает о помощи и стоимости.',
                         selected_step_fits=True, evidence_ids=[evidence[0]], note='Нужны симптомы запуска; модель ПК не требуется.'))
        self.assertTrue(schema_matches(candidate, original))
        self.assertTrue(schema_matches(candidate, actual))
        candidate['reply'] = ''
        candidate['needs_operator'] = True
        candidate['context_review']['selected_step_fits'] = False
        self.assertTrue(schema_matches(candidate, original))
        self.assertTrue(schema_matches(candidate, actual))
        candidate['context_review']['evidence_ids'] = ['another-client']
        self.assertFalse(schema_matches(candidate, original))
        self.assertFalse(schema_matches(candidate, actual))

    def test_actual_API_wire_is_compact_while_bound_native_contract_is_unchanged(self):
        current = fixtures.context()
        current['candidate_contract'] = dict(system='Preserve source roles and all conditional checks.', task={}, schema=conditional())
        original = copy.deepcopy(current)
        payloads = []
        def request(payload, timeout):
            payloads.append(payload)
            raise TimeoutError('synthetic')
        with self.assertRaises(api.TransportError):
            api.ResponsesTransport(request, UsageLedger())('research', pack_context('research', current), ())
        self.assertEqual(set(payloads[0]['text']['format']['schema']['properties']['candidate']), {'anyOf'})
        self.assertEqual(current, original)
        self.assertEqual(payloads[0]['reasoning'], {'effort': 'max'})
        self.assertEqual(payloads[0]['max_output_tokens'], 32768)

    def test_incomplete_output_has_a_bounded_code_no_reply_no_retry_and_unknown_zero_usage(self):
        calls, ledger = [], UsageLedger()
        def request(payload, timeout):
            calls.append(payload)
            return dict(id='incomplete238', model='gpt-6.1-sol', status='incomplete', service_tier='default',
                        incomplete_details={'reason': 'max_output_tokens'}, output=[],
                        usage=dict(input_tokens=0, output_tokens=0,
                                   input_tokens_details=dict(cached_tokens=0, cache_write_tokens=0)))
        with self.assertRaises(api.TransportError) as raised:
            api.ResponsesTransport(request, ledger)('research', pack_context('research', fixtures.context()), ())
        self.assertEqual(getattr(raised.exception, 'failure_code', None), 'provider_output_limit')
        self.assertEqual(len(calls), 1)
        self.assertEqual(ledger.summary()['unknown_calls'], 1)
        self.assertFalse(ledger.summary()['complete'])

    def test_pipeline_keeps_only_the_trusted_finite_failure_code_not_external_exception_text(self):
        f = fixtures.ResearchTests()
        f.setUp()
        self.addCleanup(f.tmp.cleanup)
        events = []
        def model(role, packet, tools):
            raise api.TransportError('sensitive external exception text', failure_code='provider_output_limit')
        result = Pipeline(f.corpus, model, audit=lambda kind, data: events.append((kind, data))).run(fixtures.context())
        self.assertFalse(result['approved'])
        self.assertFalse(result['can_send_or_create'])
        self.assertEqual(result['failure_code'], 'provider_output_limit')
        self.assertEqual(result['failure_kind'], 'technical')
        self.assertNotIn('sensitive', str(result))
        self.assertEqual(next(data for kind, data in events if kind == 'research_stopped')['failure_code'], 'provider_output_limit')

    def test_unknown_or_spoofed_failure_code_cannot_become_a_trusted_diagnosis(self):
        f = fixtures.ResearchTests()
        f.setUp()
        self.addCleanup(f.tmp.cleanup)
        def model(role, packet, tools):
            error = ValueError('provider response containing a secret')
            error.failure_code = 'provider_output_limit'
            raise error
        result = Pipeline(f.corpus, model).run(fixtures.context())
        self.assertNotIn('failure_code', result)
        self.assertNotIn('secret', str(result))
        self.assertIsNone(api.TransportError('ignored', failure_code='secret-from-provider').failure_code)
