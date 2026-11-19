"""A service's unsent qualification is not a customer's information request."""
import copy
import json
import unittest
import extension_assistant as ext
import test_native_wording209 as fixture


def task(kind='place', body='Нужно собрать комод. Схема есть, детали в наличии.'):
    return dict(planned_question_roles=dict(qualification_kind=kind,questioner='service',respondent='client',status='planned_not_sent'),
                conversation=[dict(id='client',direction='in',speaker_role='client',sender_type='client',body=body)])


class SourceRoles210Tests(unittest.TestCase):
    def test_place_query_transfer_is_rejected_in_all_free_fields(self):
        for key in ('last_intent','latest_client_meaning','note','reply'):
            review=dict(last_intent='Сборка комода');review[key]='Клиент уточняет расположение места сборки комода'
            self.assertTrue(ext._planned_question_as_client_goal(review,task()),key)

    def test_information_goals_cover_ordinary_qualification_topics(self):
        cases=[('place','Узнать тип помещения'),('address','Запрос информации об адресе'),
               ('wall','Клиент уточняет материал стен'),('room','Клиент спрашивает о кухне или ванной'),
               ('model','Клиент хочет узнать марку и модель'),('volume','Уточнить объём работ'),
               ('client_name','Узнать имя'),('decision_maker','Клиент уточняет, кто принимает решение и оплачивает'),
               ('visit_time','Клиент интересуется временем приезда'),('printer_connection','Клиент уточняет источник печати')]
        for kind,value in cases:
            with self.subTest(kind=kind):self.assertTrue(ext._planned_question_as_client_goal(dict(last_intent=value),task(kind)))

    def test_real_customer_questions_on_the_same_topics_remain_allowed(self):
        cases=[('place','В каком помещении вы работаете?','Клиент уточняет тип помещения'),
               ('address','Дайте ваш адрес','Узнать адрес'),('wall','Материал стен имеет значение?','Уточнить материал стен'),
               ('model','С какой моделью вы работаете?','Клиент уточняет модель'),
               ('volume','Какой объём работ сможете сделать?','Узнать объём работ'),
               ('client_name','Как ваше имя?','Узнать имя'),
               ('decision_maker','Кто принимает решение об оплате?','Клиент уточняет, кто принимает решение и оплачивает'),
               ('visit_time','Когда сможете приехать?','Узнать время приезда'),
               ('printer_connection','С какого устройства можно печатать?','Уточнить источник печати')]
        for kind,body,value in cases:
            with self.subTest(kind=kind):self.assertFalse(ext._planned_question_as_client_goal(dict(last_intent=value),task(kind,body)))

    def test_an_answer_about_place_is_not_a_customer_question_about_place(self):
        t=task(body='В квартире.')
        t['conversation'].insert(0,dict(id='staff',direction='out',speaker_role='staff',sender_type='operator',body='Где будут работы?',delivery_status='delivered'))
        self.assertTrue(ext._planned_question_as_client_goal(dict(latest_client_meaning='Клиент уточняет тип помещения'),t))
        self.assertFalse(ext._planned_question_as_client_goal(dict(latest_client_meaning='Сообщил, что работы нужны в квартире.'),t))

    def test_service_note_can_state_what_is_still_unknown(self):
        for note in ('Сервису нужно уточнить место работ.', 'Нужно уточнить тип помещения перед оформлением.',
                     'Клиент ждёт сборку, сервис уточнит место проведения работ.'):
            self.assertFalse(ext._planned_question_as_client_goal(dict(last_intent='Сборка комода',note=note),task()),note)

    def test_nearest_actor_keeps_a_service_explanation_separate(self):
        review=dict(last_intent='Сборка комода',note='Клиент ждёт сборку, а сервис хочет узнать тип помещения.')
        self.assertFalse(ext._planned_question_as_client_goal(review,task()))

    def test_negative_and_explicitly_hypothetical_bad_summary_are_not_assertions(self):
        for text in ('Не цель клиента — узнать место работ.',
                     'Клиент не уточняет место проведения работ.',
                     'Нельзя писать «Клиент уточняет место сборки», это неверный пересказ.',
                     'Если написать «Клиент уточняет тип помещения», это будет ошибкой.'):
            self.assertFalse(ext._planned_question_as_client_goal(dict(last_intent='Сборка комода',note=text),task()),text)

    def test_quoting_an_asserted_wrong_summary_without_a_disclaimer_is_not_a_loophole(self):
        self.assertTrue(ext._planned_question_as_client_goal(dict(latest_client_meaning='«Клиент уточняет место сборки»'),task()))

    def test_roles_delivery_quotes_and_foreign_report_do_not_supply_client_question(self):
        for change in ('staff','system','failed','pending','quote','report','hypothesis'):
            t=task(body='Какое место проведения работ?')
            row=t['conversation'][0]
            if change in ('staff','system'):row['speaker_role']=change
            elif change in ('failed','pending'):row['delivery_status']=change
            elif change=='quote':row['body']='«Какое место проведения работ?»'
            elif change=='report':row['body']='Сосед спросил, какое место проведения работ?'
            else:row['body']='Если понадобится, какое место проведения работ?'
            self.assertTrue(ext._planned_question_as_client_goal(dict(last_intent='Узнать место проведения работ'),t),change)

    def test_old_customer_question_is_not_latest_message_meaning(self):
        t=task(body='Какой тип помещения вы обслуживаете?')
        t['conversation'].append(dict(id='last',direction='in',speaker_role='client',sender_type='client',body='Схема сборки есть.'))
        self.assertTrue(ext._planned_question_as_client_goal(dict(latest_client_meaning='Клиент уточняет тип помещения'),t))
        self.assertFalse(ext._planned_question_as_client_goal(dict(last_intent='Узнать тип помещения'),t))

    def test_new_enquiry_removes_old_question_authority(self):
        t=task(body='Какой тип помещения вы обслуживаете?')
        t['conversation'].append(dict(id='last',direction='in',speaker_role='client',sender_type='client',body='Новая заявка: собрать шкаф.'))
        self.assertTrue(ext._planned_question_as_client_goal(dict(last_intent='Узнать тип помещения'),t))

    def test_real_other_question_and_literal_work_goal_are_not_rejected(self):
        for value in ('Сборка комода', 'Узнать стоимость сборки', 'Передать адрес для сборки',
                      'Клиент сообщил адрес и телефон для сборки.'):
            self.assertFalse(ext._planned_question_as_client_goal(dict(last_intent=value),task()),value)


