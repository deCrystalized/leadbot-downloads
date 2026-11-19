"""Observed109 model errors and causal controls for real/failed/planned speech."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from assistant_store import Store
from extension_assistant import Assistant
import assistant_catalog as catalog
import assistant_policy as policy
from test_assistant import context, message
from test_history_intake106 import assess, known, rows


class ContextGrounding110Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name+'/db'))

    def prepare(self, messages, direction='mnc', title='Ремонт мебели', city='Чебоксары'):
        out, code = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review',
            ctx=context(messages, dir=direction, city=city, itemTitle=title)))
        self.assertEqual(code, 200)
        self.assertTrue(out.get('pending_model'), out.get('reason'))
        return out, json.loads(out['model_task']['task'])

    def finish(self, out, task, meaning, note, intent='Ремонт шкафа'):
        candidate = dict(reply=task.get('fixed_reply') or task['decision']['next_question']['question'],
            needs_operator=False, context_review=dict(last_intent=intent, latest_client_meaning=meaning,
            selected_step_fits=True, evidence_ids=[task['latest_client_message']['evidence_id']], note=note))
        final, code = self.app.handle(dict(owner='owner', action='finalize', request_id=out['request_id'],
            revision=out['revision'], candidate=candidate))
        self.assertEqual(code, 200)
        self.assertFalse(final['auto_enabled'])
        return final

    def furniture(self, staff='Фото есть? Пришлите, пожалуйста', delivery='delivered'):
        return [message('Можно заменить разбухшие боковые стенки шкафа?', mid='job'),
            dict(message(staff, 'out', 'staff'), sender_type='operator', delivery_status=delivery),
            message('Как сфоткают отправлю. Вы берёте такую работу?', mid='client')]

    def test_other_real_question_does_not_prove_the_materials_question_was_asked(self):
        _, task = self.prepare(self.furniture())
        self.assertTrue(task['history_coverage']['prior_staff_speech_exists'])
        self.assertEqual(task['selected_question_history']['kind'], 'materials')
        self.assertEqual(task['selected_question_history']['observed_question_ids'], [])

    def test_actual109_transition_claim_is_blocked_even_with_other_staff_speech(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task, 'Клиент обещает фото позже и спрашивает о ремонте.',
            'Вопрос о материалах логично задать после фото, однако сотрудник перешёл к нему раньше.')
        self.assertEqual(result['action'], 'handoff')
        self.assertIn('unobserved_selected_question', result['validation'])

    def test_fabricated_same_topic_past_question_is_blocked(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task, 'Клиент описал боковые стенки.',
                             'Сотрудник уже задал вопрос о материалах.')
        self.assertFalse(result['reply'])
        self.assertIn('unobserved_selected_question', result['validation'])

    def test_true_photo_history_and_future_material_question_are_allowed(self):
        out, task = self.prepare(self.furniture())
        result = self.finish(out, task, 'Клиент обещает фото и спрашивает о ремонте.',
                             'Сотрудник попросил фото; следующий вопрос уточнит материалы.')
        self.assertTrue(result['reply'])
        self.assertEqual(result['validation'], [])

    def test_actual_delivered_same_question_can_be_described_as_past(self):
        out, task = self.prepare(self.furniture('Материалы и комплектующие есть?'))
        self.assertEqual(task['selected_question_history']['observed_question_ids'], ['staff'])
        result = self.finish(out, task, 'Клиент не ответил на вопрос о материалах.',
                             'Сотрудник уже задал вопрос о материалах.')
        self.assertTrue(result['reply'])
        self.assertNotIn('unobserved_selected_question', result['validation'])

    def test_failed_same_question_is_not_observed(self):
        out, task = self.prepare(self.furniture('Материалы и комплектующие есть?', 'failed'))
        self.assertEqual(task['selected_question_history']['observed_question_ids'], [])
        result = self.finish(out, task, 'Клиент описал боковые стенки.',
                             'Сотрудник уже уточнил материалы.')
        self.assertIn('unobserved_selected_question', result['validation'])

    def gas(self, latest='У него нет запчастей', prior='Не знаю'):
        return [message('Газовая плита, сам срабатывает поджиг', mid='job'),
            dict(message('С газовым оборудованием не работаю.', 'out', 'refusal'), sender_type='operator'),
            message('А какого мастера мне искать?', mid='referral'),
            dict(message(prior, 'out', 'staff'), sender_type='operator'), message(latest, mid='client')]

    def test_literal_third_party_stock_report_does_not_establish_new_search(self):
        _, task = self.prepare(self.gas(), 'bt', 'Ремонт духовок', 'Саранск')
        limits = task['literal_third_party_report']
        self.assertEqual(limits['quote'], 'У него нет запчастей')
        self.assertFalse(limits['new_request_confirmed'])
        self.assertFalse(limits['referent_confirmed'])

    def test_actual109_invented_alternative_master_request_is_blocked(self):
        out, task = self.prepare(self.gas(), 'bt', 'Ремонт духовок', 'Саранск')
        result = self.finish(out, task,
            'Клиент сообщает, что предыдущий специалист не имеет нужных запчастей, и ищет альтернативного мастера с комплектующими.',
            'Фиксируем намерение клиента найти другого мастера с запчастями.', intent='Газовая плита')
        self.assertEqual(result['action'], 'handoff')
        self.assertIn('unconfirmed_third_party_request', result['validation'])

    def test_literal_report_without_new_intent_is_allowed(self):
        out, task = self.prepare(self.gas(), 'bt', 'Ремонт духовок', 'Саранск')
        result = self.finish(out, task, task['output_contract']['fixed_latest_client_meaning'],
            'Новый запрос не подтверждён; газовое оборудование исключено.', intent='Ранее спрашивал специалиста для газовой плиты')
        self.assertEqual(result['action'], 'refuse')
        self.assertTrue(result['reply'])
        self.assertEqual(result['validation'], [])

    def test_explicit_request_for_another_master_is_not_erased(self):
        _, task = self.prepare(self.gas('У него нет запчастей. Подскажите другого мастера?'), 'bt', 'Ремонт духовок', 'Саранск')
        self.assertNotIn('literal_third_party_report', task)

    def test_real_question_about_named_third_party_grounds_the_pronoun(self):
        _, task = self.prepare(self.gas(prior='У мастера есть запчасти?'), 'bt', 'Ремонт духовок', 'Саранск')
        self.assertNotIn('literal_third_party_report', task)

    def test_client_inventory_is_not_an_unnamed_third_party(self):
        _, task = self.prepare(self.gas('У меня нет запчастей'), 'bt', 'Ремонт духовок', 'Саранск')
        self.assertNotIn('literal_third_party_report', task)

    def test_callout_question_explains_why_work_scope_is_needed(self):
        out = assess(rows(('in', 'Доброе утро за вызов приехать сколько цена без работы?')), known('mnc', 'Услуги электрика'))
        self.assertEqual(out['next_question']['kind'], 'problem')
        self.assertIn('Выезд в черте города бесплатный.', out['mandatory_price']['reply'])
        self.assertIn('что требуется сделать', out['next_question']['question'].lower())
        self.assertNotIn('1000', str(out))

    def test_printer_drop_and_already_replaced_cord_are_not_house_wiring(self):
        body = 'Нужен ремонт термопринтера xprinter. При падении повис на кабеле, новый кабель подключили, не включается'
        out = catalog.choose(body, known('kp', 'Ремонт принтеров'))
        self.assertFalse(any(x['id'] == 'electric' for x in out['items']))
        decision = assess(rows(('in', body)), known('kp', 'Ремонт принтеров'))
        self.assertEqual(decision['action'], 'handoff')
        self.assertIn('согласован', decision['reason'])
        self.assertNotIn('Несколько работ', decision['reason'])

    def test_real_independent_wiring_job_is_kept_alongside_printer(self):
        out = catalog.choose('Термопринтер повис на кабеле, новый кабель подключили. Ещё нужно заменить проводку к розетке', known('kp', 'Ремонт принтеров'))
        self.assertTrue(any(x['id'] == 'electric' for x in out['items']))

    def test_unrelated_cable_request_is_not_discarded_as_a_drop(self):
        out = catalog.choose('Термопринтер не включается. Нужно проложить кабель к щитку', known('kp', 'Ремонт принтеров'))
        self.assertTrue(any(x['id'] == 'electric' for x in out['items']))

    def test_ack_after_write_when_returning_waits_before_unknown_geography(self):
        ms = rows(('in', 'Телевизор на Богатырском 60, завтра привезу в Мурино'),
                  ('out', 'Напишите как в Мурино будете'), ('out', 'Обсудим ещё раз'), ('in', 'Ок'))
        self.assertEqual(assess(ms, dict(known('kp', 'Ремонт телевизоров'), city='Новое Девяткино'))['action'], 'wait')

    def test_current_new_question_releases_staff_recontact_wait(self):
        self.assertFalse(policy._conversation_closed('Ок. А сколько будет стоить?', 'Напишите как в Мурино будете'))

    def test_confirmed_staff_visit_is_not_suppressed_by_recontact_phrase(self):
        self.assertFalse(policy._conversation_closed('Ок', 'Я приеду завтра. Напишите когда будете дома'))


if __name__ == '__main__':
    unittest.main()
