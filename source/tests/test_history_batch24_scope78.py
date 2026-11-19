"""Frozen901–940 and explicit owner coffee definition; no live actions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'leadbot/brain'))
import assistant_catalog as catalog
import contact_facts
import qualification_state as qs


def rows(*pairs):
    return [dict(id=str(i),direction=d,body=t) for i,(d,t) in enumerate(pairs)]


class HistoryBatch24Scope78Tests(unittest.TestCase):
    def choose(self,text,direction='mnc'):
        return catalog.choose(text,dict(direction=direction,city='Москва'))

    def test_a_clog_in_a_cast_iron_riser_is_not_a_riser_replacement(self):
        for text in ('Нужно прочистить засор в чугунном стояке',
                     'Стоит вода в стояке, не могу прочистить. Стояк чугун',
                     'Устранить засор канализационной трубы'):
            out=self.choose(text)
            self.assertEqual(out['status'],'supported',out)
            self.assertEqual([x['id'] for x in out['items']],['drain'])
            self.assertIn('DOC-L0292',out['rules'])
            self.assertNotIn('DOC-L0284',out['rules'])

    def test_real_written_riser_clog_keeps_the_client_operation(self):
        history=rows(('in','Здравствуйте, стоит вода в стояке, не могу прочистить'),
                     ('out','Трубы какие у вас?'),('in','Стояк чугун'))
        facts=contact_facts.collect(history)
        out=self.choose(contact_facts.intent_text('\n'.join(m['body'] for m in history if m['direction']=='in'),facts))
        self.assertEqual([x['id'] for x in out['items']],['drain'])

    def test_explicit_riser_replacement_or_cutting_still_needs_approval(self):
        for text in ('Прочистить засор и заменить чугунный стояк',
                     'Устранить засор. Также нужна врезка в стояк',
                     'После прочистки нужно перенести канализационную трубу'):
            out=self.choose(text)
            self.assertIn('DOC-L0284',out['rules'])
            self.assertNotEqual(out['status'],'supported',out)

    def test_heating_work_is_not_reclassified_as_ordinary_drain_cleaning(self):
        out=self.choose('Устранить засор в радиаторе отопления')
        self.assertIn('DOC-L0286',out['rules'])
        self.assertNotEqual(out['status'],'supported')

    def test_riser_leak_without_a_clog_is_not_admitted_by_clog_rules(self):
        out=self.choose('Чугунный стояк течёт, нужно заменить')
        self.assertIn('DOC-L0284',out['rules'])
        self.assertNotIn('drain',{x['id'] for x in out['items']})

    def test_call_to_wife_as_they_approach_is_arrival_not_before_departure(self):
        for body in ('Позвоните жене как будут подъезжать',
                     'Позвоните жене, когда будете подъезжать'):
            facts=contact_facts.collect(rows(('in',body)))
            self.assertTrue(facts['call_before_visit'],facts)
            self.assertEqual(facts['call_timing'],'upon_arrival')
            self.assertIn('Позвонить при подъезде по просьбе клиента.',facts['comment_lines'])

    def test_negative_or_staff_arrival_request_cannot_set_the_client_flag(self):
        for d,t in [('out','Позвоните жене как будут подъезжать'),
                    ('in','Не звоните жене как будут подъезжать')]:
            self.assertEqual(contact_facts.collect(rows((d,t)))['call_timing'],'not_stated')

    def test_a_professional_portafilter_is_not_industrial_by_its_format(self):
        for body in ('Профессиональная рожковая кофемашина Nuova Simonelli, две группы, не работают кнопки',
                     'Промышленная рожковая кофемашина, не торговый автомат, терминала оплаты нет'):
            out=self.choose(body,'bt')
            self.assertEqual(out['status'],'supported',out)
            self.assertNotIn('industrial',{x['id'] for x in out['items']})

    def test_confirmed_coffee_vending_with_payment_terminal_needs_approval(self):
        for body in ('Кофейный торговый автомат с терминалом оплаты не работает',
                     'Вендинговая кофемашина со встроенным платёжным терминалом'):
            out=self.choose(body,'bt')
            self.assertEqual(out['status'],'agree',out)
            self.assertIn('DOC-L0466',out['rules'])
            self.assertIn('OWNER-COFFEE-VENDING-20261019',out['rules'])

    def test_an_ambiguous_industrial_coffee_label_gets_one_terminal_question(self):
        out=self.choose('Промышленная кофемашина не работает','bt')
        self.assertEqual(out['status'],'supported',out)
        self.assertIn('coffee_vending',out['items'][0]['questions'])

    def test_coffee_vending_answer_is_bound_to_the_actual_question(self):
        question='Это торговый кофейный автомат с терминалом оплаты?'
        for answer,wanted in [('Да','yes'),('Нет','no')]:
            state=qs.inspect(rows(('in','Промышленная кофемашина не работает'),('out',question),('in',answer)))
            self.assertEqual(state['coffee_vending']['value'],wanted)
        state=qs.inspect(rows(('out','Подъехать сегодня?'),('in','Да')))
        self.assertEqual(state['coffee_vending']['status'],'missing')

    def test_ambiguous_industrial_question_precedes_coffee_type_and_model(self):
        from extension_assistant import _parse
        import assistant_policy
        _,history,known,_=_parse(dict(convId='synthetic-scope78-priority',city='Москва',dir='bt',channel='avito',
                                     partner='7',accountTitle='Иван БТ',itemTitle='Ремонт техники',adIdentity='Иван',origin='С1',
                                     messages=rows(('in','Промышленная кофемашина не работает'))))
        out=assistant_policy.assess(history,known,contact_facts.collect(history,known))
        self.assertEqual(out['next_question']['question'],'Это торговый кофейный автомат с терминалом оплаты?')

    def test_an_unrelated_cafe_payment_terminal_does_not_make_a_portafilter_industrial(self):
        out=self.choose('Рожковая кофемашина в кафе. Рядом на кассе терминал оплаты','bt')
        self.assertEqual(out['status'],'supported',out)

    def test_vendor_without_payment_terminal_does_not_get_industrial_approval(self):
        for ending in ('без терминала оплаты','терминал оплаты отсутствует',
                       'не оборудован платёжным терминалом'):
            out=self.choose('Кофейный торговый автомат, '+ending,'bt')
            self.assertEqual(out['status'],'supported',out)
            self.assertNotIn('DOC-L0466',out['rules'])

    def test_a_terminal_elsewhere_in_the_cafe_is_not_bound_to_the_vendor(self):
        for body in ('Кофейный автомат. На кассе терминал оплаты',
                     'Кофейный автомат, рядом терминал оплаты на кассе'):
            out=self.choose(body,'bt')
            self.assertEqual(out['status'],'supported',out)
            self.assertIn('coffee_vending',out['items'][0]['questions'])

    def test_terminal_in_the_machine_can_be_reported_in_the_next_sentence(self):
        out=self.choose('Кофейный торговый автомат. В нём терминал оплаты не работает','bt')
        self.assertEqual(out['status'],'agree',out)
        self.assertIn('OWNER-COFFEE-VENDING-20261019',out['rules'])

    def test_vending_definition_does_not_remove_an_independent_electrician_job(self):
        out=self.choose('Кофейный торговый автомат с терминалом оплаты и заменить электрический автомат в щитке','bt')
        self.assertIn('coffee-vending',{x['id'] for x in out['items']})
        self.assertNotEqual(out['status'],'supported')

    def test_other_industrial_appliances_keep_their_approval(self):
        for body in ('Промышленная стиральная машина без терминала оплаты',
                     'Промышленная стиральная машина и рожковая кофемашина'):
            out=self.choose(body,'bt')
            self.assertIn('DOC-L0466',out['rules'])
            self.assertNotEqual(out['status'],'supported')

    def test_capsule_rule_is_independent_of_the_industrial_definition(self):
        body='Капсульная кофемашина без терминала оплаты, не работает'
        out=self.choose(body,'bt');issue=catalog.condition_issue(out,qs.inspect(rows(('in',body))),body)
        self.assertIsNotNone(issue)
        self.assertIn('DOC-L0406',issue[1])


if __name__=='__main__':unittest.main()
