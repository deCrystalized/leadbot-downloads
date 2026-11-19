"""Cancelled source text is visible history, not a current fact or order."""
import unittest
import research_form
from research_pipeline import pack_context,ResearchError
import test_research_form233 as forms


class CancelledEvidence252Tests(unittest.TestCase):
    def context(self,status):
        return dict(owner_id='owner',dialogue_id='synthetic',revision='r1',policy_version='p1',
            memory_version='m1',map_version='map1',messages=[dict(id='source',direction='in',
                sender_type='client',speaker_role='client',body='Нужно повесить полку.',delivery_status=status)],
            facts=[dict(status='reported',evidence_ids=['source'],text='Повесить полку')])

    def test_cancelled_message_cannot_support_a_current_client_fact(self):
        with self.assertRaises(ResearchError):pack_context('research',self.context('cancelled'))

    def test_canceled_message_cannot_support_a_current_client_fact(self):
        with self.assertRaises(ResearchError):pack_context('research',self.context('canceled'))

    def test_canceled_message_cannot_support_a_requested_CRM_work(self):
        f=forms.FormSchema233Tests();f.setUp();f.row['delivery_status']='canceled'
        with self.assertRaises(ValueError):research_form.check(f.value,f.current)

    def test_delivery_exclusion_keeps_history_without_current_evidence_authority(self):
        ctx=self.context('cancelled');ctx['facts']=[]
        packed=pack_context('research',ctx)
        self.assertEqual(packed['input']['current']['messages'],ctx['messages'])
        self.assertNotIn('current:source',packed['input']['source_references'])
