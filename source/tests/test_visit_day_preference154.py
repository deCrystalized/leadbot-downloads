"""Choose a day in the current turn without admitting or booking the job."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import contact_facts
import extension_assistant as ext
import test_dialogue_context150 as fixture
from assistant_store import Store


def history(answer='Хорошо. Если сегодня у вас не получается, давайте, на другой день',
            promise='Посмотрю по графику вам напишу'):
    return [fixture.row('Нужно собрать шкаф, схема есть, и врезать мойку в столешницу.', mid='scope'),
            fixture.row('Из какого материала столешница?', 'out', 'materialq'),
            fixture.row('Нужно сегодня вечером', mid='time'),
            fixture.row(promise, 'out', 'promise'), fixture.row(answer, mid='answer')]


class VisitDayPreference154Tests(unittest.TestCase):
    def test_conditional_alternative_preserves_source_and_no_booking(self):
        v = contact_facts.alternative_visit_day_preference(history())
        self.assertEqual((v['message_id'], v['staff_message_id']), ('answer', 'promise'))
        for key in ('day_chosen', 'availability_verified', 'appointment_confirmed', 'crm_write_confirmed'):
            self.assertIs(v[key], False)

    def test_direct_alternative_is_an_unselected_day(self):
        self.assertTrue(contact_facts.alternative_visit_day_preference(history('Давайте на другой день.')))

    def test_other_day_without_a_schedule_promise_stays_unbound(self):
        self.assertIsNone(contact_facts.alternative_visit_day_preference(history(promise='Из какого материала столешница?')))

    def test_callback_materials_and_delivery_promises_are_not_a_schedule_check(self):
        for promise in ('Уточню материалы вам напишу', 'Посмотрю по графику звонков вам напишу',
                        'Уточню график доставки вам напишу'):
            with self.subTest(promise=promise):
                self.assertIsNone(contact_facts.alternative_visit_day_preference(history(promise=promise)))

    def test_failed_or_pending_promise_cannot_bind(self):
        for status in ('failed', 'pending', 'queued', 'sending', 'cancelled'):
            h = history(); h[-2]['delivery_status'] = status
            with self.subTest(status=status):
                self.assertIsNone(contact_facts.alternative_visit_day_preference(h))

    def test_out_pending_flag_cannot_bind(self):
        h = history(); h[-2]['out_pending'] = True
        self.assertIsNone(contact_facts.alternative_visit_day_preference(h))

    def test_client_staff_and_service_actors_are_not_interchangeable(self):
        for actor in ('operator', 'employee', 'human', 'system', 'assistant', 'bot', 'avito'):
            h = history(); h[-1].update(sender_type=actor, role='client')
            with self.subTest(actor=actor):
                self.assertIsNone(contact_facts.alternative_visit_day_preference(h))

    def test_incoming_schedule_speech_cannot_supply_staff_promise(self):
        h = history(); h[-2].update(direction='in', sender_type='client', role='assistant')
        self.assertIsNone(contact_facts.alternative_visit_day_preference(h))

    def test_completed_negated_or_quoted_check_is_not_pending_promise(self):
        for promise in ('Посмотрел по графику вам написал', 'Не посмотрю по графику вам напишу',
                        '«Посмотрю по графику вам напишу»', 'Если посмотрю по графику вам напишу'):
            with self.subTest(promise=promise):
                self.assertIsNone(contact_facts.alternative_visit_day_preference(history(promise=promise)))

    def test_quoted_negated_and_nonvisit_alternatives_do_not_bind(self):
        for body in ('Клиент сказал: «Давайте на другой день»', 'Не давайте на другой день',
                     'Давайте на другой день позвоним', 'Если завтра не выйдет, не приезжайте',
                     'Давайте материалы на другой день', 'Давайте на другой день?',
                     'Вчера говорили: давайте на другой день'):
            with self.subTest(body=body):
                self.assertIsNone(contact_facts.alternative_visit_day_preference(history(body)))

    def preview(self, h=None, **known):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='synthetic154', LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start(); self.addCleanup(env.stop)
        ctx = dict(convId='synthetic154-' + self.id().split('.')[-1], city='Томск', dir='mnc',
                   channel='avito', partner='7', origin='С1', accountTitle='Учебный МНЧ',
                   itemTitle='Сборка мебели', messages=h or history())
        ctx.update(known)
        o, status = ext.Assistant(Store(tmp.name + '/db')).handle(dict(
            owner='synthetic154', action='preview', wording_mode='neural_review', ctx=ctx))
        self.assertEqual(status, 200)
        self.assertFalse(o['auto_enabled']); self.assertFalse(o['lead']['can_create_automatically'])
        return o, json.loads(o['model_task']['task']) if o.get('model_task') else None

    def test_current_day_choice_outranks_unanswered_material_without_filling_it(self):
        o, t = self.preview()
        self.assertEqual(t['decision']['next_question']['kind'], 'visit_day_preference')
        self.assertEqual(t['proposed_reply'], 'На какой день вам будет удобно?')
        self.assertEqual(o['qualification']['countertop_material']['status'], 'missing')
        self.assertFalse(t['visit_day_choice_context']['availability_verified'])
        self.assertFalse(t['planned_question_roles']['is_evidence_of_client_goal'])
        self.assertNotIn('fixed_latest_client_meaning', t['output_contract'])

    def test_after_day_question_the_missing_service_condition_is_still_required(self):
        h = history() + [fixture.row('На какой день вам будет удобно?', 'out', 'dayq'),
                         fixture.row('В пятницу вечером', mid='dayanswer')]
        o, t = self.preview(h)
        self.assertEqual(o['qualification']['countertop_material']['status'], 'missing')
        self.assertEqual(t['decision']['next_question']['kind'], 'countertop_material')

    def test_without_schedule_promise_material_question_remains(self):
        o, t = self.preview(history(promise='Понял'))
        self.assertEqual(t['decision']['next_question']['kind'], 'countertop_material')
        self.assertNotIn('visit_day_choice_context', t)

    def test_existing_booking_claim_cannot_become_new_day_collection(self):
        h = history(); h.insert(1, fixture.row('Записал вас на сегодня к 17', 'out', 'booked'))
        o, t = self.preview(h)
        self.assertNotEqual((t or {}).get('decision', {}).get('next_question', {}).get('kind'), 'visit_day_preference')

