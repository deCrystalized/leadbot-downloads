"""A save-number callback must not bypass intake guards or a price question."""
import unittest
import assistant_policy as policy
import contact_facts
import test_caller_id189 as helper


class CallbackPriority190Tests(unittest.TestCase):
    known=helper.CallerId189Tests.known
    request=helper.CallerId189Tests.request
    contact=helper.CallerId189Tests.contact
    assess=helper.CallerId189Tests.assess

    def test_named_other_territory_keeps_exact_handoff_before_missing_phone(self):
        messages=[helper.row('Собрать шкаф. Балашиха, улица Лесная, дом 1',ident='job')]
        before=self.assess(*messages)
        after=self.assess(*messages,self.request())
        self.assertEqual(before['action'],'handoff');self.assertIn('территори',before['reason'])
        self.assertEqual((after['action'],after['reason']),(before['action'],before['reason']))
        self.assertEqual(after['caller_id_callback']['status'],'awaiting_contact')

    def test_named_other_territory_still_wins_after_phone_arrives(self):
        messages=[helper.row('Собрать шкаф. Балашиха, улица Лесная, дом 1',ident='job')]
        before=self.assess(*messages)
        after=self.assess(*messages,self.request(),self.contact())
        self.assertEqual((after['action'],after['reason']),(before['action'],before['reason']))
        self.assertEqual(after['caller_id_callback']['status'],'operator_review')
        self.assertFalse(after['caller_id_callback']['execution_allowed'])

    def test_unknown_city_and_missing_source_do_not_become_callback_collection(self):
        messages=[helper.row('Собрать шкаф',ident='job'),self.request()]
        for known in (dict(self.known(),city='Неподтверждённый город'),dict(self.known(),account_name='')):
            out=policy.assess(messages,known,contact_facts.collect(messages,known))
            self.assertEqual(out['action'],'handoff');self.assertEqual(out['forced_reply'],'')
            self.assertIn('caller_id_callback',out)

    def test_work_requiring_approval_is_not_accepted_through_callback(self):
        job=helper.row('Установить видеодомофон',ident='job')
        before=self.assess(job);after=self.assess(job,self.request())
        self.assertEqual(before['action'],'handoff')
        self.assertIn('соглас',before['reason'])
        self.assertEqual((after['action'],after['reason']),(before['action'],before['reason']))

    def test_direct_service_refusal_is_not_replaced_by_callback_intake(self):
        job=helper.row('Нужно вскрыть замок',ident='job')
        before=self.assess(job);after=self.assess(job,self.request())
        self.assertEqual(before['action'],'refuse')
        self.assertEqual((after['action'],after['reason']),(before['action'],before['reason']))

    def test_bt_route_guard_keeps_priority_for_named_gas_appliance(self):
        job=helper.row('Подключить газовую плиту',ident='job')
        before=self.assess(job);after=self.assess(job,self.request())
        self.assertEqual(before['action'],'handoff');self.assertIn('БТ',before['reason'])
        self.assertEqual((after['action'],after['reason']),(before['action'],before['reason']))

    def test_current_price_question_is_not_replaced_by_old_avito_own_number_fallback(self):
        messages=[helper.row('Собрать шкаф',ident='job'),helper.row('Мне нужен ваш номер, чтобы сохранить. Сколько стоит собрать шкаф?',ident='price')]
        out=self.assess(*messages)
        self.assertEqual(out['action'],'price');self.assertNotIn('phone_exchange',out)
        self.assertEqual(out['caller_id_callback']['status'],'awaiting_contact')


if __name__=='__main__':unittest.main()
