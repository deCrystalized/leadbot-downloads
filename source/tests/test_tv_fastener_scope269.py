"""A known bracket purchase narrows the next TV installation question."""
import json
from pathlib import Path
import tempfile
import unittest

from assistant_store import Store
from extension_assistant import Assistant
import qualification_state as qs
import test_tv_intake267 as tv


INITIAL = ('Здравствуйте. В Чите нужно повесить на бетонную стену два телевизора: 43 и 55 дюймов. '
           'Кронштейны уже купили, телевизоры исправны. Какая стоимость за оба вместе с установкой кронштейнов?')
SPECIFIC = 'Подходящий крепёж для навеса уже есть?'


class TvFastenerScopeTests(unittest.TestCase):
    def preview(self, messages):
        return tv.TvCurrentQuestion267Tests().preview(messages)

    def test_original_rejected_shape_keeps_price_stage_and_asks_only_fasteners(self):
        for wording in ('уже купили', 'уже куплены'):
            with self.subTest(wording=wording):
                messages = [tv.row(INITIAL.replace('уже купили', wording), 'c1')]
                result = self.preview(messages)
                self.assertEqual(result['reply'], 'Здравствуйте! Точную стоимость скажу после осмотра. ' + SPECIFIC)
                self.assertFalse(result['needs_operator'])
                self.assertEqual(qs.inspect(messages)['materials']['status'], 'missing')

    def test_report_of_all_current_fasteners_preserves_already_answered_inventory(self):
        rows = [tv.row(INITIAL, 'c1'),
                tv.row('Весь крепёж уже куплен. Кронштейны и телевизоры уже на месте.', 'full')]
        self.assertEqual(qs.inspect(rows)['materials']['status'], 'answered')
        self.assertNotIn(SPECIFIC, self.preview(rows)['reply'])

    def test_quoted_conditional_other_past_or_future_brackets_are_not_present(self):
        initial = tv.row(INITIAL.split('Кронштейны уже купили')[0], 'work')
        for detail in ('Если есть кронштейны, кронштейны купили.', 'Сосед сказал, что кронштейны куплены.',
                       '«Кронштейны куплены».', 'Раньше кронштейны купили.', 'Кронштейны купим завтра.',
                       'Кронштейны куплены для другого заказа.', 'Кронштейны не купили.',
                       'Если кронштейны куплены, хорошо.', 'Кронштейны куплены в прошлом году.',
                       'Не все кронштейны куплены.'):
            with self.subTest(detail=detail):
                materials = qs.inspect([initial, tv.row(detail, 'stock')])['materials']
                self.assertFalse(materials.get('tv_brackets'))
                self.assertNotEqual(materials['status'], 'answered')
        revoked = qs.inspect([tv.row(INITIAL, 'c1'), tv.row('Кронштейны вернули.', 'return')])['materials']
        self.assertFalse(revoked.get('tv_brackets'))
        self.assertNotEqual(revoked['status'], 'answered')

    def test_staff_and_system_are_not_current_inventory_sources(self):
        work = tv.row(INITIAL.split('Кронштейны уже купили')[0], 'work')
        for stock in (tv.row('Кронштейны уже купили.', 'staff', 'out'),
                      tv.row('Кронштейны уже купили.', 'system', speaker_role='service'),
                      tv.row('Кронштейны уже купили.', 'unfinished', voice_transcript_status='processing')):
            with self.subTest(stock=stock['id']):
                self.assertFalse(qs.inspect([work, stock])['materials'].get('tv_brackets'))

    def test_delivered_targeted_question_binds_only_the_actual_answer(self):
        for answer, value in [('Да.', 'yes'), ('Нет.', 'no')]:
            rows = [tv.row(INITIAL, 'c1'), tv.row(SPECIFIC, 'sent', 'out'), tv.row(answer, 'answer')]
            materials = qs.inspect(rows)['materials']
            self.assertEqual((materials['status'], materials['value']), ('answered', value))
            self.assertEqual(materials['question_message_id'], 'sent')
            self.assertEqual(materials['availability_subject'], 'подходящий крепёж для навеса телевизоров')
            rows[1]['delivery_status'] = 'failed'
            self.assertEqual(qs.inspect(rows)['materials']['status'], 'missing')
            rows[1] = tv.row('У соседа есть подходящий крепёж для навеса?', 'third-party', 'out')
            self.assertEqual(qs.inspect(rows)['materials']['status'], 'missing')

    def test_price_followup_does_not_repeat_ignored_fastener_question(self):
        rows = [tv.row(INITIAL, 'c1'),
                tv.row('Здравствуйте! Точную стоимость скажу после осмотра. ' + SPECIFIC, 'sent', 'out'),
                tv.row('Мне всё-таки нужно понять цену до выезда. Сколько будет стоить?', 'price2')]
        result = self.preview(rows)
        self.assertFalse(result['needs_operator'])
        self.assertIn('Выезд в черте города бесплатный.', result['reply'])
        self.assertNotIn('крепёж', result['reply'])
        self.assertEqual(qs.inspect(rows)['materials']['asked'], 1)

    def test_wording_guard_cannot_broaden_the_targeted_question(self):
        selected = {'wording_scope': 'tv_mount_fasteners_only'}
        self.assertTrue(qs.question_matches('Есть подходящий крепеж для телевизоров?', selected))
        for reply in ('Материалы и комплектующие есть?',
                      'Подходящий крепёж для навеса и кронштейны есть?',
                      SPECIFIC + ' Кронштейны купили?',
                      'Подходящий крепёж для дверей уже есть?',
                      'Неподходящий крепёж для навеса есть?',
                      'Подходящий крепёж для навеса есть у соседа?',
                      'У мастера будет подходящий крепёж для навеса?'):
            with self.subTest(reply=reply):
                self.assertFalse(qs.question_matches(reply, selected))

    def test_original_model_task_keeps_source_and_rejects_the_generic_reply(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Assistant(Store(Path(temporary) / 'db'))
            context = dict(convId='synthetic-tv269', dir='mnc', city='Чита', partner='7', channel='avito',
                           accountTitle='Георгий МНЧ', itemTitle='Мастер на час', messages=[tv.row(INITIAL, 'c1')])
            request = dict(owner='offline', action='preview', ctx=context, wording_mode='neural_review')
            prepared, status = app.handle(request)
            self.assertEqual(status, 200)
            self.assertTrue(prepared['pending_model'])
            task = json.loads(prepared['model_task']['task'])
            question = task['decision']['next_question']
            self.assertEqual(question['evidence_message_ids'], ['c1'])
            self.assertEqual(question['wording_scope'], 'tv_mount_fasteners_only')
            self.assertFalse(task['selected_question_history']['proposed_question_sent'])
            self.assertIn(SPECIFIC, task['proposed_reply'])
            candidate = dict(reply='Здравствуйте! Точную стоимость скажу после осмотра. Материалы и комплектующие есть?',
                             needs_operator=False, context_review=dict(last_intent='Цена навеса двух телевизоров',
                                 latest_client_meaning='Кронштейны купили, клиент спрашивает цену навеса.',
                                 selected_step_fits=True, evidence_ids=['c1'], note='Неизвестен подходящий крепёж.'))
            out, status = app.handle(dict(request, action='finalize', request_id=prepared['request_id'],
                                          revision=prepared['revision'], candidate=candidate))
            self.assertEqual(status, 200)
            self.assertIn('fixed_reply_changed', out['validation'])
            self.assertEqual(out['reply'], '')
