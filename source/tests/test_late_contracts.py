import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import assistant_policy as policy
import assistant_prices as prices
import contact_facts
from extension_assistant import _parse
class LateContracts(unittest.TestCase):
 def test_verified_card_address(self):
  _,messages,known,_=_parse({'convId':'a','messages':[{'id':'a','direction':'in','body':'Да'}], 'cardAddress':{'street':'Тестовая','building':'4','office':'ЧД'},'cardAddressVerified':True})
  facts=contact_facts.collect(messages,known)
  self.assertEqual(facts['address']['building'],'4')
  self.assertEqual(facts['address']['office'],'ЧД')
 def test_unverified_card_address(self):
  _,messages,known,_=_parse({'convId':'a','messages':[{'id':'a','direction':'in','body':'Да'}], 'cardAddress':{'street':'Тестовая','building':'4'}})
  self.assertFalse(contact_facts.collect(messages,known)['address'])
 def test_media_handoff(self):
  _,m,k,_=_parse({'convId':'a','messages':[{'id':'a','direction':'in','attachments':[{'type':'photo'}]}]})
  self.assertEqual(policy.assess(m,k,contact_facts.collect(m,k))['action'],'handoff')
 def test_723_owner_selected_general_third_price(self):
  m=[{'direction':'in','body':'Сколько стоит Windows?'},{'direction':'out','body':'От 1000 рублей'},{'direction':'in','body':'А сколько точно?'},{'direction':'out','body':'От 1000'},{'direction':'in','body':'Какая цена точно?'}]
  self.assertEqual(prices.answer(m,{'direction':'kp','partner':'723'},'Ноутбук Windows')['amounts'],[2000])
 def test_cross_chat_draft_rejected(self):
  import tempfile
  from assistant_store import Store
  with tempfile.TemporaryDirectory() as temp:
   s=Store(str(Path(temp)/'test.sqlite'))
   generation,_=s.observe('owner','one','same-revision')
   draft=s.save_draft('owner','one','same-revision',generation,{'reply':'test'})
   self.assertIsNotNone(s.draft('owner',draft,'same-revision','one'))
   self.assertIsNone(s.draft('owner',draft,'same-revision','two'))
if __name__=='__main__':unittest.main()
