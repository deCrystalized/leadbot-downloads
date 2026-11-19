import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_policy as policy
import qualification_state as qs
import research_proposals as proposals
from assistant_store import Store, digest
from extension_assistant import Assistant


def messages(question='Полка 80 сантиметров. А если крепежа окажется мало, мастер привезёт свой?'):
    return [dict(id='job',direction='in',sender_type='client',body='Нужно повесить полку в квартире. Схема есть, крепёж куплен.'),
            dict(id='wall-q',direction='out',sender_type='operator',body='Из какого материала стены?',delivery_status='delivered'),
            dict(id='wall',direction='in',sender_type='client',body='Стена кирпичная.'),
            dict(id='supply-q',direction='in',sender_type='client',body=question)]


class AnswerGoals219Tests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='goals219',LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        self.env.start();self.addCleanup(self.env.stop)
        self.app=Assistant(Store(directory.name+'/db'))
        ctx=dict(convId='synthetic-goals219',messages=messages(),city='Чита',dir='mnc',partner='7',
                 accountTitle='Мастер МНЧ',itemTitle='Мастер на час',origin='С1')
        out,code=self.app.handle(dict(owner='goals219',action='preview',ctx=ctx,wording_mode='neural_review'))
        self.assertEqual(code,200);self.assertTrue(out['pending_model'])
        self.scope='assistant:'+digest('goals219')
        _,self.payload=self.app.store.request(self.scope,out['request_id'])

    def test_current_question_gains_answer_goal_without_erasing_unknown_parts(self):
        before=copy.deepcopy(self.payload);plan=proposals.build(self.payload)
        self.assertIn('answer_current_question',plan['allowed_goals'])
        self.assertEqual(plan['answer_current_question'],'По материалам смогу сориентировать после осмотра.')
        self.assertNotEqual(self.payload['decision_internal']['qualification']['materials']['status'],'answered')
        self.assertEqual(before,self.payload)

    def test_contract_keeps_both_goals_free_meaning_and_original_veto(self):
        value=proposals.contract(self.payload)
        states=value['task']['output_contract']['decision_states']
        self.assertTrue(any(s.get('reply')==proposals.answer_only_reply(self.payload)and s['needs_operator']is False for s in states))
        self.assertTrue(any(s.get('reply')==''and s['needs_operator']is True for s in states))
        self.assertNotIn('enum',value['schema']['properties']['context_review']['properties']['last_intent'])
        self.assertIn('answer_current_question',value['system'])

    def test_exact_answer_has_normal_guards_and_defers_only_next_question(self):
        reply=proposals.answer_only_reply(self.payload)
        decision=proposals.validation_decision(reply,self.payload)
        self.assertNotIn('next_question',decision)
        self.assertEqual(decision['deferred_qualification_question'],self.payload['decision_internal']['next_question'])
        self.assertEqual(policy.validate_reply(reply,decision,self.payload['facts']),[])
        self.assertEqual(proposals.wording_violations(reply,self.payload),[])

    def test_no_stock_price_visit_or_extra_question_is_authorized(self):
        reply=proposals.answer_only_reply(self.payload)
        for tail in (' Детали привезу.',' Мастер завтра приедет.',' Цена 800 рублей.',
                     ' Назовите номер телефона.',' Крепёж точно подойдёт.'):
            with self.subTest(tail=tail):
                value=reply+tail
                self.assertIs(proposals.validation_decision(value,self.payload),self.payload['decision_internal'])
                self.assertTrue(proposals.wording_violations(value,self.payload))

    def test_no_permission_from_missing_rule_fixed_price_or_different_question(self):
        for kind in ('wall','model','price_consent','decision_maker'):
            p=copy.deepcopy(self.payload);p['decision_internal']['next_question']['kind']=kind
            with self.subTest(kind=kind):self.assertIsNone(proposals.answer_only_reply(p))
        p=copy.deepcopy(self.payload);task=json.loads(p['model_task']['task']);task['primary_sources']=[]
        p['model_task']['task']=json.dumps(task);self.assertIsNone(proposals.answer_only_reply(p))
        p=copy.deepcopy(self.payload);p['semantic_fixed_reply']='Работа от800 рублей.'
        self.assertIsNone(proposals.answer_only_reply(p))

    def test_no_permission_from_role_quote_or_undelivered_current_question(self):
        for patch in (dict(sender_type='system'),dict(delivery_status='pending'),dict(body='Сосед спросил: «Мастер привезёт крепёж?»')):
            p=copy.deepcopy(self.payload);p['messages'][-1].update(patch)
            with self.subTest(patch=patch):self.assertIsNone(proposals.answer_only_reply(p))

    def test_real_finalize_accepts_goal_without_rewriting_model_or_losing_meaning(self):
        reply=proposals.answer_only_reply(self.payload)
        candidate=dict(reply=reply,needs_operator=False,context_review=dict(
            last_intent='Клиент хочет повесить полку и уточнить возможную доставку крепежа.',
            latest_client_meaning='Называет ширину полки80см и спрашивает, привезёт ли мастер свой крепёж при нехватке.',
            selected_step_fits=True,evidence_ids=['supply-q'],note='Отвечаем на текущий вопрос без повторной анкеты, все материалы ещё не подтверждены.'))
        original=copy.deepcopy(candidate)
        final=self.app.finalize(self.scope,dict(request_id=self.payload['request_id'],revision=self.payload['revision'],candidate=candidate),research_proposal=proposals.build(self.payload))
        self.assertEqual(final['validation'],[]);self.assertEqual(final['reply'],reply)
        self.assertEqual(candidate,original)
        self.assertEqual(final['context_review']['last_intent'],candidate['context_review']['last_intent'])
        self.assertFalse(final['lead']['can_create_automatically'])

    def test_voluntary_later_kit_is_client_fact_not_answer_to_invented_question(self):
        ms=messages()+[dict(id='answer',direction='out',sender_type='operator',body='По материалам смогу сориентировать после осмотра.',delivery_status='delivered'),
                       dict(id='stock',direction='in',sender_type='client',body='Все детали и крепёж уже в наличии. Секунду, номер найду.')]
        row=qs.inspect(ms)['materials']
        self.assertEqual(row['status'],'answered');self.assertEqual(row['message_id'],'stock')
        self.assertEqual(row['availability_scope'],'client_reported_hanging_parts_only')
        self.assertNotIn('question_message_id',row)

    def test_voluntary_stock_needs_current_literal_client_and_same_work(self):
        for text in ('Все детали и крепёж будут завтра.', 'Если все детали и крепёж уже в наличии, хорошо.',
                     'Сосед сказал: «Все детали и крепёж уже в наличии».', 'Не все детали и крепёж есть.'):
            ms=messages()+[dict(id='stock',direction='in',sender_type='client',body=text)]
            with self.subTest(text=text):self.assertIsNone(qs.explicit_hanging_stock(ms,len(ms)-1))
        ms=messages()+[dict(id='stock',direction='in',sender_type='system',body='Все детали и крепёж уже в наличии.')]
        self.assertIsNone(qs.explicit_hanging_stock(ms,len(ms)-1))

    def test_voluntary_stock_can_be_withdrawn_without_prior_inventory_question(self):
        ms=messages()+[dict(id='stock',direction='in',sender_type='client',body='Все детали и крепёж уже в наличии.'),
                       dict(id='withdrawn',direction='in',sender_type='client',body='Крепёж вроде есть.')]
        row=qs.inspect(ms)['materials']
        self.assertEqual(row['status'],'uncertain');self.assertEqual(row['message_id'],'withdrawn')
        self.assertNotIn('question_message_id',row)


if __name__=='__main__':unittest.main()
