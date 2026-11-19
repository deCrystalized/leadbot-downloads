"""Incident-derived address preservation; no guessed city or routine recheck."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import contact_facts
import extension_assistant
import assistant_qualifiers


def rows(*pairs):
    return [dict(id=str(i), direction=d, body=b) for i,(d,b) in enumerate(pairs)]


class AddressFineTests(unittest.TestCase):
    def ctx(self,messages,city='Омск'):
        return extension_assistant._parse(dict(convId='synthetic-address-fine',city=city,dir='mnc',partner='7',
            channel='avito',accountTitle='Мастер МНЧ',itemTitle='Сборка мебели',messages=messages))[1:3]

    def test_untyped_client_microdistrict_survives_without_becoming_a_guessed_city(self):
        messages,known=self.ctx(rows(('in','Королева 8 южные ворота этаж 3 кВ 191')))
        facts=contact_facts.collect(messages,known)
        self.assertEqual(facts['address']['settlement'],'южные ворота')
        self.assertEqual(facts['address']['building'],'8')
        self.assertEqual(facts['address']['floor'],'3')
        self.assertEqual(facts['address']['office'],'191')
        self.assertFalse(facts['address'].get('city'))
        self.assertEqual(facts['client_location']['status'],'missing')
        self.assertIn('южные ворота',' '.join(facts['comment_lines']))

    def test_explicit_other_city_blocks_wrong_form_but_corrected_target_is_not_stuck(self):
        text='Я в Томске, Королева 8, нужно поставить двери шкафа'
        for city,blocked in [('Омск',True),('Томск',False)]:
            messages,known=self.ctx(rows(('in',text)),city)
            check=extension_assistant.manual_checklist(messages,known)
            self.assertEqual(check['hard_block'],blocked)
            self.assertEqual(check['facts']['client_location']['city'],'Томск')
            self.assertEqual(check['facts']['client_location']['message_id'],'0')

    def test_listing_or_question_about_master_does_not_prove_client_city(self):
        for text in ['Королева 8, квартира 191','Вы в Омске?','Вы из Омска?']:
            messages,known=self.ctx(rows(('in',text)))
            self.assertEqual(contact_facts.collect(messages,known)['client_location']['status'],'missing',text)

    def test_city_answer_is_reused_without_repeated_question(self):
        messages,known=self.ctx(rows(('out','Вы в Омске?'),('in','Да')))
        location=contact_facts.collect(messages,known)['client_location']
        self.assertEqual(location['status'],'confirmed');self.assertEqual(location['source'],'city_question_answer')
        self.assertEqual(location['message_id'],'1')
        messages,known=self.ctx(rows(('in','Я в Томске, нужно починить шкаф')),city='Томск')
        facts=contact_facts.collect(messages,known)
        self.assertNotEqual(assistant_qualifiers.next_question(messages,known,facts)['kind'],'city')


if __name__=='__main__':unittest.main()
