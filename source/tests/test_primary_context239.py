import copy
import json
import unittest
from pathlib import Path

from research_pipeline import Corpus, Pipeline, ResearchError, pack_context
import test_research_pipeline218 as fixtures
import test_research_continuation209 as continuation


class PrimaryContext239Tests(unittest.TestCase):
    def fixture(self, rules=None):
        f = fixtures.ResearchTests(); f.setUp(); self.addCleanup(f.tmp.cleanup)
        rules = rules if rules is not None else json.loads(
            (Path(__file__).parents[1] / 'leadbot/brain/policy_registry.json').read_text())['sources']
        corpus = Corpus(f.corpus.reader, rules, allowed_cids=['old-a', 'old-b'],
                        guard=lambda ids: None, versions=lambda: f.version)
        return f, corpus

    def ids(self, corpus, key):
        return getattr(corpus, 'primary_context_ids', lambda key: [key])(key)

    def test_actual_first_stage_reads_its_full_section_without_later_price(self):
        _, c = self.fixture()
        self.assertEqual(self.ids(c, 'KP-L0474'), ['KP-L%04d' % n for n in range(473, 480)])
        self.assertNotIn('KP-L0484', self.ids(c, 'KP-L0474'))

    def test_actual_second_stage_keeps_condition_and_price_together(self):
        _, c = self.fixture()
        self.assertEqual(self.ids(c, 'KP-L0480'), ['KP-L%04d' % n for n in range(480, 486)])

    def stage_rules(self):
        return [dict(id='X-L%04d' % n, line=n, scope='kp', type='kp_document', text=text)
                for n, text in [(1, 'Возражения делятся на 2 этапа.'), (2, '1 этап.'),
                                (3, 'Первое условие и исключение.'), (4, 'Точная фраза.'),
                                (5, '2 этап.'), (6, 'Другая цена.')]]

    def test_foreign_document_type_scope_and_family_cannot_fill_a_gap(self):
        for change in [dict(type='document'), dict(scope='bt'), dict(id='Y-L0003')]:
            rules = self.stage_rules(); rules[2].update(change)
            _, c = self.fixture(rules)
            self.assertEqual(self.ids(c, 'X-L0002'), ['X-L0001', 'X-L0002'])

    def test_missing_line_stops_before_any_unrelated_text(self):
        rules = self.stage_rules(); del rules[2]
        _, c = self.fixture(rules)
        self.assertEqual(self.ids(c, 'X-L0002'), ['X-L0001', 'X-L0002'])

    def test_inactive_clause_is_not_read_or_skipped_to_resume_expansion(self):
        rules = self.stage_rules(); rules[2]['active_primary'] = False
        _, c = self.fixture(rules)
        self.assertEqual(self.ids(c, 'X-L0002'), ['X-L0001', 'X-L0002'])

    def test_arbitrary_numbered_text_is_not_treated_as_a_stage_heading(self):
        rules = self.stage_rules(); rules[1]['text'] = '1. Клиент упомянул этап ремонта.'
        _, c = self.fixture(rules)
        self.assertEqual(self.ids(c, 'X-L0002'), ['X-L0002'])

    def test_changed_source_versions_are_checked_before_expansion(self):
        f, c = self.fixture(self.stage_rules()); f.version = 'changed'
        with self.assertRaises(ResearchError): self.ids(c, 'X-L0002')

    def test_plain_rule_remains_exact_and_originals_are_not_rewritten(self):
        rules = self.stage_rules(); before = copy.deepcopy(rules)
        _, c = self.fixture(rules)
        self.assertEqual(self.ids(c, 'X-L0003'), ['X-L0003'])
        self.assertEqual(rules, before)
        with self.assertRaises(ResearchError): self.ids(c, 'MISSING')

    def test_real_office_query_prefers_price_or_program_rules_to_crm_jivo(self):
        _, c = self.fixture()
        result = c.call('search_rules', dict(query='КП: помощь с программами Word и Excel; как отвечать о стоимости до осмотра компьютера?'), fixtures.context())
        ids = [r['rule_id'] for r in result['hits'][:3]]
        self.assertTrue(set(ids) & {'KP-L0475', 'KP-L0478', 'KP-L0490', 'DOC-L0125'}, ids)
        self.assertNotIn('DOC-L0704', ids)

    def test_specific_cost_query_can_find_exact_price_explanation(self):
        _, c = self.fixture()
        out = c.call('search_rules', dict(query='«Точную стоимость» «осмотра» «программ» КП'), fixtures.context())
        self.assertIn('KP-L0490', [x['rule_id'] for x in out['hits'][:3]])

    def test_ranked_search_does_not_claim_primary_read_or_semantic_approval(self):
        _, c = self.fixture()
        out = c.call('search_rules', dict(query='стоимость программ'), fixtures.context())
        self.assertFalse(out['primary_text_read'])
        self.assertEqual(c.evidence(fixtures.context())['rules'], [])
        self.assertNotIn('semantic_match_verified', out)

    def test_actual_prefetch_reads_every_exact_clause_before_first_model_step(self):
        _, c = self.fixture(); packets = []
        current = fixtures.context(); current['direction'] = 'kp'
        current['messages'] = [dict(id='office', direction='in', sender_type='client', body='Не работают Word и Excel. Какова стоимость?')]
        current['facts'] = []
        original = copy.deepcopy(c.rules)
        def model(role, packet, tools):
            packets.append(packet); raise TimeoutError()
        Pipeline(c, model, initial_rule_ids=['KP-L0474'], max_calls=4).run(current)
        rows = packets[0]['input']['research']['rules']
        self.assertEqual([r['id'] for r in rows], ['KP-L%04d' % n for n in range(473, 480)])
        for r in rows: self.assertEqual(r, original[r['id']])
        self.assertEqual(c.rules, original)

    def test_bad_initial_source_stops_before_model_without_guessing_a_section(self):
        f, c = self.fixture(); calls = []
        out = Pipeline(c, lambda *args: calls.append(args), initial_rule_ids=['UNKNOWN']).run(fixtures.context())
        self.assertFalse(out['approved']); self.assertEqual(calls, [])

    def test_model_requested_heading_reads_the_same_full_section_and_references(self):
        _, c = self.fixture(); current = fixtures.context()
        out = c.call('read_rule', dict(rule_id='KP-L0474'), current)
        self.assertEqual(out['primary'], c.rules['KP-L0474'])
        expected = ['KP-L%04d' % n for n in range(473, 480)]
        rows = out.get('context_sources', [])
        self.assertEqual([r['rule_id'] for r in rows], expected)
        from experienced_dialogues import digest
        for r in rows:
            self.assertEqual(r['primary'], c.rules[r['rule_id']])
            self.assertEqual(r['source_sha256'], digest(r['primary']))
        self.assertEqual([r['id'] for r in c.evidence(current)['rules']], expected)

    def test_only_broad_query_still_has_results_without_invented_semantic_match(self):
        _, c = self.fixture()
        self.assertTrue(c.call('search_rules', dict(query='компьютер'), fixtures.context())['hits'])

    def test_boolean_line_is_not_an_adjacent_document_line(self):
        rules = self.stage_rules(); rules[2]['line'] = True
        _, c = self.fixture(rules)
        self.assertEqual(self.ids(c, 'X-L0002'), ['X-L0001', 'X-L0002'])

    def test_oversized_unterminated_section_cannot_be_silently_truncated(self):
        rules = self.stage_rules()[:2]
        rules.extend(dict(id='X-L%04d' % n, line=n, scope='kp', type='kp_document', text='Условие.')
                     for n in range(3, 40))
        _, c = self.fixture(rules)
        with self.assertRaises(ResearchError): self.ids(c, 'X-L0002')

    def test_finite_budget_is_visible_and_decreases_through_draft_and_review(self):
        f, c = self.fixture([dict(id='R1', text='Наличие неизвестно', active_primary=True)])
        seq = f.sequence(); seen = []
        def model(role, packet, tools):
            seen.append((role, packet['input']['research'].get('call_budget'))); return seq.pop(0)
        out = Pipeline(c, model, max_calls=6).run(fixtures.context())
        self.assertTrue(out['approved'])
        self.assertEqual([b['remaining_including_this'] for _, b in seen], [6, 5, 4, 3, 2, 1])
        self.assertEqual(seen[-1][0], 'review')
        self.assertEqual(seen[-1][1]['minimum_conclusion_calls'], 1)
        self.assertEqual(seen[-2][1]['minimum_conclusion_calls'], 2)

    def test_tools_cannot_expand_budget_or_skip_separate_review(self):
        f, c = self.fixture([dict(id='R1', text='Наличие неизвестно', active_primary=True)])
        calls = []
        def model(role, packet, tools):
            calls.append(role); return dict(kind='tool', name='read_rule', arguments=dict(rule_id='R1'))
        out = Pipeline(c, model, max_calls=2).run(fixtures.context())
        self.assertFalse(out['approved']); self.assertEqual(calls, ['research', 'research'])
        self.assertIsNone(out['draft']); self.assertEqual(out['reason'], 'budget_exhausted')

    def test_latest_budget_survives_exact_native_tool_continuation(self):
        f = continuation.Continuation209Tests(); f.setUp()
        f.responses = [f.call(), f.conclusion()]
        first = dict(call_budget=dict(total=4, remaining_including_this=4, minimum_conclusion_calls=2))
        f.step(evidence=first)
        second = dict(f.result(), call_budget=dict(total=4, remaining_including_this=3, minimum_conclusion_calls=2))
        f.step(evidence=second)
        result = json.loads(f.sent[1]['input'][-1]['output'])
        self.assertEqual(result.get('call_budget'), second['call_budget'])
        shared = json.loads(f.sent[0]['input'][1]['content'][0]['text'])
        dynamic = json.loads(f.sent[0]['input'][2]['content'][0]['text'])
        self.assertNotIn('call_budget', shared['research'])
        self.assertEqual(dynamic.get('call_budget'), first['call_budget'])


if __name__ == '__main__': unittest.main()
