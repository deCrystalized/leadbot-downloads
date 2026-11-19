"""Controls from frozen421–460 source readings; no live customer actions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import assistant_catalog as catalog
import assistant_policy as policy
import assistant_prices as prices
import contact_facts
import crm_evidence


def messages(*rows):
    return [dict(id=str(i),direction=d,body=t) for i,(d,t) in enumerate(rows)]


class Batch12IntentTests(unittest.TestCase):
    def assess(self,*rows,direction='mnc',title='Мастер на час'):
        m=messages(*rows)
        k=dict(direction=direction,direction_source='context',city='Оренбург',partner='7',channel='avito',
               title=title,account_name='Иван '+('КП' if direction=='kp' else 'БТ' if direction=='bt' else 'МНЧ'))
        return policy.assess(m,k,contact_facts.collect(m,k))

    def test_ink_tubes_are_not_household_pipe_work(self):
        out=catalog.choose('ПринтерHPInkTank410, в трубках передается краска, там воздушный пузырь.',dict(direction='kp'))
        self.assertEqual([x['id'] for x in out['items']],['printer'])

    def test_independent_water_pipe_job_survives_printer_context(self):
        out=catalog.choose('Принтер не печатает, в трубках чернила. Еще заменить трубу в ванной.',dict(direction='kp'))
        self.assertEqual(out['status'],'mixed')
        self.assertIn('pipes',[x['id'] for x in out['items']])

    def test_computer_desk_is_furniture(self):
        for text in ('Собрать стол компьютерный','Собрать компьютерный стол'):
            out=catalog.choose(text,dict(direction='mnc'))
            self.assertEqual([x['id'] for x in out['items']],['furniture'])

    def test_gluing_window_trim_is_not_dropped_from_a_mixed_order(self):
        out=catalog.choose('Повесить люстру, картину и уголки окна приклеить',dict(direction='mnc'))
        self.assertEqual(out['status'],'mixed')
        self.assertIn('window-trim',[x['id'] for x in out['items']])
        self.assertIn('light',[x['id'] for x in out['items']])

    def test_independent_pc_job_is_not_removed_by_a_desk(self):
        out=catalog.choose('Собрать компьютер и стол',dict(direction='mnc'))
        self.assertEqual(out['status'],'mixed')

    def test_price_interest_in_past_does_not_override_explicit_decline(self):
        out=self.assess(('in','Установить унитаз'),('out','В районе3500руб работа'),
                        ('in','Пока не актуально, я хотел узнать цену, поищу ещё мастеров'))
        self.assertEqual(out['action'],'wait')

    def test_current_question_after_decline_is_not_silenced(self):
        self.assertFalse(policy._client_declined('Пока не актуально, а сколько стоит выезд?','Когда удобно?'))

    def test_bare_no_after_onsite_acceptance_question_closes_intake(self):
        self.assertTrue(policy._client_declined('нет','У себя принять сможете?'))
        self.assertFalse(policy._client_declined('нет','Инструкция есть?'))

    def test_courteous_thinking_deferral(self):
        self.assertTrue(policy._client_deferred(['Спасибо я подумаю']))
        self.assertFalse(policy._client_deferred(['Спасибо, я подумаю. А какая гарантия?']))

    def test_colloquial_farewell_does_not_continue_collection(self):
        self.assertTrue(policy._conversation_closed('до свиданья','Когда принять?'))

    def test_unverified_prior_call_is_not_confirmed_as_our_conversation(self):
        out=self.assess(('in','Александр, позвоните'),('out','Только что вам набирал'),
                        ('in','Разговаривали с Вами?'),direction='kp',title='Ремонт телевизоров')
        self.assertEqual(out['action'],'handoff')
        self.assertRegex(out['reason'],'звон|разговор')

    def test_wait_time_question_after_promised_visit_requires_lookup(self):
        out=self.assess(('in','Починить бачок унитаза'),('out','К 10 буду'),
                        ('in','Широтная63, квартира25'),('in','Вас через сколько ждать?'))
        self.assertEqual(out['action'],'handoff')

    def test_first_availability_question_does_not_prove_a_prior_visit(self):
        out=self.assess(('in','Починить бачок унитаза. Через сколько сможете приехать?'))
        self.assertNotRegex(out['reason'],'существующ.*договорённост')

    def test_reported_damage_after_work_goes_to_okk(self):
        out=self.assess(('in','Повесить телевизор на кронштейн'),('out','Записал вас, до встречи'),
                        ('in','После работы пробита бетонная стена насквозь. Кто оплатит ремонт? Испорчены обои!'))
        self.assertEqual(out['action'],'handoff')
        self.assertIn('ОКК',out['reason'])

    def test_after_work_time_of_day_is_not_a_damage_complaint(self):
        out=self.assess(('in','После работы придёте повесить полку?'))
        self.assertNotRegex(out['reason'],'ОКК')

    def test_polair_cold_chamber_is_industrial_agreement_not_refusal(self):
        out=self.assess(('in','Ремонт холодильной камеры в столовой'),('out','Марка какая?'),
                        ('in','Полаир'),direction='bt',title='Ремонт холодильников')
        self.assertEqual(out['action'],'handoff')
        self.assertIn('DOC-L0466',out['rule_ids'])
        self.assertNotIn('не сможем',out.get('forced_reply',''))

    def test_staff_refusal_and_call_queue_notes_are_lookup_hints(self):
        for text in ('1234567 отказ','1234567 на прозвоне'):
            r=crm_evidence.note_references([dict(id='n',direction='note',sender_type='operator',body=text)])
            self.assertEqual(r[0]['request_id_candidate'],'1234567')
        self.assertFalse(crm_evidence.note_references([dict(direction='in',body='1234567 отказ')]))

    def test_unknown_furniture_modules_get_one_task_clarification(self):
        out=self.assess(('in','После ответа отправлю скрины какие модули у нас, чтобы узнать цену'),title='Сборка и ремонт мебели')
        self.assertEqual(out['next_question']['kind'],'furniture_task')

    def test_onsite_question_can_be_answered_without_accepting_old_quote(self):
        out=self.assess(('in','Переустановить Windows'),('out','От500руб'),
                        ('in','Выезжаете на дом?'),direction='kp',title='Установка Windows')
        self.assertEqual(out['action'],'question')
        self.assertIn('выезжает на адрес',out['forced_reply'])

    def test_diagnostic_fee_question_typo_does_not_become_a_repair_quote(self):
        m=messages(('in','Сколько стоит ремонт холодильника или диогностика, перестал морозить?'))
        out=prices.answer(m,dict(direction='bt',city='Оренбург',partner='7'),m[0]['body'])
        self.assertEqual(out['amounts'],[800])
        self.assertNotIn('1000',out['reply'])
        self.assertIn('бесплат',out['reply'])

    def test_microdistrict_name_is_kept_for_map_lookup(self):
        f=contact_facts.collect(messages(('in','Мкр.Осетровка')),dict(city='Чита',direction='mnc'))
        self.assertRegex(f['stated_place']['value'],'Осетровка')
        self.assertFalse(f['address'].get('city'))

    def test_named_island_is_kept_without_selecting_another_city(self):
        f=contact_facts.collect(messages(('in','Живем на Русском острове, Университетский проспект25/2')),dict(city='Владивосток',direction='mnc'))
        self.assertRegex(f['stated_place']['value'],'Русском острове')

    def test_explicit_thousand_budget_unit_is_not_guessed_or_lost(self):
        state=prices.consent(messages(('in','До1,5к главное уложимся?')))
        self.assertEqual(state['budget_limit']['amount'],1500)
        self.assertFalse(state.get('budget_ambiguity'))

    def test_printer_cartridge_symptom_is_not_an_explicit_refill_job(self):
        out=catalog.choose('Ремонтируете принтеры? Не печатает, что-то с черным картриджем.',dict(direction='kp'))
        self.assertEqual(out['status'],'supported')
        self.assertEqual([x['id'] for x in out['items']],['printer'])

    def test_explicit_cartridge_refill_keeps_existing_primary_conflict_guard(self):
        out=catalog.choose('Нужно заправить картридж принтера',dict(direction='kp'))
        self.assertEqual(out['status'],'conflict')

    def test_refill_task_is_preserved_when_client_explains_it_in_separate_sentences(self):
        out=catalog.choose('Обслужить принтер Canon. Заправить, настроить уровень краски. Родные картриджи текут, новые заказали.',dict(direction='kp'))
        self.assertEqual(out['status'],'conflict')

    def test_past_cartridge_refill_does_not_become_the_current_job(self):
        out=catalog.choose('Принтер после заправки картриджа не печатает.',dict(direction='kp'))
        self.assertEqual(out['status'],'supported')


if __name__=='__main__':unittest.main()
