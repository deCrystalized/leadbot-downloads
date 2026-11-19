"""Full source boundaries: stated symptoms, access documents and terminal replies."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_policy as policy
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant


def client(mid, body):
    return dict(id=mid, direction='in', sender_type='client', body=body)


def staff(mid, body, **extra):
    return dict(id=mid, direction='out', sender_type='operator', body=body, delivery_status='delivered', **extra)


class PrinterBusiness167Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_PERSONAL_OWNER_ID='owner167', LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(tmp.name + '/db'))
        self.serial = 0

    def preview(self, messages, **extra):
        self.serial += 1
        ctx = dict(convId='synthetic-printer167-' + str(self.serial), city='Сочи', dir='kp', channel='avito', partner='7',
                   accountTitle='Учебный КП', origin='В89', itemTitle='Ремонт принтеров', messages=messages)
        ctx.update(extra)
        out, status = self.app.handle(dict(owner='owner167', action='preview', wording_mode='neural_review', ctx=ctx))
        self.assertEqual(status, 200)
        self.assertFalse(out['auto_enabled'])
        self.assertFalse(out['lead']['can_create_automatically'])
        return out

    def base(self):
        return [client('job', 'Ремонтируете принтер Kyocera 5003i?'), staff('question', 'Какая у вас проблема?')]

    def test_separate_print_quality_answer_is_not_a_missing_problem_or_component_diagnosis(self):
        messages = self.base() + [client('quality', 'бледная печать второй половины листа. При печати документов невозможно прочитать текст снизу листа. Ресурс тонера 60 %.')]
        state = qs.inspect(messages)
        self.assertEqual(state['problem']['status'], 'answered')
        self.assertEqual(state['problem']['message_id'], 'quality')
        self.assertEqual(state['problem']['value'], 'бледная печать')
        self.assertEqual(state['problem']['evidence_source'], 'client_message')
        after_unknown = self.base() + [client('unknown', 'Не знаю'), messages[-1]]
        self.assertEqual(qs.inspect(after_unknown)['problem']['message_id'], 'quality')
        self.assertEqual(qs.inspect(after_unknown)['problem']['status'], 'answered')
        out = self.preview(messages)
        task = json.loads(out['model_task']['task']) if out.get('model_task') else {}
        self.assertNotEqual((task.get('decision', {}).get('next_question') or {}).get('kind'), 'problem')
        self.assertNotRegex(out.get('reply', '') + task.get('proposed_reply', ''), r'тонер пуст|заменить барабан|картридж закончился')

    def test_a_percentage_quote_hypothetical_staff_speech_or_other_subject_is_not_a_client_symptom(self):
        for message in (client('x', 'Ресурс тонера 60 %'), client('x', '«Бледная печать» написано в инструкции'),
                        client('x', 'Если будет бледная печать, сколько стоит ремонт?'),
                        staff('x', 'У вас бледная печать'), client('x', 'Бледной печати нет')):
            self.assertIsNone(qs.printer_quality_evidence(self.base() + [message]))
        self.assertIsNone(qs.printer_quality_evidence([client('other', 'На майке бледная печать')]))
        self.assertIsNone(qs.printer_quality_evidence(self.base() + [client('new', 'Теперь нужен ремонт телевизора, бледная печать на майке')]))

    def test_active_invoice_stays_a_branch_handoff_without_false_company_refusal(self):
        out = self.preview(self.base() + [client('invoice', 'Мы компания, оплата по счёту юридическому лицу')])
        self.assertEqual(out['action'], 'handoff')
        self.assertIn('DOC-L0801', out['rule_ids'])
        self.assertFalse(out.get('pending_model'))
        self.assertFalse(out['reply'])

    def test_ack_after_delivered_generic_refusal_ends_even_with_an_earlier_invoice(self):
        messages = self.base() + [client('invoice', 'Оплата по счёту, перевод в течение месяца'),
                                 staff('refusal', 'Не смогу вам тогда помочь, извините'), client('ack', 'Хорошо, поняла')]
        for extra in ({}, dict(conversationStatus='closed')):
            out = self.preview(messages, **extra)
            self.assertEqual(out['action'], 'wait')
            self.assertFalse(out.get('pending_model'))
            self.assertFalse(out['reply'])
            self.assertFalse(out['staff_refusal_closure']['admission_rule'])
            self.assertFalse(out['staff_refusal_closure']['crm_closure_confirmed'])

    def test_companies_intermediaries_and_extended_ack_do_not_become_an_admission_ban(self):
        messages = self.base() + [client('invoice', 'Мы компания, по счёту'),
                                 staff('refusal', 'Здравствуйте, я не работаю с посредниками и компаниями'),
                                 client('ack', 'Хорошо, поняла Вас, спасибо за информацию')]
        out = self.preview(messages)
        self.assertEqual(out['action'], 'wait')
        self.assertEqual(out['staff_refusal_closure']['client_message_id'], 'ack')
        self.assertFalse(out['staff_refusal_closure']['admission_rule'])

    def test_new_question_after_refusal_and_failed_delivery_cannot_end_an_active_case(self):
        for ack in ('Хорошо, а если наличными?', 'Хорошо. А почему вы отказались?', 'Спасибо, когда приедете?'):
            out = self.preview(self.base() + [client('invoice', 'Мы компания, по счёту'),
                                            staff('refusal', 'Не смогу вам помочь'), client('ack', ack)])
            self.assertNotEqual(out['action'], 'wait')
        messages = self.base() + [client('invoice', 'Мы компания, по счёту'), staff('refusal', 'Не смогу вам помочь'), client('ack', 'Хорошо, поняла')]
        messages[-2]['delivery_status'] = 'failed'
        self.assertNotEqual(self.preview(messages)['action'], 'wait')

    def test_existing_crm_reference_and_accepted_visit_outrank_refusal_ack(self):
        messages = self.base() + [client('invoice', 'Мы компания, по счёту'),
                                 staff('refusal', 'Не смогу вам помочь'), client('ack', 'Хорошо, поняла')]
        self.assertEqual(self.preview(messages, crmRequestId='synthetic-order167')['action'], 'handoff')
        booked = self.base() + [staff('time', 'Через час-полтора удобно вам будет?'), client('yes', 'Да'),
                                staff('refusal', 'Не смогу вам помочь'), client('ack', 'Хорошо, поняла')]
        out = self.preview(booked)
        self.assertIsNone(out.get('staff_refusal_closure'))

    def test_personal_passport_request_for_access_goes_to_operator_without_disclosure_or_a_fake_regulation(self):
        messages = self.base() + [client('access', 'Нужно ехать в банк, необходим допуск. Для допуска необходимы паспортные данные. Мы если что компания, работаем с клиентами.')]
        out = self.preview(messages)
        self.assertEqual(out['action'], 'handoff')
        self.assertFalse(out.get('pending_model'))
        self.assertFalse(out['reply'])
        self.assertIn('VERIFY_PERSONAL_ACCESS_DOCUMENTS', [guard['id'] for guard in out['decision_guards']])
        self.assertNotRegex(out['reason'], 'компании не принимаем|отказ|данные отправлены|пропуск оформлен')

    def test_product_passport_negation_withdrawal_and_staff_only_access_are_not_personal_requests(self):
        for body in ('Для допуска паспортные данные не нужны', 'Для монтажа нужен паспорт изделия',
                     'Если для допуска понадобятся паспортные данные, что делать?', '«Для допуска нужны паспортные данные» — цитата'):
            self.assertIsNone(policy._personal_access_document_request([client('x', body)]))
        self.assertIsNone(policy._personal_access_document_request([staff('x', 'Для допуска нужны паспортные данные')]))
        self.assertIsNone(policy._personal_access_document_request([client('x', 'Для допуска нужны паспортные данные'),
                                                                   client('y', 'Паспортные данные больше не требуются')]))


if __name__ == '__main__':
    unittest.main()
