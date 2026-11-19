"""Natural selected questions keep their source, disclosures and action fences."""
import copy
import unittest

import experience_wording as wording
import research_proposals as proposals
from assistant_store import digest
import test_native_wording209 as native_fixture


QUESTION = dict(kind='place',
    question='Где будут проводиться работы: квартира, частный дом или организация?',
    groups=[['где', 'квартир', 'дом']])
NATURAL = 'Где будут проводиться работы: в квартире, частном доме или организации?'
ORIGINAL_REPLY = ('Здравствуйте! Работаем с выездом. До оформления заявки уточним условия работы. '
                  + NATURAL)


class SelectedWordingFrame259Tests(unittest.TestCase):
    def setUp(self):
        self.question = copy.deepcopy(QUESTION)
        self.experience = dict(examples=[], conversation_style={})

    def accepts(self, reply, question=None, experience=None, status='provided'):
        return wording.verified_question(reply, question or self.question,
            self.experience if experience is None else experience, status)

    def test_natural_case_and_original_selected_colon_are_accepted(self):
        self.assertTrue(self.accepts(NATURAL))

    def test_case_form_is_also_accepted_without_colon(self):
        self.assertTrue(self.accepts(NATURAL.replace(':', '')))

    def test_canonical_question_itself_is_a_valid_wording_frame(self):
        self.assertTrue(self.accepts(QUESTION['question']))

    def test_colon_cannot_be_added_when_absent_from_selected_question(self):
        q = dict(question='Схема или инструкция сборки есть?', groups=[['схем', 'инструкц']])
        self.assertFalse(self.accepts('Схема: инструкция сборки есть?', q))

    def test_additional_colon_does_not_become_a_second_assertion_frame(self):
        self.assertFalse(self.accepts(NATURAL.replace('в квартире,', 'в квартире:')))

    def test_new_room_or_building_cannot_enter_the_selected_scope(self):
        self.assertFalse(self.accepts(NATURAL.replace('доме', 'гараже')))

    def test_declension_does_not_authorize_a_different_house_object(self):
        self.assertFalse(self.accepts(NATURAL.replace('доме', 'домике')))

    def test_price_and_new_assertion_still_fail(self):
        for reply in (NATURAL.replace('работы:', 'работы за 800 рублей:'),
                      'Завтра приеду. ' + NATURAL):
            with self.subTest(reply=reply):
                self.assertFalse(self.accepts(reply))

    def test_negation_and_extra_questions_still_fail(self):
        for reply in (NATURAL.replace('в квартире', 'не в квартире'),
                      NATURAL + ' Телефон подскажите?'):
            with self.subTest(reply=reply):
                self.assertFalse(self.accepts(reply))

    def test_short_root_cannot_be_authorized_only_by_a_historical_example(self):
        q = dict(kind='place', question='Где будут работы: квартира или организация?',
                 groups=[['квартир', 'организац']])
        experience = dict(examples=[dict(staff_question='Частный дом?')])
        self.assertFalse(self.accepts(NATURAL, q, experience))

    def test_current_review_and_source_context_are_still_required(self):
        self.assertFalse(self.accepts(NATURAL, experience={}))
        self.assertFalse(self.accepts(NATURAL, status='invalid'))

    def test_review_does_not_mutate_question_or_experience(self):
        before = copy.deepcopy((self.question, self.experience))
        self.accepts(NATURAL)
        self.assertEqual((self.question, self.experience), before)


class NativeWordingFrame259Tests(unittest.TestCase):
    setUp = native_fixture.NativeWording209Tests.setUp
    tearDown = native_fixture.NativeWording209Tests.tearDown

    def source(self):
        self.ctx.update(itemTitle='Сантехника', messages=[
            dict(id='client-price', direction='in', sender_type='client',
                 body='Здравствуйте! Нужно заменить 2 смесителя в ванной. Оба смесителя куплены, материалы есть. Как это происходит'),
            dict(id='service-accept', direction='out', sender_type='system', role='system',
                 body='Диалог принят', delivery_status='delivered'),
            dict(id='staff-unsent', direction='out', sender_type='operator',
                 body='Телефон и адрес подскажите?', delivery_status='pending'),
            dict(id='staff-price-pending', direction='out', sender_type='operator',
                 body='Замена смесителя — 2000 рублей за штуку. Такая стоимость Вас устраивает?',
                 delivery_status='pending'),
            dict(id='client-punctuation', direction='in', sender_type='client', body='?')])
        prepared, task = native_fixture.NativeWording209Tests.prepare(self)
        self.assertEqual(task['decision']['next_question']['kind'], 'place')
        self.assertEqual(len(task['conversation']), 5)
        scope = 'assistant:' + digest('wording209')
        _, payload = self.app.store.request(scope, prepared['request_id'])
        candidate = dict(reply=ORIGINAL_REPLY, needs_operator=False, context_review=dict(
            evidence_ids=['client-price', 'client-punctuation'],
            last_intent='Клиент хочет заменить два смесителя в ванной и узнать порядок работы сервиса; смесители куплены, материалы есть.',
            latest_client_meaning='Знак «?» завершает вопрос «Как это происходит?» о порядке работы по замене двух смесителей в ванной.',
            note='Предложенный ответ поясняет порядок обращения и уточняет неизвестный тип объекта; ванная уже названа.',
            selected_step_fits=True))
        return scope, payload, candidate

    def finalize(self, scope, payload, candidate):
        original = copy.deepcopy(candidate)
        result = self.app.finalize(scope, dict(request_id=payload['request_id'],
            revision=payload['revision'], candidate=candidate), research_proposal=proposals.build(payload))
        self.assertEqual(candidate, original)
        return result

    def test_original_free_model_reply_survives_native_finalize_without_rewriting(self):
        scope, payload, candidate = self.source()
        result = self.finalize(scope, payload, candidate)
        self.assertEqual(result['validation'], [])
        self.assertEqual(result['reply'], ORIGINAL_REPLY)
        self.assertFalse(result['needs_operator'])
        for field in ('last_intent', 'latest_client_meaning', 'note'):
            self.assertEqual(result['context_review'][field], candidate['context_review'][field])
        self.assertFalse(result['lead']['can_create_automatically'])

    def test_required_process_answer_cannot_be_dropped(self):
        scope, payload, candidate = self.source()
        candidate['reply'] = 'Здравствуйте! ' + NATURAL
        result = self.finalize(scope, payload, candidate)
        self.assertIn('proposal_required_text_missing', result['validation'])
        self.assertEqual(result['reply'], '')

    def test_wording_fix_does_not_admit_an_unrequested_building(self):
        scope, payload, candidate = self.source()
        candidate['reply'] = ORIGINAL_REPLY.replace('доме', 'гараже')
        result = self.finalize(scope, payload, candidate)
        self.assertIn('proposal_wording_unbound', result['validation'])
        self.assertEqual(result['reply'], '')

    def test_original_justified_empty_veto_remains_available(self):
        scope, payload, candidate = self.source()
        candidate.update(reply='', needs_operator=True)
        candidate['context_review'].update(selected_step_fits=False,
            note='Выбранный вопрос требует отдельной проверки уместности.')
        result = self.finalize(scope, payload, candidate)
        self.assertTrue(result['needs_operator'])
        self.assertEqual(result['reply'], '')
