"""Source/summary transport boundaries; fake model, never semantic API credit."""
import copy
import json
import unittest
import research_form as form
import test_research_pipeline218 as fixtures


class FormConditions251Tests(unittest.TestCase):
    def current(self, text, extra=()):
        current=fixtures.context();current['facts']=[];current['open_questions']=[]
        current['messages']=[dict(id='work',speaker_role='client',body=text,delivery_status='delivered'),*extra]
        current['candidate_contract']=dict(system='Суть работ',task={'purpose':form.PURPOSE},schema=form.schema('research'))
        return current

    def value(self, text, summary, unknowns=()):
        return dict(kind='intake_form',client_goal='Заменить смесители.',latest_client_meaning='Сообщил условия работы.',
            note='Запрошено, ещё не выполнено.',summary=summary,unknowns=list(unknowns),needs_operator=False,
            works=[dict(subject='Смесители',action='Заменить',quantity='',status='requested',
                evidence=[dict(message_id='work',quote=text)])])

    def run_form(self,current,value,violations=()):
        packets=[];audits=[];original=copy.deepcopy(value)
        def transport(role,packet,tools):
            packets.append(copy.deepcopy(packet))
            return copy.deepcopy(value if role=='research'else dict(kind='review',approved=not violations,
                violations=list(violations),checked_claims=[0,1],basis=['current:work']))
        out=form.run(current,transport,audit=lambda *v:audits.append(v))
        self.assertEqual(value,original);self.assertEqual(len(packets),2)
        for packet in packets:self.assertEqual(packet['input']['current']['messages'],current['messages'])
        self.assertEqual(packets[1]['input']['research']['intake_form'],original)
        self.assertEqual(out['form'],original);self.assertFalse(out['can_send_or_create'])
        self.assertEqual([a[0]for a in audits],['form_model_description','form_separate_review'])
        return out

    def test_literal_supplied_materials_survive_both_stages_without_new_work(self):
        text='Заменить 2 смесителя. Оба куплены, материалы есть.'
        out=self.run_form(self.current(text),self.value(text,text))
        self.assertTrue(out['approved']);self.assertEqual(len(out['form']['works']),1)

    def test_partial_supplies_remain_partial_and_missing_fasteners_unknown(self):
        text='Заменить смесители. Куплен только один, про крепления не знаю.'
        out=self.run_form(self.current(text),self.value(text,text,['Крепления неизвестны']))
        self.assertTrue(out['approved']);self.assertEqual(out['form']['unknowns'],['Крепления неизвестны'])

    def test_conditional_shortage_question_does_not_require_invented_stock(self):
        text='Заменить смесители. Если деталей не хватит, сможете купить?'
        out=self.run_form(self.current(text),self.value(text,'Заменить смесители. Клиент спрашивает о покупке при возможной нехватке деталей.',['Фактическая комплектность неизвестна']))
        self.assertTrue(out['approved'])

    def test_other_past_and_system_statements_remain_labelled_in_both_stages(self):
        text='Заменить смесители. Материалы пока не проверял.'
        rows=[dict(id='system',speaker_role='system',body='Материалы есть.',delivery_status='delivered'),
              dict(id='past',speaker_role='client',body='Вчера сосед купил смеситель себе.',delivery_status='delivered')]
        out=self.run_form(self.current(text,rows),self.value(text,text,['Комплектность неизвестна']))
        self.assertTrue(out['approved'])

    def test_late_correction_is_not_lost_from_source_or_reviewer_input(self):
        text='Заменить смесители, оба куплены.'
        row=dict(id='correction',speaker_role='client',body='Уточнение: один вернул в магазин, куплен только второй.',delivery_status='delivered')
        out=self.run_form(self.current(text,[row]),self.value(text,'Заменить смесители; по последнему уточнению куплен только один.'))
        self.assertTrue(out['approved'])

    def test_omission_review_veto_is_retained_without_repair(self):
        text='Заменить смесители. Оба куплены, материалы есть.'
        out=self.run_form(self.current(text),self.value(text,'Заменить смесители.'),['Потеряно наличие материалов.'])
        self.assertFalse(out['approved']);self.assertEqual(out['failure_kind'],'semantic')
        self.assertEqual(out['form']['summary'],'Заменить смесители.')

    def test_unsupported_supply_review_veto_is_not_overridden(self):
        text='Заменить смесители. Если не хватит, привезёте?'
        out=self.run_form(self.current(text),self.value(text,'Заменить смесители; мастер привезёт все детали.'),['Необоснованное обещание запаса и доставки.'])
        self.assertFalse(out['approved'])

    def test_richer_conditions_do_not_grant_model_contact_price_or_action_fields(self):
        text='Заменить смесители, оба куплены.';current=self.current(text);value=self.value(text,text)
        for summary in ('Заменить смесители за 800 рублей.','Заявка создана.','Заменить смесители, приезд в 14:00.'):
            bad=copy.deepcopy(value);bad['summary']=summary
            with self.subTest(summary=summary),self.assertRaises(ValueError):form.check(bad,current)


if __name__=='__main__':unittest.main()
