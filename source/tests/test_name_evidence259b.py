"""Additional causal source-name boundaries, frozen before their refinement."""
import unittest

import assistant_policy
import contact_facts
import personal_workflow
import research_form
import qualification_state
from extension_assistant import _parse
from test_assistant import message
import test_crm_name259 as previous
import test_workflow as fixture


class NameEvidence259BTests(unittest.TestCase):
    def test_name_prefix_is_not_the_same_person_name(self):
        ctx=fixture.WorkflowTests().ctx(True,clientName='Иван')
        ctx['messages'][0]['body']=ctx['messages'][0]['body'].replace('Меня зовут Иван.','Меня зовут Иванна.')
        _,rows,known,revision=_parse(ctx);proposal=fixture.WorkflowTests().proposal(ctx)
        out=personal_workflow.check_crm(rows,known,dict(ctx,workflowRevision=revision),proposal)
        self.assertFalse(out['ready'])
        self.assertIn('Имя заявки отличается от подтверждённого имени клиента',out['reasons'])

    def test_denial_invalidates_previous_literal_and_same_profile(self):
        out=previous.CRMName259Tests().check('Иван',extra=[message('Меня зовут не Иван.',mid='deny-current')])
        self.assertFalse(out['ready'])
        self.assertIn('Имя заявки отличается от подтверждённого имени клиента',out['reasons'])

    def test_denial_asks_for_current_name_instead_of_sending_ready_form(self):
        ctx=fixture.WorkflowTests().ctx(True,clientName='Иван')
        ctx['messages'].append(message('Меня зовут не Иван.',mid='deny-current'))
        _,rows,known,_=_parse(ctx);facts=contact_facts.collect(rows,known)
        decision=assistant_policy.assess(rows,known,facts)
        self.assertEqual((decision.get('next_question')or{}).get('kind'),'client_name')

    def test_denial_does_not_silently_reactivate_other_old_profile_name(self):
        out=previous.CRMName259Tests().check('Пётр',name='Пётр',extra=[message('Меня зовут не Иван.',mid='deny-current')])
        self.assertFalse(out['ready'])

    def test_denial_of_another_name_keeps_current_literal(self):
        self.assertTrue(previous.CRMName259Tests().check('Пётр',extra=[
            message('Меня зовут не Пётр.',mid='deny-other')])['ready'])

    def test_quoted_denial_does_not_revoke_current_name(self):
        self.assertTrue(previous.CRMName259Tests().check('Пётр',extra=[
            message('Цитата: «Меня зовут не Иван».',mid='quote-denial')])['ready'])

    def test_conditional_denial_does_not_revoke_current_name(self):
        self.assertTrue(previous.CRMName259Tests().check('Пётр',extra=[
            message('Если меня зовут не Иван, что тогда?',mid='conditional-denial')])['ready'])

    def test_new_literal_after_denial_becomes_current(self):
        self.assertTrue(previous.CRMName259Tests().check('Иван',name='Пётр',extra=[
            message('Меня зовут не Иван. Меня зовут Пётр.',mid='corrected-name')])['ready'])

    def test_denial_after_positive_in_same_message_does_not_restore_invalid_name(self):
        self.assertFalse(previous.CRMName259Tests().check('Иван',extra=[
            message('Меня зовут Иван. Меня зовут не Иван.',mid='same-message-denial')])['ready'])

    def test_last_literal_introduction_in_same_message_is_current(self):
        self.assertTrue(previous.CRMName259Tests().check('Иван',name='Пётр',extra=[
            message('Меня зовут Иван. Меня зовут Пётр.',mid='same-message-correction')])['ready'])

    def test_current_positive_fact_does_not_keep_old_revocation_flags(self):
        fact=qualification_state.inspect([
            message('Меня зовут Иван.',mid='first-name'),
            message('Меня зовут не Иван.',mid='denied-name'),
            message('Меня зовут Пётр.',mid='current-name')])['client_name']
        self.assertEqual(fact['status'],'answered')
        self.assertNotIn('invalidated_name',fact)
        self.assertNotIn('denied_name',fact)

    def test_valid_self_introduction_yields_only_name_in_form(self):
        ctx=fixture.WorkflowTests().ctx(True,clientName='Пётр')
        ctx['messages'][0]['body']=ctx['messages'][0]['body'].replace('Меня зовут Иван.','')
        ctx['messages'].append(message('Это я Иван.',mid='self-introduction'))
        _,rows,known,_=_parse(ctx);facts=contact_facts.collect(rows,known)
        decision=assistant_policy.assess(rows,known,facts)
        lead=research_form._base_lead(dict(messages=rows,known=known,facts=facts,
            crm_flags=decision['crm_flags'],geography=decision['geography']))
        self.assertEqual(lead['name'],'Иван')


if __name__=='__main__':unittest.main()
