"""Active callout tariff and observed/unsent boundary, not invented history."""
import unittest

import test_context_grounding110 as fixtures
from test_assistant import context, message


class GroundedPrice111Tests(unittest.TestCase):
    setUp = fixtures.ContextGrounding110Tests.setUp
    prepare = fixtures.ContextGrounding110Tests.prepare
    finish = fixtures.ContextGrounding110Tests.finish
    furniture = fixtures.ContextGrounding110Tests.furniture
    gas = fixtures.ContextGrounding110Tests.gas

    def fee(self, body, partner='7', city='Армавир'):
        return self.app.handle(dict(owner='owner', action='preview', wording_mode='reviewed',
            ctx=context([message(body, mid='client')], dir='mnc', city=city, partner=partner,
                        accountTitle='Григорий МНЧ', itemTitle='Услуги электрика')))[0]

    def test_ordinary_callout_price_is_answered_before_one_scope_question(self):
        out = self.fee('Доброе утро за вызов приехать сколько цена без работы?')
        self.assertEqual(out['action'], 'question')
        self.assertEqual(out['reply'], 'Здравствуйте! Выезд в черте города бесплатный. Что требуется сделать?')
        self.assertIn('DOC-L0757', out['rule_ids'])
        self.assertNotIn('диагностика бесплат', out['reply'])
        self.assertNotIn('1000', out['reply'])
        self.assertFalse(out['auto_enabled'])

    def test_common_callout_wording_preserves_the_same_rule(self):
        for body in ('Выезд бесплатный?', 'За вызов сколько берёте?', 'Вы берете деньги за выезд?',
                     'Сколько будет стоить приезд без работы?'):
            with self.subTest(body=body):
                out = self.fee(body)
                self.assertIn('Выезд в черте города бесплатный.', out['reply'])
                self.assertEqual(out['reply'].count('?'), 1)

    def test_partner723_does_not_transfer_kp_callout_fee_to_mnc(self):
        out = self.fee('За выезд сколько берёте?', partner='723')
        self.assertNotIn('1000 рублей', out['reply'])
        self.assertIn('Выезд в черте города бесплатный.', out['reply'])
        self.assertIn('OWNER-MNC-FREE-CALLOUT-20261021', out['rule_ids'])

    def test_known_city_conflict_does_not_get_a_free_territory_promise(self):
        out = self.fee('Я в Томске, сколько стоит выезд?', city='Омск')
        self.assertEqual(out['action'], 'handoff')
        self.assertFalse(out['reply'])

    def test_actual111_task_places_history_before_unsent_proposal(self):
        _, task = self.prepare(self.furniture())
        keys = list(task)
        self.assertLess(keys.index('conversation'), keys.index('decision'))
        self.assertEqual(task['latest_client_message']['body'], 'Как сфоткают отправлю. Вы берёте такую работу?')
        self.assertEqual(task['review_boundary']['observed_history'], 'conversation')
        self.assertEqual(task['review_boundary']['unsent_proposal'], ['decision', 'proposed_reply'])

    def test_latest_literal_summary_is_bound_to_the_actual_quote(self):
        _, task = self.prepare(self.gas(), 'bt', 'Ремонт духовок', 'Саранск')
        self.assertEqual(task['output_contract']['fixed_latest_client_meaning'],
                         'Сообщает: «У него нет запчастей». Новый запрос и исход обращения не подтверждены.')
        self.assertIn('contractor_refusal', task['literal_third_party_report']['does_not_establish'])

    def test_actual110_inferred_refusal_is_rejected_without_rewriting_it(self):
        out, task = self.prepare(self.gas(), 'bt', 'Ремонт духовок', 'Саранск')
        result = self.finish(out, task, 'Сообщить, что предыдущий специалист отказался из-за отсутствия запчастей.',
                             'Фиксированный отказ по газовому профилю уместен.', intent='Специалист для газовой плиты')
        self.assertEqual(result['action'], 'handoff')
        self.assertIn('unconfirmed_third_party_outcome', result['validation'])
        self.assertFalse(result['reply'])

    def test_true_literal_summary_still_allows_the_rule_based_gas_reply(self):
        out, task = self.prepare(self.gas(), 'bt', 'Ремонт духовок', 'Саранск')
        result = self.finish(out, task, task['output_contract']['fixed_latest_client_meaning'],
                             'Отказ по газовому профилю остаётся уместным.', intent='Ранее спрашивал о специалисте для газовой плиты')
        self.assertTrue(result['reply'])
        self.assertEqual(result['validation'], [])

    def test_canonical_meaning_cannot_hide_fabricated_outcome_in_note(self):
        out, task = self.prepare(self.gas(), 'bt', 'Ремонт духовок', 'Саранск')
        result = self.finish(out, task, task['output_contract']['fixed_latest_client_meaning'],
                             'Предыдущий мастер отказался из-за отсутствия деталей.', intent='Газовая плита')
        self.assertFalse(result['reply'])
        self.assertIn('unconfirmed_third_party_outcome', result['validation'])

    def test_uncertain_outcome_is_not_mistaken_for_a_confirmed_refusal(self):
        out, task = self.prepare(self.gas(), 'bt', 'Ремонт духовок', 'Саранск')
        result = self.finish(out, task, task['output_contract']['fixed_latest_client_meaning'],
                             'Неизвестно, мастер отказался или ждёт детали; наш профиль исключает газ.', intent='Ранее спрашивал о специалисте')
        self.assertTrue(result['reply'])
        self.assertEqual(result['validation'], [])

    def test_short_actual110_past_proposal_claim_is_rejected(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task, 'Клиент обещает фото и спрашивает, берём ли ремонт.',
                             'Сотрудник пропустил промежуточные шаги и сразу предложил следующий стандартный вопрос.')
        self.assertEqual(result['action'], 'handoff')
        self.assertIn('unobserved_selected_question', result['validation'])

    def test_actual_other_past_question_remains_valid(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task, 'Клиент описал стенки шкафа и обещал фото.',
                             'Сотрудник попросил фото; предлагаемый вопрос уточнит наличие материалов.')
        self.assertTrue(result['reply'])
        self.assertEqual(result['validation'], [])


if __name__ == '__main__':
    unittest.main()
