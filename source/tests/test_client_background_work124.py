"""Client preparation is not a second job for the service."""
import json
import unittest
import test_diagnostic_reasoning119 as helpers
import contact_facts
import assistant_catalog


def row(text, ident='m1', direction='in'):
    return dict(id=ident, direction=direction, body=text)


class ClientBackground124Tests(unittest.TestCase):
    setUp = helpers.DiagnosticReasoning119Tests.setUp
    finish = helpers.DiagnosticReasoning119Tests.finish

    def prepare(self):
        messages = [row('Клею обои в субботу в зале и нужно сделать добавочные 2 розетки.'),
                    row('Когда вам удобно?', 'staff', 'out'),
                    row('У вас будет с собой провод метра два', 'wire'),
                    row('И розетка', 'socket'), row('?', 'question')]
        ctx = dict(convId='synthetic-client-background124', city='Оренбург', dir='mnc', channel='avito',
                   partner='7', accountTitle='Учебный мастер', origin='С1', itemTitle='Услуги электрика', messages=messages)
        out, code = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertTrue(out.get('pending_model'), out.get('reason'))
        return out, json.loads(out['model_task']['task'])

    def candidate(self, task):
        return dict(reply=task.get('fixed_reply') or task['decision']['next_question']['question'], needs_operator=False,
                    context_review=dict(last_intent='Установить две дополнительные розетки',
                        latest_client_meaning='Клиент ожидает ответа о проводе и розетке у мастера',
                        selected_step_fits=True, evidence_ids=['question'],
                        note='Клиент клеит обои сам; заказ мастеру только на розетки, материалы заранее не обещаем.',
                        background_work_review=dict(evidence_ids=['m1'], actor='client', ordered_from_service=False)))

    def test_shared_facts_keep_background_and_select_only_requested_work(self):
        messages = [row('Клею обои в субботу в зале и нужно сделать добавочные 2 розетки.')]
        facts = contact_facts.collect(messages)
        self.assertEqual(facts['client_background_work'][0]['actor'], 'client')
        text = contact_facts.intent_text(messages[0]['body'], facts)
        self.assertNotIn('Клею обои', text)
        self.assertIn('розетки', text)
        service = assistant_catalog.choose(text, dict(direction='mnc', city='Оренбург'))
        self.assertTrue(service['items'])
        self.assertEqual({x['family'] for x in service['items']}, {'sockets'})
        self.assertTrue(any('Самостоятельная работа клиента' in x for x in facts['comment_lines']))

    def test_service_request_and_later_addition_are_never_discarded(self):
        for texts in [['Нужно поклеить обои и сделать розетки.'],
                      ['Я не буду клеить обои сам. Поклейте обои.'],
                      ['Я хочу, чтобы вы поклеили обои.'],
                      ['Клею обои сам. Нужны розетки.', 'Передумал: поклейте обои тоже.']]:
            self.assertEqual(contact_facts.client_background_work([row(t, str(i)) for i,t in enumerate(texts)]), [])

    def test_street_expansion_does_not_invent_an_address_change(self):
        for a, b, same in [('ул.Твардовского','ул Твардовского',True),
                           ('ул.Ленина','улица Ленина',True),
                           ('Улан-Удэнская','Лан-Удэнская',False),
                           ('ул.Ленина','ул Ленская',False)]:
            self.assertEqual(contact_facts._same_street(a,b),same)
        messages = [row('Г.Балашиха ул.Твардовского'), row('Г.Балашиха ул.Твардовского д18 кв165','full')]
        facts = contact_facts.collect(messages, dict(direction='mnc',city='Балашиха'))
        self.assertFalse(facts['address_needs_confirmation'])
        self.assertEqual(facts['address']['building'],'18')
        self.assertEqual(facts['address']['office'],'165')

    def test_the_only_object_anchor_is_preserved_for_its_repair(self):
        messages = [row('Я сам поклеил обои, но они отходят. Нужен ремонт.')]
        facts = contact_facts.collect(messages)
        self.assertFalse(facts['client_background_work'][0]['exclude_from_service_selection'])
        self.assertIn('обои', contact_facts.intent_text(messages[0]['body'], facts))

    def test_fragment_and_actor_are_bound_to_observed_messages(self):
        out, task = self.prepare()
        self.assertEqual([m['evidence_id'] for m in task['latest_client_fragment_context']['messages']], ['wire','socket','question'])
        self.assertEqual(task['latest_client_fragment_context']['question_topic'], 'materials_inventory')
        self.assertEqual(task['client_background_work'][0]['evidence_id'], 'm1')
        proof = out['model_task']['response_format']['schema']['properties']['context_review']['properties']['background_work_review']
        self.assertEqual(proof['properties']['ordered_from_service']['enum'], [False])

    def test_positive_real_finalize_is_useful_and_does_not_handoff(self):
        out, task = self.prepare()
        final = self.finish(out, self.candidate(task))
        self.assertEqual(final['validation'], [])
        self.assertFalse(final['needs_operator'])
        self.assertIn('По материалам смогу сориентировать после осмотра.', final['reply'])

    def test_original_wrong_order_is_rejected_even_with_correct_metadata(self):
        out, task = self.prepare()
        value = self.candidate(task)
        value['context_review']['last_intent'] = 'Запрос установки двух дополнительных розеток с клеением обоев'
        self.assertIn('client_background_work_added_to_order', self.finish(out, value)['validation'])

    def test_future_address_question_is_not_the_clients_materials_question(self):
        out, task = self.prepare()
        value = self.candidate(task)
        value['context_review']['latest_client_meaning'] = 'Знак вопроса означает ожидание уточнения адреса и наличия материалов'
        self.assertIn('future_address_question_used_as_client_fragment', self.finish(out, value)['validation'])

    def test_proof_cannot_turn_client_work_into_service_order(self):
        for field, wrong in [('actor','service'), ('ordered_from_service',True), ('evidence_ids',['wire'])]:
            with self.subTest(field=field):
                self.setUp()
                out, task = self.prepare()
                value = self.candidate(task)
                value['context_review']['background_work_review'][field] = wrong
                self.assertIn('background_work_review_mismatch', self.finish(out,value)['validation'])


if __name__ == '__main__':
    unittest.main()
