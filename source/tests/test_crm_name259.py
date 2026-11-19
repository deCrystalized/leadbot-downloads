"""The accepted form's literal name and the CRM gate use the same evidence."""
import unittest

import personal_workflow
from extension_assistant import _parse
from test_assistant import message
import test_workflow as fixture


class CRMName259Tests(unittest.TestCase):
    def check(self, profile, name='Иван', extra=(), remove_literal=False):
        ctx=fixture.WorkflowTests().ctx(True,clientName=profile)
        if remove_literal:
            ctx['messages'][0]['body']=ctx['messages'][0]['body'].replace('Меня зовут Иван.','')
        ctx['messages'].extend(extra)
        _,rows,known,revision=_parse(ctx)
        proposal=fixture.WorkflowTests().proposal(ctx);proposal['lead']['name']=name
        return personal_workflow.check_crm(rows,known,dict(ctx,workflowRevision=revision),proposal)

    def test_literal_name_precedes_different_profile(self):
        self.assertTrue(self.check('Пётр')['ready'])

    def test_matching_profile_and_literal_remain_accepted(self):
        self.assertTrue(self.check('Иван')['ready'])

    def test_profile_cannot_authorize_name_contradicted_by_client(self):
        out=self.check('Пётр',name='Пётр')
        self.assertIn('Имя заявки отличается от подтверждённого имени клиента',out['reasons'])

    def test_delivered_staff_name_does_not_replace_current_client_name(self):
        out=self.check('Пётр',extra=[message('Меня зовут Пётр.','out',mid='staff-name')])
        self.assertNotIn('Имя заявки отличается от подтверждённого имени клиента',out['reasons'])
        self.assertIn('Ожидаем ответа клиента',out['reasons'])

    def test_latest_literal_client_correction_is_used(self):
        self.assertTrue(self.check('Иван',name='Пётр',extra=[message('Меня зовут Пётр.',mid='name-correction')])['ready'])

    def test_profile_fallback_without_literal_is_preserved(self):
        out=self.check('Иван',remove_literal=True)
        self.assertNotIn('Имя заявки отличается от подтверждённого имени клиента',out['reasons'])

    def test_quoted_staff_introduction_does_not_replace_literal_client_name(self):
        self.assertTrue(self.check('Пётр',extra=[message('Вы написали: «Меня зовут Пётр». Я по-прежнему Иван.',mid='quote')])['ready'])

    def test_quoted_name_cannot_be_approved_even_when_profile_matches_it(self):
        out=self.check('Пётр',name='Пётр',extra=[message('Цитирую мастера: "Меня зовут Пётр".',mid='quote')])
        self.assertIn('Имя заявки отличается от подтверждённого имени клиента',out['reasons'])

    def test_conditional_name_is_not_a_client_identity(self):
        out=self.check('Пётр',name='Пётр',extra=[message('Если меня зовут Пётр, то что?',mid='conditional')])
        self.assertIn('Имя заявки отличается от подтверждённого имени клиента',out['reasons'])

    def test_negated_name_is_not_a_client_identity(self):
        out=self.check('Пётр',name='Пётр',extra=[message('Меня зовут не Пётр.',mid='negation')])
        self.assertIn('Имя заявки отличается от подтверждённого имени клиента',out['reasons'])

    def test_system_role_with_incoming_direction_is_not_client_name(self):
        row=message('Меня зовут Пётр.',mid='system');row['role']='system'
        self.assertTrue(self.check('Пётр',extra=[row])['ready'])

    def test_form_uses_unquoted_introduction_instead_of_earlier_quote_in_same_message(self):
        import assistant_policy, contact_facts, research_form
        ctx=fixture.WorkflowTests().ctx(True,clientName='Пётр')
        ctx['messages'].append(message('Цитата: «Меня зовут Пётр». Меня зовут Сергей.',mid='name-source'))
        _,rows,known,_=_parse(ctx);facts=contact_facts.collect(rows,known)
        decision=assistant_policy.assess(rows,known,facts)
        lead=research_form._base_lead(dict(messages=rows,known=known,facts=facts,
            crm_flags=decision['crm_flags'],geography=decision['geography']))
        self.assertEqual(lead['name'],'Сергей')

    def test_multiline_name_keeps_its_original_match_offsets(self):
        self.assertTrue(self.check('Пётр',name='Сергей',extra=[
            message('Цитата: «Меня зовут Пётр».\nМеня зовут Сергей.',mid='multiline-name')])['ready'])


if __name__=='__main__':unittest.main()
