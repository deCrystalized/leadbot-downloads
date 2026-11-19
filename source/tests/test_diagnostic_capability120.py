"""Keep useful diagnostic intake and source-scoped technical uncertainty."""
import copy
import json
import unittest

import test_diagnostic_reasoning119 as helpers
import assistant_policy as policy


class DiagnosticCapability120Tests(unittest.TestCase):
    setUp = helpers.DiagnosticReasoning119Tests.setUp
    prepare = helpers.DiagnosticReasoning119Tests.prepare
    candidate = helpers.DiagnosticReasoning119Tests.candidate
    finish = helpers.DiagnosticReasoning119Tests.finish

    def first(self, job='Можете провести диагностику принтера HP Deskjet 6075? Картриджей нет.', direction='kp', attachments=None):
        ctx = dict(convId='synthetic-diagnostic-capability120', city='Оренбург', dir=direction,
                   channel='avito', partner='7', accountTitle='Учебный мастер', origin='С1',
                   itemTitle='Ремонт принтеров', messages=[dict(id='job', direction='in', body=job, attachments=attachments or [])])
        out, code = self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(code,200)
        return out, json.loads(out['model_task']['task']) if out.get('model_task') else None

    def test_capability_answer_precedes_the_necessary_question(self):
        out,t = self.first()
        self.assertTrue(out.get('pending_model'))
        self.assertIn('Диагностику провести можно.',t['proposed_reply'])
        self.assertIn('без картриджей',t['proposed_reply'])
        self.assertNotIn('1000',t['proposed_reply'])
        c = dict(reply=t['decision']['next_question']['question'],needs_operator=False,
                 context_review=dict(last_intent='Узнать возможность диагностики принтера без картриджей',
                     latest_client_meaning='Хочет проверить свой принтер, сообщает отсутствие картриджей',
                     selected_step_fits=True,evidence_ids=['job'],
                     note='Ответ подтверждает приём диагностики, не обещает её результат; далее необходимый вопрос.'))
        if t.get('item_fitment_context'):
            c['context_review']['item_fitment_review'] = copy.deepcopy(
                t['item_fitment_context']['required_review'])
        final=self.finish(out,c)
        self.assertEqual(final['validation'],[])
        self.assertIn('Диагностику провести можно.',final['reply'])
        self.assertIn('без картриджей',final['reply'])
        self.assertLessEqual(len(final['reply']),280)

    def test_no_cartridge_disclaimer_when_client_did_not_report_absence(self):
        _,t=self.first('Можете провести диагностику принтера HP Deskjet 6075?')
        self.assertIn('Диагностику провести можно.',t['proposed_reply'])
        self.assertNotIn('без картриджей',t['proposed_reply'])

    def test_required_acknowledgement_cannot_be_dropped_by_a_wording_path(self):
        _,t=self.first()
        d=dict(t['decision'], action='question'); question=d['next_question']['question']
        self.assertIn('missing_required_disclosure',policy.validate_reply(question,d,{'contact_phone_to_use':''}))

    def test_later_price_question_does_not_repeat_capability_acknowledgement(self):
        _,t=self.prepare(job='Можете провести диагностику принтера HP Deskjet 6075?',latest='По стоимости сколько выйдет?')
        self.assertNotIn('Диагностику провести можно.',t['proposed_reply'])
        self.assertIn('от 500',t['fixed_reply'])

    def test_unsupported_format_and_unreviewed_media_never_gain_capability_acceptance(self):
        for job in ['Можете провести диагностику принтера формата А0?']:
            with self.subTest(job=job):
                out,t=self.first(job)
                self.assertNotIn('Диагностику провести можно.',(t or {}).get('proposed_reply',''))
        out,_=self.first('Холодильник не морозит. Можете провести диагностику?',direction='bt')
        self.assertNotIn('Диагностику провести можно.',out.get('reply',''))
        _,t=self.first(attachments=[dict(kind='image',url='https://example.invalid/printer.jpg')])
        self.assertNotIn('Диагностику провести можно.',(t or {}).get('proposed_reply',''))

    def test_no_invented_age_ban_for_an_ordinary_printer(self):
        _,t=self.first('Можете провести диагностику принтера HP Deskjet 6075? Ему 20 лет.')
        self.assertIn('Диагностику провести можно.',t['proposed_reply'])

    def test_actual119_conditional_and_worried_source_review_is_usable(self):
        out,t=self.prepare();c=self.candidate(t)
        c['context_review'].update(
            last_intent='Уточнить стоимость диагностики принтера HP deskjet plus ink advantage 6075, если он нерабочий',
            latest_client_meaning='Клиент беспокоится, что принтер нерабочий, поскольку другие мастера отказались его диагностировать, поэтому уточняет стоимость диагностики в случае неисправности устройства',
            note='Предложенный ответ корректно отражает регламентированную стоимость диагностики и соответствует запросу клиента')
        final=self.finish(out,c)
        self.assertEqual(final['validation'],[])
        self.assertTrue(final['reply'])

    def test_condition_on_the_device_is_allowed(self):
        out,t=self.prepare();c=self.candidate(t)
        c['context_review']['last_intent']='Узнать стоимость диагностики, если принтер нерабочий'
        final=self.finish(out,c)
        self.assertEqual(final['validation'],[])

    def test_cost_uncertainty_does_not_qualify_an_asserted_device_fault(self):
        out,t=self.prepare();c=self.candidate(t)
        c['context_review']['latest_client_meaning']='Клиент беспокоится о возможной напрасной трате денег на диагностику неисправного принтера'
        final=self.finish(out,c)
        self.assertIn('unverified_third_party_device_condition',final['validation'])
        self.assertFalse(final['reply'])

    def test_condition_only_on_price_does_not_qualify_asserted_device_fault(self):
        out,t=self.prepare();c=self.candidate(t)
        c['context_review']['latest_client_meaning']='Если цена приемлема, клиент хочет диагностику неисправного принтера'
        final=self.finish(out,c)
        self.assertIn('unverified_third_party_device_condition',final['validation'])


if __name__=='__main__':
    unittest.main()
