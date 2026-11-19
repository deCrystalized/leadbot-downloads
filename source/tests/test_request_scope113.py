"""Service questions and named operations must retain their actual subjects."""
import unittest

import test_context_grounding110 as fixtures
from test_assistant import context, message


class RequestScope113Tests(unittest.TestCase):
    setUp = fixtures.ContextGrounding110Tests.setUp
    prepare = fixtures.ContextGrounding110Tests.prepare
    finish = fixtures.ContextGrounding110Tests.finish
    furniture = fixtures.ContextGrounding110Tests.furniture
    def reviewed(self, text):
        return self.app.handle(dict(owner='owner', action='preview', wording_mode='reviewed',
            ctx=context([message(text)], dir='mnc', city='Чебоксары',
                        itemTitle='Ремонт мебели')))[0]

    def test_capability_is_answered_before_missing_materials_without_manufacture_promise(self):
        out = self.reviewed('Можно ли заменить разбухшие боковые стенки шкафа?')
        self.assertIn('Готовые детали заменить можно.', out['reply'])
        self.assertRegex(out['reply'].lower(), r'материал.*есть')
        self.assertNotIn('изготов', out['reply'].lower())
        self.assertNotIn('реставр', out['reply'].lower())
        self.assertFalse(out['auto_enabled'])

    def test_not_every_furniture_message_needs_an_unasked_capability_answer(self):
        out = self.reviewed('Нужно заменить разбухшие боковые стенки шкафа.')
        self.assertNotIn('Готовые детали заменить можно.', out.get('reply', ''))

    def test_common_replacement_and_capability_wording_keeps_the_same_scope(self):
        for text in ('Можете поменять боковины шкафа?', 'Вы такое делаете? Нужно заменить стенки шкафа.',
                     'Здравствуйте. Подскажите пожалуйста, можно ли заменить боковые стенки шкафа?'):
            with self.subTest(text=text):
                self.assertIn('Готовые детали заменить можно.', self.reviewed(text).get('reply', ''))

    def test_reported_business_statement_is_not_a_new_capability_question(self):
        out = self.reviewed('Мне сказали, что вы выполняете замену деталей шкафа.')
        self.assertNotIn('Готовые детали заменить можно.', out.get('reply', ''))

    def test_repeated_can_question_after_details_does_not_lose_the_question_subject(self):
        rows = self.furniture() + [message('Разбухшие детали заменить можно на новые?', mid='can')]
        out = self.app.handle(dict(owner='owner', action='preview', wording_mode='reviewed',
            ctx=context(rows, dir='mnc', city='Чебоксары', itemTitle='Ремонт мебели')))[0]
        self.assertIn('Готовые детали заменить можно.', out.get('reply', ''))

    def test_real_special_jobs_keep_operator_gate(self):
        for text in ('Реставрировать старый шкаф сможете?', 'Сделаете новые детали шкафа на заказ? Нужно изготовить боковины.',
                     'Вы заменяете стекло на шкафу?', 'Можете заменить пружины в кровати?'):
            with self.subTest(text=text):
                out = self.reviewed(text)
                self.assertFalse(out.get('reply'))
                self.assertEqual(out['action'], 'handoff')

    def test_only_swelling_does_not_turn_into_a_confirmed_replacement(self):
        out = self.reviewed('У шкафа разбухли стенки. Вы такое ремонтируете?')
        self.assertNotIn('Готовые детали заменить можно.', out.get('reply', ''))

    def test_new_task_binds_operation_and_capability_subject_to_client_evidence(self):
        _, task = self.prepare(self.furniture())
        scope = task['client_request_boundaries']
        self.assertIn('job', scope['evidence_ids'])
        self.assertEqual(scope['operation'], 'furniture_parts_replacement')
        self.assertIn('restoration', scope['does_not_establish'])
        self.assertIn('manufacture', scope['does_not_establish'])
        self.assertIn('DOC-L0459', [s['id'] for s in task['primary_sources']])
        question = task['service_capability_question']
        self.assertEqual(question['questioner'], 'client')
        self.assertEqual(question['respondent'], 'service')
        self.assertEqual(question['evidence_id'], 'client')
        self.assertLess(list(task).index('client_request_boundaries'), list(task).index('decision'))

    def test_actual112_restoration_label_is_not_accepted_as_repair_evidence(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task,
            'Клиент уточняет, делаете ли вы такую работу, и сообщает, что отошлет фото, когда соседи сделают',
            'Вопрос о материалах логично задать после того, как клиент подтвердит возможность такой работы',
            intent='Узнать, выполняется ли у вас реставрация мебели после потопа')
        self.assertFalse(result['reply'])
        self.assertIn('unsupported_service_kind_in_context', result['validation'])

    def test_customer_cannot_confirm_the_services_own_capability(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task, 'Клиент спрашивает, берём ли замену деталей.',
            'Вопрос о материалах зададим после того, как клиент подтвердит возможность такой работы.')
        self.assertFalse(result['reply'])
        self.assertIn('service_capability_actor_reversed', result['validation'])

    def test_explicit_question_stays_a_question_and_ordinary_repair_can_continue(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task, 'Обещает фото и спрашивает о замене боковых стенок шкафа.',
            'Ответ про замену готовых деталей и вопрос о материалах уместны.', intent='Заменить повреждённые детали шкафа')
        self.assertTrue(result['reply'])
        self.assertEqual(result['validation'], [])

    def test_negated_special_category_is_not_treated_as_a_requested_operation(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task, 'Просит замену стенок, не реставрацию.',
            'Готовые детали можно заменить; изготовление не подтверждено.', intent='Ремонт шкафа')
        self.assertTrue(result['reply'])
        self.assertEqual(result['validation'], [])

    def test_true_general_rule_in_note_does_not_relabel_the_client_request(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task, 'Спрашивает о замене стенок шкафа и обещает фото.',
            'Реставрация требует согласования; здесь запрошена замена готовых деталей.', intent='Ремонт шкафа')
        self.assertTrue(result['reply'])
        self.assertEqual(result['validation'], [])

    def test_promised_evening_photos_and_acknowledgment_still_wait(self):
        rows = self.furniture() + [message('Хорошо, вечером отправлю фотографии.', mid='later'),
            dict(message('Буду ждать', 'out', 'wait'), sender_type='operator'),
            message('Договорились', mid='ack')]
        out = self.app.handle(dict(owner='owner', action='preview', wording_mode='reviewed',
            ctx=context(rows, dir='mnc', city='Чебоксары', itemTitle='Ремонт мебели')))[0]
        self.assertFalse(out['reply'])
        self.assertEqual(out['action'], 'wait')


if __name__ == '__main__':
    unittest.main()
