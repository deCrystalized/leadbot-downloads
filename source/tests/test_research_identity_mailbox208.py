import unittest
from research_identity import ObserverProofs


class Mailbox208Tests(unittest.TestCase):
    def setUp(self):
        self.now=100
        self.bank=ObserverProofs(lambda:self.now,limit=2)
        self.body=dict(owner='o',request_id='r',revision='v',browser_session='sid',operator_id='actor',identity_proof='local-test-proof')

    def remember(self,**patch):
        self.bank.remember(dict(self.body,**patch),'binding',dict(iat=100,exp=145))

    def test_only_exact_owner_request_revision_session_actor_can_retrieve_proof(self):
        self.remember()
        for key in ('owner','request_id','revision','browser_session','operator_id'):
            changed=dict(self.body,**{key:'other'})
            self.assertEqual(self.bank.body(changed),(changed,None))

    def test_original_body_is_not_mutated_and_expiry_is_not_extended(self):
        self.remember(identity_proof='renewed')
        value,binding=self.bank.body(self.body)
        self.assertEqual(value['identity_proof'],'renewed');self.assertEqual(binding,'binding')
        self.assertEqual(self.body['identity_proof'],'local-test-proof')
        self.now=145;self.assertEqual(self.bank.body(self.body),(self.body,None))
        self.assertFalse(self.bank._entries)

    def test_bounded_capacity_and_explicit_discard(self):
        for rid in ('r','r2','r3'):self.remember(request_id=rid)
        self.assertEqual(len(self.bank._entries),2)
        self.bank.discard('o','r2');self.assertEqual(len(self.bank._entries),1)

    def test_native_three_second_clock_skew_does_not_extend_signed_lifetime(self):
        self.bank.remember(self.body,'binding',dict(iat=103,exp=148))
        self.assertEqual(self.bank.body(self.body)[1],'binding')
        self.now=148;self.assertIsNone(self.bank.body(self.body)[1])

    def test_invalid_or_extended_or_boolean_expiry_is_not_cached(self):
        for identity in (dict(iat=100,exp=146),dict(iat=104,exp=145),dict(iat=True,exp=145),dict(iat=100,exp=True)):
            self.bank.remember(self.body,'binding',identity)
            self.assertIsNone(self.bank.body(self.body)[1])


if __name__=='__main__':unittest.main()
