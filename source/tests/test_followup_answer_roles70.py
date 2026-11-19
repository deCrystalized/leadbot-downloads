"""Answers bind to the current question; closure is not new intake."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_policy as policy
from assistant_store import Store
from extension_assistant import Assistant


def messages(*rows):
    return [dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)]


class FollowupAnswerRoleTests(unittest.TestCase):
    def test_yes_to_relevance_does_not_accept_an_old_relative_slot(self):
        rows=messages(('out','Через час-полтора удобно?'),('out','Номер телефона напишите'),
                      ('out','Актуально?'),('in','Да конечно'))
        self.assertIsNone(policy._accepted_staff_visit(rows))

    def test_yes_to_presence_does_not_accept_an_old_relative_slot(self):
        rows=messages(('out','Через час-полтора удобно?'),('out','Вы тут?'),('in','Да'))
        self.assertIsNone(policy._accepted_staff_visit(rows))

    def test_presence_question_in_the_same_message_is_still_ambiguous(self):
        rows=messages(('out','К 12 удобно? Вы здесь?'),('in','Да'))
        self.assertIsNone(policy._accepted_staff_visit(rows))

    def test_explicit_slot_choice_resolves_a_presence_followup(self):
        rows=messages(('out','К 12 удобно?'),('out','Вы тут?'),('in','В 12'))
        found=policy._accepted_staff_visit(rows)
        self.assertEqual(found['proposal_message_id'],'0')
        self.assertEqual(found['answer_message_id'],'2')

    def test_range_end_is_not_mistaken_for_minutes_of_a_clock(self):
        rows=messages(('out','К 12–14 удобно?'),('out','Вы тут?'),('in','В 12:14'))
        self.assertIsNone(policy._accepted_staff_visit(rows))

    def test_a_phone_request_does_not_erase_an_unambiguous_slot(self):
        rows=messages(('out','Через час-полтора удобно?'),('out','Номер телефона напишите'),('in','Да конечно'))
        self.assertEqual(policy._accepted_staff_visit(rows)['proposal_message_id'],'0')

    def test_later_presence_does_not_erase_an_already_accepted_visit(self):
        rows=messages(('out','К 12 удобно?'),('in','Да'),('out','Вы тут?'),('in','Да'))
        self.assertEqual(policy._accepted_staff_visit(rows)['answer_message_id'],'1')

    def test_later_discussion_is_not_a_visit(self):
        self.assertIsNone(policy._accepted_staff_visit(messages(
            ('out','Давайте в 10 спишемся и обсудим'),('in','Хорошо'))))

    def test_a_claimed_booking_is_lookup_evidence_without_accepting_a_slot(self):
        rows=messages(('out','К 12 удобно?'),('out','Вы тут?'),('in','Да'),
                      ('out','Хорошо, записал вас — до встречи'),('in','Ок'))
        self.assertIsNone(policy._accepted_staff_visit(rows))
        claim=policy._staff_booking_claim(rows)
        self.assertEqual(claim['message_id'],'3')
        self.assertFalse(claim['crm_write_confirmed'])
        self.assertEqual(claim['source'],'staff_statement_unverified')

    def test_possible_negated_or_pending_booking_is_not_a_completed_claim(self):
        for text in ('Записать вас?', 'Я не записал вас','Если вы записаны, проверьте номер','Записал вас?'):
            self.assertIsNone(policy._staff_booking_claim(messages(('out',text))),text)
        self.assertIsNone(policy._staff_booking_claim([dict(id='a',direction='out',body='Записал вас',out_pending=True)]))

    def test_disputed_document_charges_are_client_allegations_not_tariffs(self):
        body='Цены бешеные, в договоре поставили планка 550 руб это моя, за одну дырку 3000 руб и еще приписка'
        evidence=policy._post_service_price_complaint(messages(('in',body)))
        self.assertEqual(len(evidence),1)
        self.assertEqual(evidence[0]['source'],'client_report_unverified')
        self.assertEqual(evidence[0]['kind'],'disputed_document_charge')
        self.assertEqual(evidence[0]['quote'],body)
        for text in ('А если в договоре напишут 3000 рублей, это обман?',
                     'Сколько будет стоить работа, в договоре укажете?',
                     'В договоре указали 3000 рублей, спасибо',
                     'Сделка состоялась. В договоре написали лишние 3000 рублей, обман'):
            self.assertFalse(policy._post_service_price_complaint(messages(('in',text))),text)

    def test_clear_short_declines_are_not_missing_material_answers(self):
        self.assertTrue(policy._client_declined('Нет тогда','Когда удобно, чтобы я приехал?'))
        self.assertTrue(policy._client_declined('Понятно, не надо','Давайте приеду и рассчитаю'))
        self.assertTrue(policy._client_declined('Понятно, ненадо','Давайте приеду и рассчитаю'))
        self.assertFalse(policy._client_declined('Нет тогда','Материалы уже есть?'))
        self.assertFalse(policy._client_declined('Нет, тогда сколько диагностика?','Когда удобно?'))
        self.assertTrue(policy._client_declined('Я сама соберу, если это настолько сложно и дорого. Не надо.','Схема есть?'))
        self.assertFalse(policy._client_declined('Если дорого, не надо','Когда удобно?'))

    def test_polite_closure_does_not_swallow_a_new_question(self):
        self.assertTrue(policy._conversation_closed('Ладно спасибо','Мне надо смотреть холодильник'))
        self.assertFalse(policy._conversation_closed('Ладно спасибо. А диагностика сколько?','Мне надо смотреть'))
        self.assertTrue(policy._conversation_closed('Принято','К сожалению, я не смогу помочь'))
        self.assertFalse(policy._conversation_closed('Принято','От 1500 рублей, устраивает?'))

    def test_contact_profile_answer_closes_only_a_contact_question(self):
        self.assertTrue(policy._conversation_closed('ок','В шапке профиля есть','У вас есть контактный телефон?'))
        self.assertFalse(policy._conversation_closed('ок','В шапке профиля есть цена, устраивает?','У вас есть контактный телефон?'))
        self.assertFalse(policy._conversation_closed('ок','В шапке профиля есть','Схема есть?'))

    def test_a_decline_waits_despite_unread_images_but_never_cancels_a_visit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,LEADBOT_ASSISTANT_WORDING='reviewed'):
            app=Assistant(Store(tmp+'/db'))
            def preview(rows):
                ms=messages(*rows)
                ms.insert(1,dict(id='photo',direction='in',body='',attachments=[dict(kind='image',url='https://example.invalid/image.jpg')]))
                out,code=app.handle(dict(owner='offline-followup70',action='preview',ctx=dict(
                    convId='synthetic-followup70',city='Оренбург',dir='mnc',partner='7',channel='avito',
                    accountTitle='Иван МНЧ',itemTitle='Мастер на час',messages=ms)))
                self.assertEqual(code,200);self.assertFalse(out['auto_enabled'])
                return out
            out=preview([('in','Собрать шкаф'),('out','Когда удобно, чтобы я приехал?'),('in','Нет тогда')])
            self.assertEqual(out['action'],'wait')
            self.assertTrue(out['crm_flags']['customer_declined'])
            out=preview([('in','Собрать шкаф'),('out','К 12 удобно?'),('in','Да'),('in','Нет тогда')])
            self.assertEqual(out['action'],'handoff')
            self.assertRegex(out['reason'],'договорённость')
            out=preview([('in','Собрать шкаф'),('out','К 12 удобно?'),('out','Вы тут?'),('in','Да'),
                         ('out','Записал вас'),('in','А цена?')])
            self.assertEqual(out['action'],'handoff')
            self.assertFalse(out.get('existing_visit_evidence'))
            self.assertEqual(out['staff_booking_claim']['message_id'],'4')
            self.assertFalse(out['staff_booking_claim']['crm_write_confirmed'])
