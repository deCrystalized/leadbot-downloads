"""Owner's intake rule and manually checked parts/on-site conversations."""
import json
import unittest
import test_diagnostic_reasoning119 as helpers
import assistant_policy as policy
import contact_facts


def row(body, direction='in', ident='client'):
    return dict(id=ident, body=body, direction=direction)


class ServiceExpectations122Tests(unittest.TestCase):
    setUp = helpers.DiagnosticReasoning119Tests.setUp
    finish = helpers.DiagnosticReasoning119Tests.finish

    def assess(self, text, direction='kp', title='Ремонт ноутбуков'):
        messages = [row(text)]
        known = dict(direction=direction, channel='avito', partner='7', city='Оренбург',
                     title=title, account_name='Учебный мастер')
        return policy.assess(messages, known, contact_facts.collect(messages, known))

    def preview(self, messages, direction='kp', title='Ремонт компьютеров'):
        ctx = dict(convId='synthetic-service-expectations122', city='Оренбург', dir=direction,
                   channel='avito', partner='7', accountTitle='Учебный мастер', origin='С1',
                   itemTitle=title, messages=messages)
        out, code = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertTrue(out.get('pending_model'), out.get('reason'))
        return out, json.loads(out['model_task']['task'])

    def test_unusual_motive_does_not_add_an_approval_or_unrequested_work(self):
        for text, direction, title in [
            ('Переустановите Windows на ноутбуке, чтобы дома быстрее работал Wi-Fi.', 'kp', 'Ремонт ноутбуков'),
            ('Соберите шкаф. Мне кажется, тогда в комнате станет теплее.', 'mnc', 'Сборка мебели'),
            ('Мне нужна только диагностика принтера HP Deskjet 6075 без картриджей, даже если другие мастера считают это бессмысленным.', 'kp', 'Ремонт принтеров')]:
            with self.subTest(text=text):
                out = self.assess(text, direction, title)
                self.assertEqual(out['service']['status'], 'supported')
                self.assertNotIn(out['action'], ['handoff', 'refuse'])
                self.assertIn('OWNER-CLIENT-REPORTED-ACCEPTANCE-20261020', out['rule_ids'])

    def test_actual_prohibited_work_keeps_its_rule(self):
        out = self.assess('На экране телевизора полосы. Хочу ремонт.', title='Ремонт телевизоров')
        self.assertEqual(out['action'], 'refuse')
        self.assertIn('OWNER-TV-BANDS-20261017', out['rule_ids'])

    def test_split_materials_question_keeps_the_safe_answer(self):
        messages = [row('Нужно установить розетки.'), row('Какой адрес?', 'out', 'staff'),
                    row('У вас будет с собой провод метра два?', ident='wire'),
                    row('И розетка', ident='socket'), row('?', ident='question')]
        replies = policy.service_expectation_questions(messages)
        self.assertEqual(replies, ['По материалам смогу сориентировать после осмотра.'])

    def test_no_inventory_inference_from_the_clients_own_parts(self):
        for text in ['Все материалы уже куплены.', 'У меня есть запчасти.', 'Собрать ПК с моими запчастями.',
                     'Другой мастер отказался: у него нет запчастей.']:
            self.assertEqual(policy.service_expectation_questions([row(text)]), [], text)

    def test_address_clarification_does_not_erase_the_materials_answer(self):
        messages = [row('Нужно установить розетки. У вас будет с собой провод?')]
        known = dict(direction='mnc', channel='avito', partner='7', city='Оренбург',
                     title='Услуги электрика', account_name='Учебный мастер')
        facts = contact_facts.collect(messages, known)
        facts['address_needs_confirmation'] = True
        out = policy.assess(messages, known, facts)
        reply = policy.compose_reply(out['forced_reply'], out)
        self.assertIn('По материалам смогу сориентировать после осмотра.', reply)
        self.assertIn('окончательный адрес', reply)
        self.assertEqual(out['action'], 'question')

    def test_an_old_question_does_not_repeat_after_staff_answer(self):
        messages = [row('Запчасти у вас есть?'), row('Уточню после осмотра.', 'out'), row('Удобно завтра.')]
        self.assertEqual(policy.service_expectation_questions(messages), [])

    def test_on_site_question_has_a_useful_answer_before_intake(self):
        out, task = self.preview([row('Мой компьютер не включается. Сможете всё сделать на месте?')])
        self.assertIn('Возможность ремонта на месте определю после осмотра.', task['proposed_reply'])
        candidate = dict(reply=task['decision']['next_question']['question'], needs_operator=False,
                         context_review=dict(last_intent='Ремонт компьютера и вопрос о ремонте на месте',
                                             latest_client_meaning='Клиент спрашивает, можно ли устранить проблему за выезд',
                                             selected_step_fits=True, evidence_ids=['client'],
                                             note='Ответ через осмотр без гарантированного результата, далее нужное уточнение.'))
        final = self.finish(out, candidate)
        self.assertEqual(final['validation'], [])
        self.assertIn('Возможность ремонта на месте определю после осмотра.', final['reply'])
        self.assertFalse(final['needs_operator'])

    def test_inventory_and_even_soft_procurement_promises_are_rejected(self):
        for text in ['Привезу все нужные запчасти.', 'Постараюсь взять провод и розетку.',
                     'Все детали есть у меня.', 'У меня есть нужный герметик.',
                     'Не обещаю ремонт, но возьму материалы.']:
            self.assertIn('unconfirmed_materials_promise', policy.service_expectation_violations(text), text)

    def test_successful_single_visit_is_not_promised(self):
        for text in ['Точно всё починю.', 'На месте отремонтирую.', 'Сделаю за один выезд.',
                     '100% устраню неисправность.']:
            self.assertIn('unconfirmed_repair_outcome', policy.service_expectation_violations(text), text)
        for text in ['Возможность ремонта на месте определю после осмотра.',
                     'По материалам смогу сориентировать после осмотра.',
                     'Не могу гарантировать ремонт за один выезд.',
                     'Какие материалы у вас уже есть?']:
            self.assertEqual(policy.service_expectation_violations(text), [], text)


if __name__ == '__main__':
    unittest.main()
