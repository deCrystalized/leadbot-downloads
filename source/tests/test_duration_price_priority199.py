"""A duration question cannot skip mandatory price or price acceptance."""
import unittest

import assistant_policy as policy
import test_work_duration198 as previous

row=previous.row


class DurationPricePriority199Tests(unittest.TestCase):
    setUp=previous.WorkDuration198Tests.setUp
    preview=previous.WorkDuration198Tests.preview
    proposal=previous.WorkDuration198Tests.proposal

    def test_clog_running_metre_price_is_quoted_with_no_duration_estimate(self):
        out,task,reply=self.proposal(messages=[row('Нужно устранить засор в унитазе. Сколько времени займёт работа?','job')],itemTitle='Сантехник')
        self.assertIn(policy.WORK_DURATION_REPLY,reply)
        self.assertIn('500 рублей за погонный метр',reply)
        self.assertIn('Такая стоимость вас устраивает?',reply)
        self.assertIn('DOC-L0499',out['rule_ids'])
        self.assertFalse(out['accepted_visit']);self.assertFalse(out['crm_preparation'])

    def test_console_minimum_and_price_acceptance_are_preserved(self):
        out,task,reply=self.proposal(messages=[row('Нужно почистить PlayStation 5. Сколько времени займёт чистка?','job')],
            dir='kp',itemTitle='Ремонт приставок',accountTitle='Учебный КП')
        self.assertIn(policy.WORK_DURATION_REPLY,reply)
        self.assertIn('от 1500 рублей',reply);self.assertIn('без учёта запчастей',reply)
        self.assertIn('Такая стоимость вас устраивает?',reply)
        self.assertFalse(out['accepted_visit']);self.assertFalse(out['crm_preparation'])

    def furniture_price_history(self,answer=None):
        h=[row('Нужно собрать шкаф','job'),row('Схема сборки есть?','scheme','out'),row('Да','yes'),
           row('Сборка мебели от 1500 рублей. Такая стоимость вас устраивает?','price','out')]
        if answer:h.append(row(answer,'priceanswer'))
        h.append(row('Сколько времени займёт работа?','duration'))
        return h

    def test_pending_price_acceptance_is_not_replaced_with_new_intake(self):
        out,task,reply=self.proposal(messages=self.furniture_price_history())
        self.assertIn(policy.WORK_DURATION_REPLY,reply)
        self.assertIn('Такая стоимость вас устраивает?',reply)
        self.assertEqual(out['crm_flags']['price_consent'],'pending')
        self.assertFalse(out['crm_preparation'])

    def test_accepted_price_is_not_requested_again(self):
        out,task,reply=self.proposal(messages=self.furniture_price_history('Да'))
        self.assertIn(policy.WORK_DURATION_REPLY,reply)
        self.assertNotIn('Такая стоимость вас устраивает?',reply)
        self.assertEqual(out['crm_flags']['price_consent'],'accepted')

    def test_prior_refusal_is_not_mistaken_for_price_acceptance(self):
        out,task,reply=self.proposal(messages=self.furniture_price_history('Нет, дорого'))
        self.assertIn(out['action'],('handoff','question'))
        if out['action']=='question':
            self.assertIn('Такая стоимость вас устраивает?',reply)
            self.assertNotEqual(out['crm_flags']['price_consent'],'accepted')
        self.assertFalse(out['lead']['can_create_automatically']);self.assertFalse(out['crm_preparation'])

    def test_no_price_duration_keeps_refusal_and_one_qualification(self):
        out,task,reply=self.proposal('Сколько времени займёт сборка?')
        self.assertIn(policy.WORK_DURATION_REPLY,reply);self.assertIn('Схема',reply)
        self.assertLessEqual(reply.count('?'),1);self.assertFalse(out['visit_offer'])

    def test_ambiguous_timing_without_price_keeps_owner_clarification(self):
        out,task,reply=self.proposal('И что по срокам?')
        self.assertEqual(task['decision']['next_question']['kind'],'timing_scope')
        self.assertEqual(reply,'Здравствуйте! Вы про время приезда или сколько займёт работа?')
        self.assertFalse(out['visit_offer'])
