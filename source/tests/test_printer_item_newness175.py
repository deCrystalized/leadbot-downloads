"""An adjective about a cartridge cannot establish the age of its printer."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import contact_facts as facts
from assistant_store import Store
from extension_assistant import Assistant


def client(mid, body):
    return dict(id=mid, direction='in', sender_type='client', body=body)


def staff(mid, body):
    return dict(id=mid, direction='out', sender_type='operator', body=body,
                delivery_status='delivered')


REPORT = 'Принтер плохо печатает цветом, картридж новый.'


class PrinterAttributeEvidenceTests(unittest.TestCase):
    def evidence(self, body):
        return facts.printer_item_newness([client('source', body)])

    def test_new_cartridge_does_not_establish_new_printer(self):
        context = self.evidence(REPORT)
        self.assertEqual(context['states']['printer'], 'not_stated')
        self.assertEqual(context['states']['cartridge'], 'new')
        row = context['evidence'][0]
        self.assertEqual(row['literal'], 'картридж новый')
        self.assertEqual(row['message_id'], 'source')
        self.assertEqual(row['quote'], REPORT)

    def test_adjective_order_and_case_keep_the_same_object(self):
        for body in ['У принтера новый цветной картридж.', 'Картриджи совсем новые.',
                     'С новым картриджем принтер плохо печатает.', 'Картридж — новый.']:
            with self.subTest(body=body):
                context = self.evidence(body)
                self.assertEqual(context['states']['cartridge'], 'new')
                self.assertEqual(context['states']['printer'], 'not_stated')

    def test_explicit_new_printer_and_two_explicit_attributes_remain_valid(self):
        self.assertEqual(self.evidence('Новый принтер плохо печатает.')['states']['printer'], 'new')
        context = self.evidence('Принтер новый, а картридж старый.')
        self.assertEqual(context['states'], dict(printer='new', cartridge='old'))
        self.assertEqual(self.evidence('Принтер новый, картриджи тоже новые.')['states'],
                         dict(printer='new', cartridge='new'))

    def test_new_component_of_a_new_device_records_both_only_when_explicit(self):
        context = self.evidence('Новый картридж нового принтера плохо печатает.')
        self.assertEqual(context['states'], dict(printer='new', cartridge='new'))

    def test_genitive_device_attribute_does_not_describe_its_component(self):
        context = self.evidence('Картридж нового принтера плохо печатает.')
        self.assertEqual(context['states'], dict(printer='new', cartridge='not_stated'))

    def test_negation_is_not_positive_newness_or_an_old_age_inference(self):
        context = self.evidence('Картридж не новый, принтер не старый.')
        self.assertEqual(context['states'], dict(printer='not_old', cartridge='not_new'))

    def test_question_uncertainty_hypothesis_and_third_party_are_not_client_facts(self):
        for text in ['Если принтер новый, почему печать плохая?',
                     'Принтер новый?', 'Возможно, принтер новый.',
                     'Принтер вроде новый.', 'Продавец сказал, принтер новый.',
                     'Мастер написал: «Новый принтер».', 'Хочу купить новый принтер.']:
            with self.subTest(text=text):
                context = self.evidence(text + ' Картридж новый.')
                self.assertEqual(context['states']['printer'], 'not_stated')
                self.assertEqual(context['states']['cartridge'], 'new')

    def test_staff_system_or_quoted_text_cannot_supply_positive_newness(self):
        data = [staff('staff', 'Принтер новый.'),
                dict(id='system', direction='in', sender_type='avito', body='Принтер новый.'),
                client('quote', 'В инструкции: «Новый принтер». Картридж новый.')]
        context = facts.printer_item_newness(data)
        self.assertEqual(context['states']['printer'], 'not_stated')
        self.assertEqual(context['states']['cartridge'], 'new')

    def test_previous_replacement_does_not_prove_newness(self):
        self.assertIsNone(self.evidence('В принтере вчера поменяли картридж.'))

    def test_quoted_adjective_alone_is_not_a_positive_age_fact(self):
        context = self.evidence('Принтер «новый», картридж новый.')
        self.assertEqual(context['states']['printer'], 'not_stated')
        self.assertEqual(context['states']['cartridge'], 'new')

    def test_device_label_adjective_is_not_an_adjective_of_the_device(self):
        self.assertIsNone(self.evidence('Новая принтерная головка установлена.'))

    def test_new_enquiry_or_another_printer_resets_old_attributes(self):
        for boundary in ['Новая заявка: принтер плохо печатает.', 'Другой принтер плохо печатает.']:
            with self.subTest(boundary=boundary):
                context = facts.printer_item_newness([client('old', 'Принтер новый.'),
                    client('boundary', boundary), client('new', 'Картридж новый.')])
                self.assertEqual(context['states']['printer'], 'not_stated')
                self.assertEqual(context['states']['cartridge'], 'new')


class PrinterAttributeNativeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner', LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))
        self.serial = 0

    def preview(self, text=REPORT, **extra):
        self.serial += 1
        context = dict(convId='synthetic-newness175-' + str(self.serial),
            city='Коломна', dir='kp', channel='avito', partner='7',
            itemTitle='Ремонт принтеров', accountTitle='Учебный мастер',
            messages=[client('source', text)], **extra)
        value, code = self.app.handle(dict(owner='owner', action='preview', wording_mode='neural_review', ctx=context))
        self.assertEqual(code, 200)
        self.assertTrue(value.get('pending_model'))
        self.assertFalse(value['auto_enabled'])
        self.assertFalse(value['lead']['can_create_automatically'])
        task = json.loads(value['model_task']['task'])
        return value, task

    def candidate(self, task):
        candidate = dict(reply=task['decision']['next_question']['question'], needs_operator=False,
            context_review=dict(last_intent='Помощь с плохой цветной печатью принтера',
                latest_client_meaning='Клиент описал плохую печать, картридж по его словам новый.',
                selected_step_fits=True, evidence_ids=['source'], note='Уточняем известную проблему без диагноза.'))
        if task.get('item_attribute_context', {}).get('required_review'):
            candidate['context_review']['item_attribute_review'] = copy.deepcopy(
                task['item_attribute_context']['required_review'])
        if task.get('item_fitment_context', {}).get('required_review'):
            candidate['context_review']['item_fitment_review'] = copy.deepcopy(
                task['item_fitment_context']['required_review'])
        if task.get('item_source_quote_contract'):
            mid = task['item_source_quote_contract']['latest_relevant_evidence_id']
            source = next(row for row in task['conversation'] if mid in (row['id'],row.get('review_ref')))
            candidate['context_review']['item_source_quotes'] = [dict(evidence_id=mid,quote=source['body'])]
        return candidate

    def finalize(self, value, candidate):
        original = copy.deepcopy(candidate)
        final, code = self.app.handle(dict(owner='owner', action='finalize',
            request_id=value['request_id'], revision=value['revision'], candidate=candidate))
        self.assertEqual(code, 200)
        self.assertEqual(candidate, original)
        return final

    def test_original_native_error_is_rejected_even_when_customer_question_is_suitable(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review']['last_intent'] = 'Узнать причину плохой печати цветным картриджем нового принтера'
        candidate['context_review']['latest_client_meaning'] = 'Клиент сообщает о проблеме с печатью нового принтера'
        final = self.finalize(value, candidate)
        self.assertFalse(final['reply'])
        self.assertIn('item_attribute_object_transfer', final['validation'])

    def test_every_semantic_field_and_reply_are_checked(self):
        for field in ['last_intent', 'latest_client_meaning', 'note', 'reply']:
            with self.subTest(field=field):
                value, task = self.preview()
                candidate = self.candidate(task)
                if field == 'reply':
                    candidate['reply'] = 'У нового принтера проблема с печатью. ' + candidate['reply']
                else:
                    candidate['context_review'][field] = 'Клиент просит помочь с новым принтером.'
                final = self.finalize(value, candidate)
                self.assertIn('item_attribute_object_transfer', final['validation'])

    def test_correct_cartridge_scope_passes_and_is_not_a_new_crm_fact(self):
        value, task = self.preview()
        context = task['item_attribute_context']
        self.assertEqual(context['states']['printer'], 'not_stated')
        self.assertEqual(context['evidence'][0]['evidence_id'], 'source')
        self.assertEqual(context['source'], 'server_literal_item_attribute_binding')
        self.assertFalse(context['independent_model_interpretation'])
        final = self.finalize(value, self.candidate(task))
        self.assertEqual(final['validation'], [])
        self.assertTrue(final['reply'])
        self.assertNotIn('printer_age', final['facts'])

    def test_explicit_new_printer_is_allowed_and_does_not_make_cartridge_new(self):
        value, task = self.preview('Новый принтер плохо печатает цветом.')
        candidate = self.candidate(task)
        candidate['context_review']['last_intent'] = 'Проблема с печатью нового принтера'
        candidate['context_review']['latest_client_meaning'] = 'Клиент сообщает, что новый принтер плохо печатает.'
        self.assertEqual(self.finalize(value, candidate)['validation'], [])
        value, task = self.preview('Новый принтер плохо печатает цветом.')
        candidate = self.candidate(task)
        self.assertIn('item_attribute_object_transfer', self.finalize(value, candidate)['validation'])

    def test_both_explicit_new_items_pass(self):
        value, task = self.preview('Принтер новый, картридж тоже новый, печатает плохо.')
        candidate = self.candidate(task)
        candidate['context_review']['last_intent'] = 'Плохая печать нового принтера с новым картриджем'
        self.assertEqual(self.finalize(value, candidate)['validation'], [])

    def test_uncertain_or_quoted_source_does_not_authorize_definite_device_newness(self):
        for text in ['Принтер вроде новый, картридж новый, печатает плохо.',
                     'Продавец написал: «Принтер новый». Картридж новый, принтер печатает плохо.']:
            with self.subTest(text=text):
                value, task = self.preview(text)
                candidate = self.candidate(task)
                candidate['context_review']['last_intent'] = 'Плохая печать нового принтера'
                self.assertIn('item_attribute_object_transfer', self.finalize(value, candidate)['validation'])

    def test_fictional_quote_does_not_hide_an_invented_device_attribute(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review']['latest_client_meaning'] = 'Клиент описывает «новый принтер».'
        self.assertIn('item_attribute_object_transfer', self.finalize(value, candidate)['validation'])

    def test_unknown_age_disclaimer_is_not_a_positive_age_claim(self):
        value, task = self.preview()
        candidate = self.candidate(task)
        candidate['context_review']['note'] = 'Клиент не говорил, что принтер новый; возраст принтера неизвестен.'
        self.assertEqual(self.finalize(value, candidate)['validation'], [])

    def test_raw_context_cannot_inject_a_new_device_fact(self):
        value, task = self.preview(item_attribute_context=dict(states=dict(printer='new')))
        self.assertEqual(task['item_attribute_context']['states']['printer'], 'not_stated')
        candidate = self.candidate(task)
        candidate['context_review']['last_intent'] = 'Новый принтер плохо печатает.'
        self.assertIn('item_attribute_object_transfer', self.finalize(value, candidate)['validation'])


if __name__ == '__main__':
    unittest.main()