class OriginalNative210Tests(unittest.TestCase):
    setUp=fixture.NativeWording209Tests.setUp
    tearDown=fixture.NativeWording209Tests.tearDown
    prepare=fixture.NativeWording209Tests.prepare
    finish=fixture.NativeWording209Tests.finish

    def source(self):
        self.ctx['messages']=[dict(id='improv-client-1',direction='in',sender_type='client',body='Добрый вечер! Нужно собрать комод. Схема осталась в коробке, все детали и крепёж на месте. Пока хочу понять, как это будет.')]
        return self.prepare()

    def original(self):
        # Exact untouched provider JSON209/9902/1, a synthetic identity, no private contacts.
        return {'context_review':{'last_intent':'Сборка комода','latest_client_meaning':'Клиент уточняет расположение места сборки комода','selected_step_fits':True,'evidence_ids':['improv-client-1'],'note':'Вопрос о месте проведения работ соответствует намерению клиента и необходим для дальнейшего оформления заказа'},'reply':'Здравствуйте! Где будут проводиться работы: квартира, частный дом или организация?','needs_operator':False}

    def test_original_native_is_rejected_by_the_context_guard_without_repair(self):
        _,t=self.source();value=self.original();before=copy.deepcopy(value)
        _,status,errors=ext._context_review(value,t)
        self.assertEqual(status,'inconsistent');self.assertIn('staff_question_as_client_goal',errors);self.assertEqual(value,before)

    def test_full_finalize_keeps_the_original_native_empty_and_blocked(self):
        prepared,_=self.source();out=self.finish(prepared,self.original())
        self.assertEqual(out['reply'],'');self.assertTrue(out['needs_operator']);self.assertIn('staff_question_as_client_goal',out['validation'])

    def test_correct_free_meaning_and_natural_question_survive_native_wire_and_finalize(self):
        prepared,t=self.source();value=self.original();value['context_review']['latest_client_meaning']='Просит собрать комод, сообщает о схеме и полном комплекте, хочет понять порядок работ.'
        value['reply']='Подскажите, это квартира, частный дом или организация?'
        self.assertNotIn('enum',prepared['model_task']['response_format']['schema']['properties']['reply'])
        out=self.finish(prepared,value);self.assertEqual(out['validation'],[]);self.assertEqual(out['response_source'],'model');self.assertIn(value['reply'],out['reply'])

    def test_valid_meaning_does_not_force_acceptance_of_the_service_step(self):
        _,t=self.source();value=self.original();value['context_review'].update(latest_client_meaning='Клиент просит собрать комод и хочет понять порядок работ.',selected_step_fits=False,note='Сервисный шаг оценивается отдельно от слов клиента.')
        value.update(reply='',needs_operator=True)
        _,status,errors=ext._context_review(value,t);self.assertEqual(status,'provided');self.assertEqual(errors,['model_context_mismatch'])

    def test_native_free_semantic_fields_and_conditional_reviews_remain_independent(self):
        prepared,_=self.source();review=prepared['model_task']['response_format']['schema']['properties']['context_review']['properties']
        for key in ('last_intent','latest_client_meaning'):
            self.assertEqual(review[key]['type'],'string');self.assertNotIn('enum',review[key]);self.assertTrue(review[key].get('description'))
        self.assertNotIn('enum',review['selected_step_fits'])
