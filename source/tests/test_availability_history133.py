"""An ambiguous yes stays bound to its question after later photos/replies."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import extension_assistant as ext
import personal_media
from assistant_store import Store, digest


class AvailabilityHistory133Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner')
        env.start(); self.addCleanup(env.stop)
        self.app = ext.Assistant(Store(tmp.name + '/db'))

    def prepare(self, later=None, photo=False):
        messages = [dict(id='job', direction='in', body='Сколько стоит собрать шкаф?'),
                    dict(id='staff', direction='out', body='У вас они в наличии уже?'),
                    dict(id='yes', direction='in', body='Да')]
        if photo:
            messages.append(dict(id='photo', direction='in', body='', attachments=[
                dict(kind='image', url='https://example.test/wardrobe.jpg')]))
        else:
            messages += later or [dict(id='price', direction='in', body='Меня цена интересует')]
        ctx = dict(convId='synthetic-history133', city='Уфа', dir='mnc', channel='avito',
                   partner='7', accountTitle='Учебный мастер МНЧ', origin='С1',
                   itemTitle='Сборка мебели', messages=messages)
        request = dict(owner='owner', action='preview', wording_mode='neural_review', ctx=ctx)
        if photo:
            before, code = self.app.handle(request)
            self.assertEqual(code, 200); self.assertFalse(before.get('pending_model'))
            self.assertEqual(before['action'], 'handoff')
            chat, parsed, known, _ = ext._parse(ctx)
            parsed = copy.deepcopy(parsed)
            parsed[-1].update(unread_media=False, media_reviewed=True, offline_fixture=True)
            personal_media.attach_observation(parsed[-1], dict(content_kind='product_photo',
                device_kind='wardrobe', model='Мартина2000x2016x520'), source='offline_reviewed_image')
            with patch.object(ext, '_parse', return_value=(chat, parsed, known, digest([parsed, known, ext.policy.VERSION]))):
                out, code = self.app.handle(request)
        else:
            out, code = self.app.handle(request)
        self.assertEqual(code, 200); self.assertTrue(out.get('pending_model'), out.get('reason'))
        return out, json.loads(out['model_task']['task'])

    def candidate(self, task):
        return dict(reply=task.get('fixed_reply') or task['proposed_reply'], needs_operator=False,
            context_review=dict(last_intent='Узнать стоимость сборки шкафа',
                latest_client_meaning='Клиент интересуется ценой сборки шкафа',
                selected_step_fits=True, evidence_ids=[task['latest_client_message']['evidence_id']],
                note='Следующий вопрос уместен, наличие комплектующих не подтверждено.'))

    def finish(self, out, candidate):
        final, code = self.app.handle(dict(owner='owner', action='finalize',
            request_id=out['request_id'], revision=out['revision'], candidate=candidate))
        self.assertEqual(code, 200); self.assertFalse(final['auto_enabled'])
        return final

    def test_original_native_photo_misunderstanding_is_rejected(self):
        out, task = self.prepare(photo=True); candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Отправлено фото шкафа, комплектующие в наличии'
        result = self.finish(out, candidate)
        self.assertFalse(result['reply'])
        self.assertIn('unconfirmed_availability_subject', result['validation'])

    def test_later_text_does_not_erase_the_bound_question(self):
        _, task = self.prepare()
        context = task['prior_availability_answers'][0]
        self.assertEqual(context['question_evidence_id'], 'staff')
        self.assertEqual(context['answer_evidence_id'], 'yes')
        self.assertEqual(context['question_quote'], 'У вас они в наличии уже?')
        self.assertIn('parts_materials', context['unsupported_presence_subjects'])
        self.assertNotIn('fixed_latest_client_meaning', task['output_contract'])
        self.assertLess(list(task).index('prior_availability_answers'), list(task).index('primary_sources'))

    def test_invented_materials_in_note_rejected_after_later_text(self):
        out, task = self.prepare(); candidate = self.candidate(task)
        candidate['context_review']['note'] = 'Материалы уже есть, уточняем инструкцию'
        self.assertIn('unconfirmed_availability_subject', self.finish(out, candidate)['validation'])

    def test_invented_instruction_in_goal_rejected_after_photo(self):
        out, task = self.prepare(photo=True); candidate = self.candidate(task)
        candidate['context_review']['last_intent'] = 'Сборка шкафа, инструкция есть'
        self.assertIn('unconfirmed_availability_subject', self.finish(out, candidate)['validation'])

    def test_grounded_photo_meaning_and_question_accepted(self):
        out, task = self.prepare(photo=True); candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Отправлено фото шкафа'
        result = self.finish(out, candidate)
        self.assertTrue(result['reply']); self.assertEqual(result['validation'], [])

    def test_explicit_later_client_facts_are_not_erased(self):
        out, task = self.prepare(later=[dict(id='parts', direction='in', body='Комплектующие есть')])
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Клиент подтвердил наличие комплектующих'
        result = self.finish(out, candidate)
        self.assertTrue(result['reply']); self.assertEqual(result['validation'], [])

    def test_later_named_question_with_yes_can_confirm_instructions(self):
        out, task = self.prepare(later=[dict(id='instruction', direction='out', body='Инструкция сборки есть?'),
                                      dict(id='instructions-yes', direction='in', body='Да')])
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Клиент подтвердил наличие инструкции'
        result = self.finish(out, candidate)
        self.assertTrue(result['reply']); self.assertEqual(result['validation'], [])

    def test_unanswered_staff_question_does_not_confirm_parts(self):
        out, task = self.prepare(later=[dict(id='parts-q', direction='out', body='Комплектующие есть?'),
                                      dict(id='price', direction='in', body='Меня цена интересует')])
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Комплектующие уже в наличии'
        self.assertIn('unconfirmed_availability_subject', self.finish(out, candidate)['validation'])
