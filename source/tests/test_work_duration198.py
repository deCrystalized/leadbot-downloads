"""Owner forbids forecasting work duration; arrival is a separate question."""
import copy
import json
import unittest
from datetime import datetime
from unittest.mock import patch

import assistant_policy as policy
import assistant_prices
import extension_assistant as ext
import test_question_roles185 as previous


def row(body,mid,direction='in',**extra):
    value=dict(id=mid,body=body,direction=direction,
               sender_type='client' if direction=='in' else 'operator')
    value.update(extra)
    return value


class WorkDuration198Tests(unittest.TestCase):
    setUp=previous.QuestionRoles185Tests.setUp

    def preview(self,last='Сколько времени займёт работа?',messages=None,**extra):
        self.sequence=getattr(self,'sequence',0)+1
        ctx=dict(convId='synthetic-duration198-'+str(self.sequence),dir='mnc',city='Тула',channel='avito',
                 partner='7',origin='С77',accountTitle='Учебный МНЧ',itemTitle='Сборка мебели',
                 messages=messages or [row('Нужно собрать шкаф','job'),row(last,'latest')])
        ctx.update(extra)
        out,status=self.app.handle(dict(owner='question185-owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(status,200);self.assertFalse(out['auto_enabled']);self.assertFalse(out['lead']['can_create_automatically'])
        return out,json.loads(out['model_task']['task'])if out.get('model_task')else None

    def proposal(self,last='Сколько времени займёт работа?',**kwargs):
        out,task=self.preview(last,**kwargs)
        return out,task,task['proposed_reply']if task else out.get('reply','')

    def test_explicit_work_duration_has_no_estimate_or_future_estimate_promise(self):
        out,task,reply=self.proposal()
        self.assertIn(policy.WORK_DURATION_REPLY,reply)
        self.assertIn(policy.WORK_DURATION_RULE,out['rule_ids'])
        self.assertNotRegex(reply,r'\d|сориентир|быстро|один визит|в день обращения')
        self.assertFalse(out['visit_offer']);self.assertFalse(out['accepted_visit'])

    def test_duration_variants_and_deadlines_do_not_get_a_completion_promise(self):
        for text in ['И сколько по времени будет установка?','Сколько займёт сборка?',
                     'Как долго будет ремонт?','За сколько сможете собрать?',
                     'Соберёте до 15:00?','За час управитесь?','Управитесь за час?']:
            with self.subTest(text=text):
                out,task,reply=self.proposal(text);self.assertIn(policy.WORK_DURATION_REPLY,reply)
                self.assertFalse(out['visit_offer']);self.assertNotIn('15:00',reply)

    def test_duration_reply_can_continue_one_required_qualification(self):
        out,task,reply=self.proposal()
        self.assertIn('Схема',reply);self.assertLessEqual(reply.count('?'),1)
        self.assertEqual(task['planned_question_roles']['status'],'planned_not_sent')

    def test_same_duration_rule_applies_to_kp(self):
        out,task,reply=self.proposal(messages=[row('Принтер Canon LBP2900 не печатает','job'),
            row('Сколько по времени займёт ремонт?','latest')],dir='kp',itemTitle='Ремонт принтеров',accountTitle='Учебный КП')
        self.assertIn(policy.WORK_DURATION_REPLY,reply);self.assertFalse(out['visit_offer'])

    def test_ambiguous_timing_is_clarified_without_guessing_duration_or_arrival(self):
        for text in ['И что по срокам?','Какие сроки?','А по срокам?','Сроки?']:
            with self.subTest(text=text):
                out,task,reply=self.proposal(text)
                self.assertEqual(task['decision']['next_question']['kind'],'timing_scope')
                self.assertEqual(reply,'Здравствуйте! Вы про время приезда или сколько займёт работа?')
                self.assertFalse(out['visit_offer']);self.assertFalse(out['accepted_visit'])

    def test_actual542_time_question_preserves_address_and_provider_unknown(self):
        h=[row('Мне нужно само подключение интернета в квартиру','job'),row('Роутер имеется','router'),
           row('Интернет уже проведён?','q','out',sender_type='bot'),row('Секунду','pause'),
           row('Адрес подскажите?','addressq','out'),row('Улица Каяни 17/6','address'),row('И что по срокам?','time')]
        out,task,reply=self.proposal(messages=h,dir='kp',city='Ростов-на-Дону',itemTitle='Настройка роутера',accountTitle='Учебный КП')
        self.assertEqual(reply,'Вы про время приезда или сколько займёт работа?')
        self.assertEqual(out['lead']['address']['building'],'17/6');self.assertFalse(out['visit_offer'])
        self.assertEqual(task['decision']['next_question']['source_question']['message_id'],'time')
        self.assertNotEqual(out['qualification']['internet']['status'],'answered')

    def test_explicit_arrival_keeps_existing_normative_route(self):
        with patch.object(policy,'_visit_question_now',lambda zone:datetime(2026,10,24,13,20,tzinfo=zone)):
            out,task,reply=self.proposal(messages=[row('Принтер Canon MG2540S жуёт бумагу и скрипит.','job'),
                row('Куда подъехать?','where','out'),row('Шехурдина 8а, 91','address'),
                row('Когда сможете приехать?','time')],dir='kp',city='Саратов',itemTitle='Ремонт принтеров',accountTitle='Учебный КП')
        self.assertNotIn(policy.WORK_DURATION_RULE,out['rule_ids'])
        self.assertNotIn(policy.WORK_DURATION_REPLY,reply)
        self.assertTrue(out['visit_offer'] or out['action']=='handoff')

    def test_arrival_does_not_establish_duration(self):
        h=[row('Нужно собрать шкаф','job'),row('Могу через час-полтора','arrival','out'),
           row('Да. А сколько по времени займёт работа?','duration')]
        out,task,reply=self.proposal(messages=h)
        self.assertIn(policy.WORK_DURATION_REPLY,reply);self.assertNotIn('полтора',reply)

    def test_observed_short_approximate_followup_keeps_no_estimate(self):
        h=[row('Сколько по времени собирать шкаф?','duration'),
           row('Постараюсь всё быстро сделать','answer','out'),row('Примерно?','followup')]
        evidence=policy._current_work_time_question(h)
        self.assertEqual(evidence['kind'],'duration');self.assertEqual(evidence['previous_client_message_id'],'duration')
        out,task,reply=self.proposal(messages=h);self.assertIn(policy.WORK_DURATION_REPLY,reply)

    def test_approximate_price_followup_is_not_work_duration(self):
        h=[row('Сколько стоит собрать шкаф?','price'),row('От1500 рублей','quote','out'),row('Примерно?','followup')]
        self.assertIsNone(policy._current_work_time_question(h))

    def test_unsent_or_system_answer_does_not_bind_approximate_followup(self):
        for extra in [dict(out_pending=True),dict(delivery_status='failed'),dict(sender_type='system')]:
            h=[row('Сколько времени займёт сборка?','duration'),row('По времени точно не скажу','answer','out',**extra),row('Примерно?','followup')]
            evidence=policy._current_work_time_question(h)
            self.assertFalse(evidence and evidence.get('previous_client_message_id'))

    def test_failed_prior_client_question_does_not_bind_followup(self):
        h=[row('Сколько времени займёт сборка?','duration',delivery_status='failed'),
           row('По времени точно не скажу','answer','out'),row('Примерно?','followup')]
        self.assertIsNone(policy._current_work_time_question(h))

    def test_price_and_duration_both_remain_in_actual_proposal(self):
        out,task,reply=self.proposal('Сколько стоит сборка и сколько времени займёт?')
        self.assertIn(policy.WORK_DURATION_REPLY,reply)
        self.assertRegex(reply,r'стоим|цен|осмотр|руб')

    def test_literal_quote_is_not_a_new_timing_question(self):
        for text in ['Сосед спросил: «Сколько времени займёт работа?»',
                     'Сотрудник написал сколько времени займёт ремонт',
                     'Не спрашиваю сколько времени займёт ремонт',
                     'Если делать ремонт, сколько времени займёт?']:
            self.assertFalse(policy._work_time_kind(text))

    def test_own_duration_question_after_quote_remains_a_question(self):
        self.assertEqual(policy._work_time_kind('Сосед сказал: «час». Сколько времени займёт работа?'),'duration')

    def test_callback_delivery_warranty_and_past_work_are_other_subjects(self):
        for text in ['Что по срокам звонка?','Какие сроки гарантии?',
                     'Сколько времени займёт доставка шкафа?',
                     'Вчера мастер работал час. Не спрашиваю про сроки.',
                     'Срок договора истёк','Сколько времени нужно до приезда?',
                     'Как долго вы этим занимаетесь?',
                     'Сколько времени служит картридж?',
                     'Сколько времени мастер был у клиента?']:
            self.assertFalse(policy._work_time_kind(text))

    def test_staff_system_or_failed_timing_is_not_client_evidence(self):
        for extra in [dict(direction='out'),dict(sender_type='system'),dict(delivery_status='failed')]:
            m=row('Сколько времени займёт работа?','time');m.update(extra)
            self.assertIsNone(policy._current_work_time_question([m]))

    def test_new_enquiry_does_not_inherit_duration_from_old_job(self):
        h=[row('Сколько времени займёт сборка шкафа?','old'),
           row('Новый заказ: установить Windows на ноутбук','new')]
        self.assertIsNone(policy._current_work_time_question(h))

    def test_independent_model_veto_is_preserved(self):
        out,task=self.preview('Какие сроки?');candidate=dict(reply='',needs_operator=True,context_review=dict(
            last_intent='Клиенту нужна сборка шкафа; спрашивает о сроках.',latest_client_meaning='Спрашивает о сроках.',
            selected_step_fits=False,evidence_ids=['latest'],note='Передаю оператору при противоречащих условиях.'))
        original=copy.deepcopy(candidate);review,status,errors=ext._context_review(candidate,task)
        self.assertEqual(errors,['model_context_mismatch']);self.assertFalse(review['selected_step_fits']);self.assertEqual(candidate,original)

    def test_no_new_receipt_and_no_fixed_client_meaning(self):
        out,task=self.preview('Какие сроки?')
        self.assertNotIn('fixed_latest_client_meaning',task['output_contract'])
        self.assertNotIn('work_duration_review',task['output_contract']['context_review_fields'])

    def test_unlisted_or_prohibited_work_is_not_accepted_by_duration_answer(self):
        for job in ['Протечку в насосе устраняете или предлагаете сразу замену?','Нужно отремонтировать газовую плиту']:
            out,task,reply=self.proposal(messages=[row(job,'job'),row('Сколько времени займёт работа?','duration')],itemTitle='Сантехника')
            self.assertIn(out['action'],('handoff','refuse'))
            self.assertNotIn(policy.WORK_DURATION_RULE,out['rule_ids'])
            if out['action']=='handoff':
                self.assertIsNone(task)
            else:
                self.assertEqual(out['service']['status'],'refuse')
                self.assertEqual(task['fixed_reply'],'Здравствуйте! К сожалению, с газовым оборудованием не работаю.')

    def test_generic_leak_qualifier_does_not_become_acceptance_due_to_duration(self):
        out,task,reply=self.proposal(messages=[row('Нужно устранить течь в насосе','job'),
            row('Сколько времени займёт работа?','duration')],itemTitle='Сантехника')
        self.assertEqual(out['service']['status'],'unknown')
        self.assertNotIn(policy.WORK_DURATION_RULE,out['rule_ids'])
        self.assertFalse(out['accepted_visit']);self.assertFalse(out['lead']['can_create_automatically'])

    def test_explicit_price_is_not_erased_by_separate_duration_question(self):
        self.assertTrue(assistant_prices.asks('Сколько стоит сборка и сколько времени займёт?'))
        self.assertTrue(assistant_prices.asks('Сколько будет стоить ремонт? Как долго он продлится?'))
        for text in ['Сколько по времени займёт работа?',
                     'Сосед спросил: «сколько стоит?». Сколько времени займёт работа?',
                     'Не спрашиваю сколько стоит, сколько времени займёт работа?']:
            self.assertFalse(assistant_prices.asks(text))
