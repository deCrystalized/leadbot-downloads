"""Causal controls from frozen381–420 targets; no live actions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog as catalog
import assistant_policy as policy
import assistant_prices as prices
import assistant_qualifiers as qualifiers
import contact_facts
import crm_evidence
import qualification_state
from extension_assistant import manual_checklist


def history(*rows):
    return [dict(id=str(i), direction=d, body=t) for i,(d,t) in enumerate(rows)]


class Batch11IntentTests(unittest.TestCase):
    def assess(self,*rows,direction='mnc',title=None):
        m=history(*rows)
        known=dict(city='Оренбург',direction=direction,partner='7',channel='avito',
                   account_name='Иван '+('КП' if direction=='kp' else 'МНЧ'),advertiser_name='Иван',
                   title=title or ('Ремонт компьютеров' if direction=='kp' else 'Мастер на час'))
        return policy.assess(m,known,contact_facts.collect(m,known))

    def test_missed_visit_complaint_outranks_polite_decline(self):
        out=self.assess(('in','Заменить душевую кабину'),('out','Через час-полтора удобно?'),
                        ('in','Мы больше не нуждаемся в вашем мастере. Время19.10 он так и не появился за сегодняшний день. Спасибо за испорченное настроение и потраченные4дня'))
        self.assertEqual(out['action'],'handoff')
        self.assertIn('ОКК',out['reason'])
        self.assertIn('DOC-L0823',out['rule_ids'])

    def test_hypothetical_or_pasted_review_is_not_our_missed_visit(self):
        for text in ('Если мастер не появится, что делать?',
                     'Сделка состоялась. Мастер так и не появился за сегодняшний день'):
            self.assertFalse(policy._missed_visit_complaint(history(('in',text))))

    def test_clock_change_after_accepted_visit_requires_existing_order_lookup(self):
        out=self.assess(('in','Собрать шкаф'),('out','В11 удобно будет?'),('in','Да'),
                        ('out','Хорошо, договорились'),('in','Можно к10.30?'))
        self.assertEqual(out['action'],'handoff')
        self.assertTrue(out['existing_visit_evidence'])
        self.assertRegex(out['reason'],'перенос|договорённост')

    def test_first_clock_question_without_acceptance_does_not_prove_booking(self):
        out=self.assess(('in','Собрать шкаф'),('out','В11 удобно?'),('in','Пока не знаю'),('in','Можно к10.30?'))
        self.assertFalse(out.get('existing_visit_evidence'))

    def test_printer_status_diagnostic_word_does_not_quote_diagnostic_fee(self):
        text='Принтер печатает пустые листы, в диагностике показывает что нет краски, хотя она есть. Занимаетесь ли вы таким и какая цена?'
        out=prices.answer(history(('in',text)),dict(direction='kp',city='Оренбург',partner='7'),text)
        self.assertEqual(out['amounts'],[])
        self.assertIn('KP-L0474',out['rules'])

    def test_actual_diagnostic_price_question_is_preserved(self):
        for text in ('Сколько стоит диагностика принтера?',
                     'В диагностике пишет нет краски. Сколько стоит диагностика у вас?',
                     'Выезд платный?'):
            out=prices.answer(history(('in',text)),dict(direction='kp',city='Оренбург',partner='7'),text)
            self.assertEqual(out['amounts'],[1000])

    def test_past_price_interest_plus_future_contact_is_a_deferral(self):
        for text in ('Пока незнаю, просто хотел узнать цену, но в ближайшие дни напишу вам',
                     'Как только придёт я с вами свяжусь','Хорошо подумаю'):
            self.assertTrue(policy._client_deferred([text]))
        self.assertFalse(policy._client_deferred(['Позже напишу, а сейчас подскажите цену?']))

    def test_self_resolution_does_not_reopen_intake(self):
        for text in ('Доброе утро. Спасибо, вчера поладил и справился.',
                     'Там ничего сложного, сам справлюсь.'):
            self.assertTrue(policy._client_declined(text,'Когда вам удобно?'))
        self.assertFalse(policy._client_declined('Вчера справился, но теперь снова не работает','Когда удобно?'))

    def test_board_inflections_are_electrical_work(self):
        for text in ('Навести порядок в щитке,380V','Установить распределительный щит в новостройке'):
            service=catalog.choose(text,dict(direction='mnc'))
            self.assertEqual(service['status'],'supported')
            self.assertEqual([r['id'] for r in service['items']],['electric'])

    def test_sunday_price_wording_does_not_add_surface_restoration(self):
        service=catalog.choose('Навести порядок в щитке. Сколь услуга стоит? В гараже в воскресенье.',dict(direction='mnc'))
        self.assertEqual([x['id'] for x in service['items']],['electric'])
        service=catalog.choose('Устранить скол мебели воском',dict(direction='mnc'))
        self.assertIn('appearance',[x['id'] for x in service['items']])

    def test_kitchen_drawer_repair_does_not_require_the_word_furniture(self):
        service=catalog.choose('Перестал закрываться выкатной ящик на кухне. Можете помочь починить?',dict(direction='mnc'))
        self.assertEqual(service['status'],'supported')
        self.assertEqual([x['id'] for x in service['items']],['furniture'])
        self.assertNotIn('furniture',[x['id'] for x in catalog.choose('Починить электрический ящик',dict(direction='mnc'))['items']])

    def test_reversed_led_fixture_description_still_requires_repair_agreement(self):
        for text in ('Светильник диодный на потолке ремонтируете?', 'Ремонт светильника диодного'):
            service=catalog.choose(text,dict(direction='mnc'))
            self.assertEqual(service['status'],'agree')

    def test_identity_question_outranks_old_missed_visit_complaint(self):
        out=self.assess(('in','Ваш мастер вчера так и не приехал'),
                        ('in','Это с вашей фирмы мне сегодня позвонили?'))
        self.assertRegex(out['reason'],'происхождение звонка')

    def test_reviewed_router_photo_retains_the_unresolved_client_task(self):
        m=history(('in','Wi-Fi есть, Wi-Fi поставь'),('in',''))
        m[-1].update(media_reviewed=True,media_observation=dict(content_kind='product_photo',source='offline_reviewed_image'))
        known=dict(direction='kp',city='Оренбург',partner='7',channel='avito',title='Подключение и настройка роутера',
                   account_name='Иван КП',advertiser_name='Иван')
        out=policy.assess(m,known,contact_facts.collect(m,known))
        self.assertEqual(out['next_question']['kind'],'router_task')

    def test_printer_symptom_question_precedes_listing_city_question(self):
        messages=history(('in','Ремонтом принтеров занимаетесь?'),('out','Какой он у вас?'),('in','CanonG3410'))
        known=dict(direction='kp',city='Оренбург',partner='7')
        question=qualifiers.next_question(messages,known,contact_facts.collect(messages,known))
        self.assertEqual(question['kind'],'problem')

    def test_printhead_request_identifies_a_printer_without_repeating_device(self):
        service=catalog.choose('Нужна чистка печатающей головки. HP510',dict(direction='kp'))
        self.assertEqual(service['status'],'supported')
        self.assertEqual([x['id'] for x in service['items']],['printer'])

    def test_explicit_operation_does_not_require_a_repair_symptom(self):
        for text in ('Обновить BIOS материнской платы', 'Поменять видеокарту в компьютере'):
            m=history(('in',text));known=dict(direction='kp',city='Оренбург',partner='7')
            question=qualifiers.next_question(m,known,contact_facts.collect(m,known))
            self.assertNotEqual(question['kind'],'problem')

    def test_confirmed_manufacture_is_not_ready_made_furniture_assembly(self):
        m=history(('in','Сделать шкафы на веранде'),('out','Изготовить нужно их?'),('in','Да'))
        facts=contact_facts.collect(m)
        intent=contact_facts.intent_text('Сделать шкафы на веранде\nДа',facts)
        service=catalog.choose(intent,dict(direction='mnc'))
        self.assertIn(service['status'],('unknown','agree'))
        self.assertIn('DOC-L0453',service['rules'])
        self.assertTrue(facts['furniture_manufacture']['confirmed'])

    def test_staff_manufacture_question_alone_or_client_correction_is_not_confirmation(self):
        for tail in [[],[('in','Нет, собрать готовые')]]:
            m=history(('in','Сделать шкафы на веранде'),('out','Изготовить нужно их?'),*tail)
            self.assertFalse(contact_facts.collect(m).get('furniture_manufacture'))

    def test_staff_time_label_is_lookup_hint_and_not_created_order_proof(self):
        for text in ('1009820 ут','1075500 повтор'):
            refs=crm_evidence.note_references([dict(id='n',direction='note',sender_type='operator',body=text)])
            self.assertEqual(refs[0]['request_id_candidate'],text[:7])
        self.assertFalse(crm_evidence.note_references([dict(direction='note',sender_type='operator',body='1009820 модель')]))

    def test_safe_onsite_faq_does_not_accept_an_unverified_price(self):
        m=history(('in','Обновить BIOS материнской платы'),('out','От1000 рублей'),
                  ('in','А нет варианта, чтобы я вам материнку отдал?'))
        known=dict(direction='kp',city='Оренбург',partner='723',channel='avito',title='Компьютерная помощь',
                   account_name='КомпХелп КП',advertiser_name='КомпХелп',direction_source='context')
        out=policy.assess(m,known,contact_facts.collect(m,known))
        self.assertEqual(out['action'],'question')
        self.assertIn('выезжает',out['forced_reply'])
        self.assertTrue(manual_checklist(m,known)['hard_block'])

    def test_electric_hob_does_not_require_water_or_a_second_socket_job(self):
        text='Установить электрическую варочную панель вместо старой, подключить и прикрутить силовую вилку. Розетка уже есть.'
        service=catalog.choose(text,dict(direction='mnc'))
        self.assertEqual([x['id'] for x in service['items']],['mnc-connect'])
        self.assertEqual(service['items'][0]['questions'],['electrics_ready'])

    def test_electric_hob_and_dishwasher_keep_water_readiness(self):
        service=catalog.choose('Установить варочную панель и подключить посудомоечную машину',dict(direction='mnc'))
        self.assertIn('plumbing_ready',next(x for x in service['items'] if x['id']=='mnc-connect')['questions'])

    def test_metal_pipe_puncture_is_not_ordinary_plastic_pipe_work(self):
        m=history(('in','Просверлили медную трубу в стене. Нужно срочно решить вопрос'))
        service=catalog.choose(m[0]['body'],dict(direction='mnc'))
        self.assertIsNotNone(catalog.condition_issue(service,qualification_state.inspect(m),m[0]['body']))
        m=history(('in','Повреждена медная труба, готовы заменить на пластиковую'))
        service=catalog.choose(m[0]['body'],dict(direction='mnc'))
        self.assertIsNone(catalog.condition_issue(service,qualification_state.inspect(m),m[0]['body']))

    def test_decimal_budget_without_unit_is_not_silently_guessed(self):
        state=prices.consent(history(('in','Бюджет4,5. Не больше4,5')))
        self.assertEqual(state['status'],'conditional')
        self.assertTrue(state['budget_ambiguity'])
        self.assertFalse(state.get('budget_limit'))

    def test_unclear_deictic_problem_gets_one_clarification(self):
        out=self.assess(('in','Такая проблема уже была и снова появилась, сколько стоит ремонт?'),
                        direction='kp',title='Ремонт телевизоров')
        self.assertEqual(out['next_question']['kind'],'problem')

    def test_ambiguous_wifi_request_is_clarified_before_contract_or_booking(self):
        out=self.assess(('in','Wi-Fi есть, Wi-Fi поставь'),direction='kp',title='Подключение и настройка роутера')
        self.assertEqual(out['next_question']['kind'],'router_task')

    def test_android_unlock_is_clarified_without_approving_mi_account_work(self):
        out=self.assess(('in','Разблокируйте андроид'),direction='kp',title='Настройка телефона')
        self.assertEqual(out['next_question']['kind'],'phone_lock')
        out=self.assess(('in','Разблокируйте андроид'),('out','Экран телефона или аккаунт?'),
                        ('in','Ми аккаунт'),direction='kp',title='Настройка телефона')
        self.assertEqual(out['action'],'handoff')

    def test_unclear_phone_lock_does_not_loop_the_same_question(self):
        out=self.assess(('in','Разблокируйте андроид'),('out','Что заблокировано: экран телефона или аккаунт?'),
                        ('in','Не знаю'),('out','Экран или аккаунт заблокирован?'),('in','Не понял'),
                        direction='kp',title='Настройка телефона')
        self.assertEqual(out['action'],'handoff')

    def test_plasma_lost_signal_is_not_yet_confirmed_hardware_repair(self):
        out=self.assess(('in','Плазменный телевизор LG50PJ353R'),('in','Пропал сигнал, совсем не ловит, сможете помочь?'),
                        direction='kp',title='Ремонт телевизоров')
        self.assertEqual(out['next_question']['kind'],'tv_signal_source')
        out=self.assess(('in','Плазменный телевизор LG, разбит экран'),direction='kp',title='Ремонт телевизоров')
        self.assertEqual(out['action'],'handoff')

    def test_untyped_locality_hints_are_preserved_without_guessing_a_city(self):
        for text in ('ул. Гагарина12 а сосново','Адрес: Тула, Рябиново',
                     'Размеры длина3метра высота202 Мурмаши'):
            m=history(('in',text));facts=contact_facts.collect(m,dict(city='Тула',direction='mnc'))
            self.assertTrue(facts['untyped_place_candidate'])
            self.assertFalse(facts['untyped_place_candidate']['map_verified'])
            self.assertNotEqual(facts.get('address',{}).get('city'),'Рябиново')
        for text in ('ул. Гагарина12, спасибо','ул. Гагарина12 а, готово','ул. Гагарина12, первый подъезд',
                     'Размеры стола200x80, спасибо'):
            self.assertFalse(contact_facts.collect(history(('in',text)),dict(city='Тула',direction='mnc'))['untyped_place_candidate'])


if __name__=='__main__':
    unittest.main()
