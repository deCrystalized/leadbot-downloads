import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import dialogue_lifecycle as lifecycle
from assistant_store import Store
from extension_assistant import Assistant
import contact_facts
import qualification_state as qs


NOW=datetime(2026,10,27,tzinfo=timezone.utc)


def row(text, **extra):
    return dict(id='client-wait',direction='in',sender_type='client',body=text,
                created_at=NOW.isoformat(),**extra)


class MixedPause210Tests(unittest.TestCase):
    def pause(self,text,**extra):
        return lifecycle.short_client_pause([row(text,**extra)],now=NOW)

    def test_completed_wall_answer_and_own_pending_measurement_wait(self):
        value=self.pause('Стена кирпичная. Секунду, уточню ширину полки.')
        self.assertEqual(value['status'],'waiting')
        self.assertEqual(value['grace_seconds'],60)
        self.assertEqual(value['completed_information_quote'],'стена кирпичная')
        self.assertEqual(value['purpose_quote'],'уточню ширину полки')

    def test_contact_is_not_refused_while_client_is_finding_it(self):
        value=self.pause('Понял, номер пока найду, подождите пожалуйста.')
        self.assertEqual(value['status'],'waiting')
        self.assertFalse(value['duration_explicit'])

    def test_explicit_duration_after_completed_information_is_preserved(self):
        value=self.pause('Стена кирпичная; дайте две минуты, проверю крепёж.')
        self.assertEqual(value['status'],'waiting');self.assertEqual(value['grace_seconds'],120)
        self.assertTrue(value['duration_explicit'])

    def test_full_long_history17_pending_followup_motif_is_wait_not_lpr_result(self):
        text='Сейчас уточню будет кто дома , и дам вам знать'
        value=self.pause(text);self.assertEqual(value['status'],'waiting')
        self.assertIn('уточню',value['purpose_quote'])
        self.assertEqual(qs.inspect([row(text)])['decision_maker']['status'],'missing')

    def test_new_substantive_client_turn_cancels_old_pause(self):
        messages=[row('Стена кирпичная. Секунду, уточню ширину полки.'),
                  dict(row('Полка 80 сантиметров.'),id='next',created_at=(NOW+timedelta(seconds=10)).isoformat())]
        self.assertEqual(lifecycle.short_client_pause(messages,now=NOW+timedelta(seconds=11))['status'],'not_applicable')

    def test_original_time_anchor_and_expiration_not_renewed(self):
        message=row('Стена кирпичная. Секунду, уточню размер.')
        self.assertEqual(lifecycle.short_client_pause([message],now=NOW+timedelta(seconds=59))['status'],'waiting')
        self.assertEqual(lifecycle.short_client_pause([message],now=NOW+timedelta(seconds=61))['status'],'elapsed')

    def test_unverified_clock_is_not_treated_as_a_verified_pause(self):
        value=self.pause('Стена кирпичная. Секунду, уточню размер.',short_pause_clock_unverified=True)
        self.assertEqual(value['status'],'unavailable')

    def test_other_roles_cannot_request_the_client_pause(self):
        for sender in ('operator','system','avito','assistant','bot'):
            message=row('Стена кирпичная. Секунду, уточню размер.');message['sender_type']=sender
            with self.subTest(sender=sender):
                self.assertEqual(lifecycle.short_client_pause([message],now=NOW)['status'],'not_applicable')

    def test_failed_and_pending_messages_are_not_completed_client_requests(self):
        for status in ('failed','pending','sending'):
            with self.subTest(status=status):
                self.assertEqual(self.pause('Стена кирпичная. Секунду, уточню размер.',delivery_status=status)['status'],'not_applicable')

    def test_reported_quoted_negated_and_hypothetical_actions_are_not_pause(self):
        for text in ('Сосед сказал: «Секунду, уточню ширину».',
                     'Если нужно будет, сейчас уточню и дам вам знать.',
                     'Сейчас не уточню и не дам вам знать.',
                     'Стена кирпичная. Секунду, не пришлю размеры.',
                     'Мастер написал: подождите пожалуйста.'):
            with self.subTest(text=text):self.assertEqual(self.pause(text)['status'],'not_applicable')

    def test_current_question_is_not_hidden_by_a_wait_word(self):
        for text in ('Стена кирпичная. Секунду, а по цене сколько?',
                     'Подождите, а материалы у вас есть?',
                     'Я подожду вашего ответа: привезёте крепёж?'):
            with self.subTest(text=text):self.assertEqual(self.pause(text)['status'],'not_applicable')

    def test_actual468_symptom_duration_and_work_duration_are_not_pause(self):
        for text in ('Сам ПК новый, сейчас когда нажимаю кнопку включения он не реагирует включается подсветка на секунду и все',
                     'Подсветка включается, секунду.', 'Сборка заняла, минуту.',
                     'За две минуты сможете повесить полку?',
                     'Раньше сейчас уточню и дам вам знать говорил сосед.'):
            with self.subTest(text=text):self.assertEqual(self.pause(text)['status'],'not_applicable')

    def test_waiting_for_operator_answer_is_not_own_pending_information(self):
        self.assertEqual(self.pause('Сейчас жду вашего ответа, затем дам вам знать.')['status'],'not_applicable')
        self.assertEqual(self.pause('Сейчас уточните и дайте мне знать.')['status'],'not_applicable')


class AssistantMixedPause210Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='owner',LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start();self.addCleanup(env.stop)
        self.app=Assistant(Store(Path(self.tmp.name)/'assistant.sqlite3'))

    def ctx(self,messages,**extra):
        return dict(convId='synthetic210',dir='mnc',city='Чита',partner='7',accountTitle='Мастер МНЧ',
                    itemTitle='Мастер на час',origin='С1',adIdentity='Мастер',messages=messages,**extra)

    def preview(self,messages,**extra):
        return self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',ctx=self.ctx(messages,**extra)))

    def test_actual_preview_waits_without_model_and_retains_completed_wall_fact(self):
        messages=[dict(row('Нужно повесить полку в квартире, схема есть, крепёж куплен.'),id='first'),
                  dict(id='ask',direction='out',sender_type='operator',body='Из какого материала стены?',delivery_status='delivered'),
                  row('Стена кирпичная. Секунду, уточню ширину полки.')]
        out,code=self.preview(messages)
        self.assertEqual(code,200);self.assertEqual(out['action'],'wait');self.assertEqual(out['reply'],'')
        self.assertFalse(out.get('pending_model'));self.assertFalse(out['needs_operator'])
        fields=qs.inspect(messages)
        self.assertEqual(fields['wall']['status'],'answered');self.assertIn('кирпич',str(fields['wall']['value']).lower())

    def test_existing_booking_guard_still_precedes_client_pause(self):
        messages=[dict(row('Нужно повесить полку.'),id='first'),
                  dict(id='staff',direction='out',sender_type='operator',body='Хорошо, записал вас — до встречи.',delivery_status='delivered'),
                  row('Стена кирпичная. Секунду, уточню размер.')]
        out,code=self.preview(messages)
        self.assertEqual(code,200);self.assertEqual(out['action'],'handoff');self.assertNotEqual(out.get('step'),'reply')

    def test_unrelated_system_event_does_not_turn_a_completed_answer_into_new_input(self):
        messages=[row('Стена кирпичная. Секунду, уточню размер.'),
                  dict(id='system',direction='system',sender_type='system',body='Диалог назначен')]
        out,code=self.preview(messages)
        self.assertEqual(code,200);self.assertFalse(out.get('pending_model'));self.assertEqual(out['reply'],'')


if __name__=='__main__':unittest.main()
