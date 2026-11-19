"""Device labels, components and screen text are not separate service jobs."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import assistant_catalog as catalog
import assistant_prices as prices
import contact_facts as contacts
from assistant_store import Store
from extension_assistant import Assistant


def messages(*rows):
    return [dict(id=str(i),direction=d,body=t) for i,(d,t) in enumerate(rows)]


def known(direction='kp'):
    return dict(direction=direction,city='Оренбург',partner='7',channel='avito',title='Компьютерная помощь')


def ids(text,direction='kp'):
    return {r['id'] for r in catalog.choose(text,known(direction))['items']}


class CatalogObjectRole71Tests(unittest.TestCase):
    def test_tv_stand_is_furniture_not_a_tv_repair_or_mount(self):
        for text in ('Сборка ТВ тумбы 180 см','Собрать ТВ-тумбу','Собрать тумбу под телевизор','Собрать телевизионную тумбу'):
            self.assertEqual(ids(text,'mnc'),{'furniture'},text)

    def test_a_tv_job_beside_a_stand_is_preserved(self):
        self.assertIn('tv',ids('Собрать ТВ-тумбу. Телевизор не включается','mnc'))
        found=ids('Собрать ТВ тумбу и повесить телевизор на кронштейн','mnc')
        self.assertIn('furniture',found);self.assertIn('tv-mount',found)

    def test_stand_ad_does_not_override_an_mnc_account_to_kp(self):
        route,basis=catalog.source_direction(dict(known('mnc'),account_name='Михаил МНЧ',title='Сборка тумбы под телевизор'))
        self.assertEqual(route,'mnc')

    def test_pencil_cabinet_assembly_is_a_furniture_subtype(self):
        self.assertEqual(ids('Сколько стоит сборку пенала сделать?','mnc'),{'furniture'})

    def test_hanging_a_tv_stand_and_socket_remain_two_mnc_jobs(self):
        service=catalog.choose('Мне нужен мастер по вешать тумбочку под телевизор и розетку сделать',known('mnc'))
        self.assertEqual(service['status'],'supported')
        self.assertEqual({r['id'] for r in service['items']},{'furniture','sockets'})
        furniture=next(r for r in service['items'] if r['id']=='furniture')
        self.assertEqual(furniture['questions'],['wall']);self.assertIn('DOC-L0352',furniture['primary_refs'])

    def test_repairing_a_cabinet_door_is_not_hanging_the_cabinet_on_a_wall(self):
        service=catalog.choose('Прикрутить дверцу шкафа, вырвало петли',known('mnc'))
        furniture=next(r for r in service['items'] if r['id']=='furniture')
        self.assertEqual(furniture['questions'],['furniture_problem'])

    def test_tv_server_error_does_not_request_server_service(self):
        for text in ('Телевизор Philips пишет что не может найти сервера',
                     'Телевизор не подключается к серверу','На ТВ ошибка: сервер недоступен'):
            items=catalog.choose(text,known())['items']
            self.assertTrue(items);self.assertEqual({r['family'] for r in items},{'tv'},text)

    def test_independent_server_service_keeps_its_agreement_rule(self):
        found=catalog.choose('Телевизор не может найти сервер. Ещё нужно отремонтировать сервер',known())
        server=next(r for r in found['items'] if r['id']=='pc-server')
        self.assertEqual(server['status'],'agree');self.assertIn('DOC-L0141',server['primary_refs'])

    def test_display_picture_does_not_request_hanging_a_wall_picture(self):
        self.assertNotIn('hanging',ids('Видеокарта вставлена в ПК, нет картинки на экране'))
        self.assertEqual(ids('Повесить картину на стену','mnc'),{'hanging'})
        self.assertIn('hanging',ids('На ПК нет картинки. Ещё повесить картину на стену'))


class GraphicsScope71Tests(unittest.TestCase):
    symptom='Подарили рабочую видеокарту б/у, но нет картинки, экран просто чёрный'

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.dict(os.environ,LEADBOT_ASSISTANT_WORDING='reviewed');p.start();self.addCleanup(p.stop)
        self.app=Assistant(Store(self.tmp.name+'/db'))

    def run_action(self,rows,action='preview'):
        out,code=self.app.handle(dict(owner='offline-graphics71',action=action,ctx=dict(
            convId='synthetic-graphics71',city='Оренбург',dir='kp',partner='7',channel='avito',
            accountTitle='Иван КП',itemTitle='Компьютерная помощь',messages=messages(*rows))))
        self.assertEqual(code,200);self.assertFalse(out['auto_enabled']);return out

    def test_unconfirmed_host_is_clarified_before_a_gpu_repair_price(self):
        out=self.run_action([('in',self.symptom+' Сколько будет стоить?')])
        self.assertEqual(out['action'],'question');self.assertRegex(out['reply'],'[Кк]омпьютер|ПК')
        self.assertNotRegex(out['reply'],'5000|1000|сломан|неисправна')

    def test_contextual_polite_yes_confirms_host_not_a_gpu_fault(self):
        rows=[('in',self.symptom),('out','Видеокарта вставлена в ПК?'),('in','Да конечно')]
        facts=contacts.collect(messages(*rows))
        scope=facts['graphics_scope'];self.assertEqual(scope['kind'],'host_diagnostic')
        self.assertEqual(scope['message_id'],'2');self.assertEqual(scope['question_message_id'],'1')
        self.assertEqual(scope['source'],'client_message');self.assertFalse(scope['component_fault_confirmed'])
        intent=contacts.intent_text('\n'.join(t for d,t in rows if d=='in'),facts)
        self.assertEqual(ids(intent),{'pc'})

    def test_an_unrelated_yes_or_two_questions_do_not_confirm_a_host(self):
        for prompt in ('Вам 18 есть?','Видеокарта вставлена в ПК? Вам 18 есть?'):
            out=self.run_action([('in',self.symptom),('out',prompt),('in','Да конечно')])
            self.assertEqual(out['action'],'question');self.assertRegex(out['reply'],'[Кк]омпьютер|ПК')
            self.assertEqual(out['facts']['graphics_scope']['kind'],'device_uncertain')

    def test_explicit_host_report_uses_pc_diagnostics_not_gpu_repair_minimum(self):
        rows=[('in','Видеокарта установлена в компьютере, но нет изображения'),('in','Сколько стоит диагностика?')]
        out=self.run_action(rows)
        self.assertEqual(out['action'],'question');self.assertRegex(out['reply'],'1000')
        self.assertRegex(out['reply'],'бесплат');self.assertNotIn('5000',out['reply'])
        self.assertIsNone(prices.mandatory(messages(*rows),known(),'\n'.join(t for _,t in rows)))

    def test_a_diagnostic_followup_keeps_the_contextual_host_answer(self):
        out=self.run_action([('in',self.symptom),('out','Видеокарта вставлена в ПК?'),('in','Да конечно'),
                            ('in','Сколько это будет стоить?'),
                            ('out','Диагностика?'),('in','Да')])
        self.assertEqual(out['action'],'question');self.assertRegex(out['reply'],'1000')
        self.assertRegex(out['reply'],'бесплат');self.assertNotIn('5000',out['reply'])

    def test_accepting_a_diagnostic_service_does_not_invent_a_price_question(self):
        for rows in [messages(('in','Компьютер не включается'),('out','Диагностика?'),('in','Да')),
                     messages(('in','Сколько стоит?'),('out','После осмотра скажу'),('out','Диагностика?'),('in','Да')),
                     messages(('in','Сколько стоит?'),('out','Диагностика? Вам 18 есть?'),('in','Да'))]:
            self.assertFalse(prices._confirmed_diagnostic_price_question(rows))

    def test_confirmed_black_display_does_not_repeat_the_known_problem(self):
        out=self.run_action([('in',self.symptom),('out','Видеокарта вставлена в ПК?'),('in','Да конечно')])
        self.assertEqual(out['action'],'question')
        self.assertNotRegex(out['reply'],'что.{0,15}случилось|какая.{0,15}проблема|5000')

    def test_a_host_question_never_becomes_a_fact_from_staff_words(self):
        facts=contacts.collect(messages(('in',self.symptom),('out','У вас точно видеокарта в ПК, я понял')))
        self.assertEqual(facts['graphics_scope']['kind'],'device_uncertain')

    def test_missing_host_does_not_reask_or_assume_a_gpu_repair(self):
        out=self.run_action([('in',self.symptom),('out','Видеокарта установлена в компьютере?'),('in','Нет')])
        self.assertEqual(out['action'],'handoff');self.assertNotIn('5000',out['reply'])
        self.assertRegex(out['reason'],'отдельн|оператор')

    def test_unknown_host_answer_is_not_repeated(self):
        out=self.run_action([('in',self.symptom),('out','Видеокарта установлена в компьютере?'),('in','Не знаю')])
        self.assertEqual(out['action'],'handoff')

    def test_explicit_gpu_repair_still_requires_its_5000_minimum(self):
        text='Нужен ремонт видеокарты, пайка. В компьютере нет изображения'
        out=prices.mandatory(messages(('in',text)),known(),text)
        self.assertEqual(out['amounts'],[5000]);self.assertIn('DOC-L0152',out['rules'])

    def test_pc_repair_near_a_working_card_does_not_become_card_repair(self):
        text='Нужен ремонт компьютера после установки видеокарты, нет картинки'
        facts=contacts.collect(messages(('in',text)))
        self.assertEqual(facts['graphics_scope']['kind'],'host_diagnostic')
        self.assertEqual(ids(contacts.intent_text(text,facts)),{'pc'})
        self.assertIsNone(prices.mandatory(messages(('in',text)),known(),text))

    def test_no_to_installation_does_not_prove_absence_of_a_pc(self):
        facts=contacts.collect(messages(('in',self.symptom),('out','Видеокарта вставлена в ПК?'),('in','Нет')))
        self.assertEqual(facts['graphics_scope']['kind'],'device_uncertain')
        self.assertTrue(facts['graphics_scope']['host_confirmation_negative'])

    def test_normal_form_uses_the_same_source_bound_graphics_scope(self):
        rows=[('in',self.symptom),('out','Видеокарта вставлена в ПК?'),('in','Да конечно')]
        out=self.run_action(rows,'checklist')
        self.assertEqual(out['facts']['graphics_scope']['kind'],'host_diagnostic')
        self.assertNotIn('5000',out['reason']);self.assertNotIn('DOC-L0152',out['rule_ids'])
        pending=self.run_action([('in',self.symptom)],'checklist')
        row=next(r for r in pending['results'] if r['key']=='graphics_host')
        self.assertFalse(row['done']);self.assertRegex(row['item'],'[Кк]омпьютер|ПК')
        self.assertTrue(pending['manual_creation']['available'])
