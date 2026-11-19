"""Availability answers in a multi-question staff turn are not booked slots."""
import json,os,tempfile,unittest
from unittest.mock import patch
import test_dialogue_context150 as fixture
import extension_assistant as ext
from assistant_store import Store


def timeline(body='Вечером ближе к 19.00 буду',**extra):
    rows=[dict(id='job',body='Нужна врезка мойки',speaker_role='client',delivery_status='delivered'),dict(id='timeq',body='Так вам вечером во сколько удобно будет?',speaker_role='staff',delivery_status='delivered'),dict(id='materialq',body='И какой материал столешницы?',speaker_role='staff',delivery_status='delivered'),dict(id='answer',body=body,speaker_role='client',delivery_status='delivered',**extra)]
    # Match the complete source-timeline contract; delivery requires an actual
    # outgoing direction, not only a staff label in a hand-built helper row.
    for i,row in enumerate(rows):row.update(position=i,review_ref='context-position:'+str(i),
                                          direction='in' if row['speaker_role']=='client' else 'out')
    return rows


class VisitTimeAnswer153Tests(unittest.TestCase):
    def test_multi_question_staff_turn_binds_the_time_question(self):
        h=timeline();v=ext._client_visit_time_answer(h,h[-1]);self.assertEqual(v['question_evidence_id'],'timeq');self.assertEqual(v['staff_block_evidence_ids'],['timeq','materialq']);self.assertFalse(v['appointment_confirmed']);self.assertFalse(v['CRM_write_confirmed'])
    def test_answer_keeps_literal_daypart_and_approximation(self):
        h=timeline();v=ext._client_visit_time_answer(h,h[-1]);self.assertIn(h[-1]['body'],v['literal_meaning']);self.assertIn('не установлены',v['literal_meaning'])
    def test_call_purchase_or_material_timing_is_not_a_visit_preference(self):
        for body in ['Вечером к 19 позвоню','Материалы привезу к 19','Куплю к 19','Если смогу, к 19 буду','К 19 или завтра','Вчера к 19 был','К 19 будут запчасти','Вы приедете к 19?','Назначаю вам 19','Я сказал: «К 19 буду»']:
            h=timeline(body)
            with self.subTest(body=body):self.assertIsNone(ext._client_visit_time_answer(h,h[-1]))
    def test_failed_or_pending_time_question_cannot_bind(self):
        for status in ['failed','pending','queued','cancelled']:
            h=timeline();h[1]['delivery_status']=status
            with self.subTest(status=status):self.assertIsNone(ext._client_visit_time_answer(h,h[-1]))
    def test_intervening_client_turn_stops_binding(self):
        h=timeline();h[1]['speaker_role']='client';self.assertIsNone(ext._client_visit_time_answer(h,h[-1]))
    def test_two_time_questions_do_not_choose_an_arbitrary_one(self):
        h=timeline();h[2]['body']='На какое время удобно?';self.assertIsNone(ext._client_visit_time_answer(h,h[-1]))
    def test_already_booked_staff_claim_is_not_recast_as_a_fresh_preference(self):
        h=timeline();h[2]['body']='Записал к 19';self.assertIsNone(ext._client_visit_time_answer(h,h[-1]))
    def test_callback_time_question_does_not_bind_as_work_visit(self):
        h=timeline();h[1]['body']='Во сколько удобно позвонить?';self.assertIsNone(ext._client_visit_time_answer(h,h[-1]))
    def test_service_note_cannot_supply_a_staff_time_question(self):
        h=timeline();h[1]['speaker_role']='service';self.assertIsNone(ext._client_visit_time_answer(h,h[-1]))
    def test_long_answer_is_not_truncated_to_force_the_native_enum(self):
        h=timeline('Вечером к 19 буду '+('я '*65));self.assertIsNone(ext._client_visit_time_answer(h,h[-1]))
    def preview(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='synthetic153',LEADBOT_PERSONAL_AUTO_AVAILABLE='0');env.start();self.addCleanup(env.stop)
        h=fixture.cabinet()+[fixture.row('Подсоединить раковину, надо прорезь в столешнице сделать',mid='scope'),fixture.row('Так вам вечером во сколько удобно будет?','out','actualtimeq'),fixture.row('И какой материал столешницы?','out','materialq'),fixture.row('Вечером ближе к 19.00 буду',mid='answer')]
        app=ext.Assistant(Store(tmp.name+'/db'));o,status=app.handle(dict(owner='synthetic153',action='preview',wording_mode='neural_review',ctx=dict(convId='synthetic153-'+self.id().split('.')[-1],city='Томск',dir='mnc',channel='avito',partner='7',origin='С1',accountTitle='Учебный МНЧ',itemTitle='Сборка мебели',messages=h)))
        self.assertEqual(status,200);self.assertFalse(o['auto_enabled']);self.assertFalse(o['lead']['can_create_automatically']);return o,json.loads(o['model_task']['task'])
    def test_native_meaning_is_literal_time_preference_not_material_or_booking(self):
        o,t=self.preview();self.assertEqual(t['visit_time_answer_context']['question_evidence_id'],'actualtimeq');self.assertEqual(t['decision']['next_question']['kind'],'countertop_material');v=t['output_contract']['fixed_latest_client_meaning'];self.assertIn('Вечером ближе к 19.00 буду',v);s=o['model_task']['response_format']['schema']['properties']['context_review']['properties'];self.assertEqual(s['latest_client_meaning']['enum'],[v]);self.assertEqual(o['qualification']['countertop_material']['status'],'missing')
    def test_actual_native152_assignment_is_rejected_and_literal_meaning_passes(self):
        o,t=self.preview();c=dict(reply=t['proposed_reply'],needs_operator=False,context_review=dict(last_intent='Заказать врезку мойки и договориться о времени',latest_client_meaning='Назначаю удобное вечернее время визита — около 19:00',selected_step_fits=True,evidence_ids=[t['latest_client_message']['evidence_id']],note='Материал неизвестен; запись не подтверждена.'))
        self.assertIn('unconfirmed_visit_time_assignment',ext._context_review(c,t)[2]);c['context_review']['latest_client_meaning']=t['output_contract']['fixed_latest_client_meaning'];self.assertFalse(ext._context_review(c,t)[2])
