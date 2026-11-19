"""Source962/971/976/979 and controls for their shared intake boundaries."""
import unittest

import assistant_catalog as catalog
import assistant_policy as policy
import contact_facts
import qualification_state as qs
import personal_assistant
from extension_assistant import manual_checklist


def rows(*pairs):
    return [dict(id='m'+str(i), direction=d, body=t) for i,(d,t) in enumerate(pairs,1)]


def known(direction='mnc', title='Мастер на час'):
    return dict(channel='avito', direction=direction, city='Тула', partner='7',
                title=title, direction_source='source', account_name='Михаил МНЧ', origin='В75')


def assess(messages, source=None):
    source=source or known()
    return policy.assess(messages, source, contact_facts.collect(messages, source))


def lock_history(answer='Попробовать отремонтировать. Понять причину заедания. И замена, если потребуется'):
    return rows(('in','Заедает замок на входной двери. Подтекает бачок унитаза. Течёт гусак в ванной.'),
                ('out','Вам замена замка нужна или ремонт?'), ('in',answer))


class Intake106Tests(unittest.TestCase):
    def test_tv_ad_and_backlight_repair_are_a_device_context(self):
        source=known('kp','Ремонт телевизоров с выездом')
        out=assess(rows(('in','На Samsung UE48H5270 заменить подсветку сколько будет?')),source)
        self.assertNotEqual(out['action'],'handoff')
        self.assertTrue(any(i['family']=='tv' for i in out['service']['items']))

    def test_tv_ad_does_not_override_an_explicit_other_device(self):
        source=known('kp','Ремонт телевизоров')
        for body in ('У ноутбука заменить подсветку экрана', 'У монитора заменить подсветку',
                     'Отремонтировать подсветку клавиатуры компьютера'):
            with self.subTest(body=body):
                service=catalog.choose(body,source)
                self.assertFalse(any(i['family']=='tv' for i in service.get('items',[])))

    def test_tv_ad_does_not_make_furniture_led_installation_a_tv_repair(self):
        service=catalog.choose('Нужно установить светодиодную ленту для подсветки под кухонными шкафами',
                               known('kp','Ремонт телевизоров'))
        self.assertFalse(any(i['family']=='tv' for i in service.get('items',[])))

    def test_existing_tv_bands_still_get_owner_refusal(self):
        out=assess(rows(('in','Телевизор LED, на экране появились полосы')),known('kp','Ремонт телевизоров'))
        self.assertEqual(out['action'],'refuse')

    def test_printer_paper_roller_request_is_recognized(self):
        source=known('kp','Ремонт принтеров и МФУ')
        messages=rows(('in','Сколько стоит поменять ролик захвата бумаги Samsung Scx 3400?'))
        out=assess(messages,source)
        self.assertNotEqual(out['action'],'handoff')
        self.assertTrue(any(i['id']=='printer' for i in out['service']['items']))
        self.assertNotIn(out.get('next_question',{}).get('kind'),('model','printer_connection','problem'))

    def test_spaced_samsung_printer_model_preserves_client_evidence(self):
        state=qs.inspect(rows(('in','Ролик захвата бумаги Samsung Scx 3400')))
        self.assertEqual(state['model']['status'],'answered')
        self.assertIn('3400',state['model']['value'])

    def test_model_does_not_consume_a_brand_price(self):
        state=qs.inspect(rows(('in','Samsung, цена 3400 рублей')))
        self.assertNotEqual(state['model']['status'],'answered')

    def test_special_printer_repair_keeps_agreement(self):
        out=assess(rows(('in','Нужен ремонт термопринтера, заменить ролик захвата бумаги')),
                   known('kp','Ремонт принтеров'))
        self.assertEqual(out['action'],'handoff')

    def test_lock_symptom_asks_work_choice_before_door_material(self):
        out=assess(lock_history()[:1])
        self.assertIn(out['action'],('question','draft'))
        self.assertEqual(out['next_question']['kind'],'lock_work')

    def test_actual_repair_choice_and_conditional_replacement_stay_repair(self):
        state=qs.inspect(lock_history())['lock_work']
        self.assertEqual(state['status'],'answered')
        self.assertEqual(state['value'],'repair')
        self.assertEqual(state['message_id'],'m3')
        self.assertEqual(state['question_message_id'],'m2')

    def test_mixed_lock_repair_is_handed_off_without_dropping_plumbing(self):
        out=assess(lock_history())
        self.assertEqual(out['action'],'handoff')
        self.assertIn('DOC-L0453',out['rule_ids'])
        self.assertGreaterEqual(len(out['service']['items']),3)
        self.assertTrue(any(i['family']=='lock' for i in out['service']['items']))

    def test_same_lock_condition_reaches_manual_form(self):
        out=manual_checklist(lock_history(),known())
        self.assertRegex(str(out),'Ремонт.*согласован')

    def test_repair_comment_keeps_conditional_replacement_in_client_words(self):
        facts=contact_facts.collect(lock_history(),known())
        self.assertEqual(facts['lock_work_choice']['value'],'repair')
        self.assertTrue(any('если потребуется' in x for x in facts['comment_lines']))

    def test_unknown_handle_work_does_not_get_a_lock_question(self):
        out=assess(rows(('in','Болтается ручка на межкомнатной двери')))
        self.assertIn('ручки',out['next_question']['question'])

    def test_explicit_replacement_is_not_lock_repair(self):
        out=assess(rows(('in','Поменять замок на входной металлической двери')))
        self.assertNotEqual(out['action'],'handoff')

    def test_service_question_can_establish_requested_work_without_consent(self):
        for body,value in (('Сколько стоит заменить замок?', 'replace'),
                           ('Вы устанавливаете ручки на межкомнатные двери?', 'install')):
            with self.subTest(body=body):
                state=qs.inspect(rows(('in',body)))['lock_work']
                self.assertEqual(state['value'],value)

    def test_conditional_future_work_is_not_current_repair_choice(self):
        state=qs.inspect(rows(('in','Если когда-нибудь понадобится отремонтировать замок, сможете?')))['lock_work']
        self.assertNotEqual(state['value'],'repair')

    def test_store_landmark_does_not_change_selected_work(self):
        messages=rows(('in','Поменять замок на входной двери'),('out','Напишите адрес'),
                      ('in','Ленина10, около магазина «Ремонт замков»'))
        self.assertEqual(qs.inspect(messages)['lock_work']['value'],'replace')

    def test_unquoted_store_in_address_answer_does_not_create_lock_repair(self):
        messages=rows(('in','Собрать шкаф'),('out','Напишите адрес'),
                      ('in','Рядом магазин Ремонт замков, Ленина10'))
        self.assertNotEqual(qs.inspect(messages)['lock_work']['value'],'repair')
        facts=contact_facts.collect(messages,known())
        self.assertFalse(any('Работа с замком' in line for line in facts['comment_lines']))

    def test_appliance_handle_does_not_become_door_lock_work(self):
        state=qs.inspect(rows(('in','Отремонтировать ручку холодильника')))['lock_work']
        self.assertNotEqual(state['value'],'repair')

    def test_later_explicit_replacement_supersedes_repair_choice(self):
        messages=lock_history()+rows(('in','Нет, ремонт не нужен. Замените замок.'))
        self.assertEqual(qs.inspect(messages)['lock_work']['value'],'replace')
        self.assertNotIn('Ремонт замка',assess(messages)['reason'])

    def test_unrelated_repair_does_not_turn_lock_replacement_into_repair(self):
        messages=rows(('in','Поменять замок и отремонтировать шкаф'))
        self.assertEqual(qs.inspect(messages)['lock_work']['value'],'replace')

    def test_failed_work_question_does_not_bind_an_unnamed_repair(self):
        messages=lock_history()
        messages[1]['delivery_status']='failed'
        self.assertNotEqual(qs.inspect(messages)['lock_work']['value'],'repair')

    def test_handle_installation_is_not_asked_about_lock_repair(self):
        out=assess(rows(('in','Установить ручки на межкомнатные деревянные двери')))
        self.assertNotEqual(out.get('next_question',{}).get('kind'),'lock_work')

    def test_free_repair_choice_is_not_ordinary_auto_admission(self):
        ctx=dict(assigneeId='',assignmentKnown=True,conversationStatus='in_progress',channelAssigned=True,
                 botActive=False,hasTransfer=False)
        result=personal_assistant.screen(lock_history(),known(),ctx,'owner',0,0)
        self.assertFalse(result['eligible'])

    def test_expensive_with_thanks_stops_intake(self):
        messages=rows(('in','Ремонт дверцы шкафа'),('out','От1500 рублей'),
                      ('in','Извините, для меня это дорого. Спасибо.'))
        out=assess(messages)
        self.assertEqual(out['action'],'wait')
        self.assertFalse(out.get('forced_reply'))

    def test_price_question_is_not_refusal(self):
        self.assertFalse(policy._client_declined('Спасибо, а почему так дорого?','От1500 рублей'))

    def test_expensive_but_accepted_is_not_refusal(self):
        self.assertFalse(policy._client_declined('Для меня дорого, но всё равно готова, приезжайте. Спасибо.','От1500 рублей'))
        self.assertFalse(policy._client_declined('Для меня это не дорого. Спасибо.','От1500 рублей'))


if __name__=='__main__':
    unittest.main()
