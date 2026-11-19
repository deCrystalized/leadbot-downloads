"""Current data-safety question is answered without promising preservation."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_policy as policy
import research_proposals as proposals
from assistant_store import Store, digest
from extension_assistant import Assistant
import test_payment_documents264 as fixture


class OfficeDataQuestion264Tests(unittest.TestCase):
    def rows(self, *texts):
        return [fixture.msg(text, 'c'+str(i)) for i, text in enumerate(texts)]

    def test_full_initial_data_loss_question_is_recognized(self):
        self.assertTrue(policy.office_data_preservation_question(self.rows(fixture.INITIAL)))

    def test_later_direct_file_safety_question_uses_current_observed_software_fault(self):
        rows = self.rows('Word не открывается.', 'Можно без потери данных?')
        self.assertTrue(policy.office_data_preservation_question(rows))

    def test_preservation_statement_does_not_become_a_client_question(self):
        self.assertFalse(policy.office_data_preservation_question(self.rows('Word не открывается. Документы нужно сохранить.')))

    def test_delivered_staff_answer_ends_the_prior_question(self):
        rows = self.rows(fixture.INITIAL)
        rows += [fixture.msg(policy.DATA_PRESERVATION_REPLY, 'o1', 'out', sender_type='operator', delivery_status='delivered'),
                 fixture.msg('Меня зовут Сергей.', 'c2')]
        self.assertFalse(policy.office_data_preservation_question(rows))

    def test_system_or_failed_outgoing_text_does_not_answer_the_client(self):
        for extra in (dict(sender_type='system'), dict(sender_type='operator', delivery_status='failed')):
            rows = self.rows(fixture.INITIAL) + [fixture.msg('Ответ готов.', 'o1', 'out', **extra)]
            with self.subTest(extra=extra):
                self.assertTrue(policy.office_data_preservation_question(rows))

    def test_roles_delivery_and_negated_questions_do_not_supply_a_request(self):
        for change in (dict(sender_type='system'),dict(sender_type='operator'),dict(speaker_role='service'),
                       dict(role='system'),dict(delivery_status='failed'),dict(delivery_status='pending'),dict(out_pending=True)):
            row=fixture.msg(fixture.INITIAL, **change)
            with self.subTest(change=change):
                self.assertFalse(policy.office_data_preservation_question([row]))
        self.assertFalse(policy.office_data_preservation_question(self.rows('Word не открывается. Не спрашиваю, сохранятся ли файлы?')))

    def test_foreign_question_and_quoted_text_do_not_supply_a_request(self):
        for body in ('Word не открывается. Мастер спросил: «Файлы сохранятся?»',
                     'Word не открывается. Сосед спросил, можно без потери файлов?'):
            with self.subTest(body=body):
                self.assertFalse(policy.office_data_preservation_question(self.rows(body)))

    def test_new_order_cannot_borrow_the_old_office_fault(self):
        rows=self.rows('Word не открывается.', 'Новая заявка. Можно восстановить файлы с другого диска?')
        self.assertFalse(policy.office_data_preservation_question(rows))

    def test_no_ordinary_office_scope_no_new_data_disclosure(self):
        self.assertFalse(policy.office_data_preservation_question(self.rows('Жёсткий диск не определяется. Файлы сохранятся?')))

    def payload(self, rows=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_AUTO_AVAILABLE='0',LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start();self.addCleanup(env.stop)
        app=Assistant(Store(str(Path(temp.name)/'assistant.sqlite3')))
        ctx=dict(convId='office-data264',messages=rows or self.rows(fixture.INITIAL),dir='kp',partner='7',city='Чита',
                 accountTitle='Георгий КП',itemTitle='Компьютерная помощь',origin='С1')
        out,code=app.handle(dict(owner='office-data264',action='preview',ctx=ctx,wording_mode='neural_review'))
        self.assertEqual(code,200);self.assertTrue(out['pending_model'])
        _,payload=app.store.request('assistant:'+digest('office-data264'),out['request_id'])
        return out,payload

    def test_whole_original_reply_answers_file_question_before_lpr(self):
        out,p=self.payload()
        task=__import__('json').loads(p['model_task']['task'])
        reply=task['proposed_reply']
        self.assertIn(policy.DATA_PRESERVATION_REPLY,reply)
        self.assertLess(reply.index(policy.DATA_PRESERVATION_REPLY),reply.index('принимать решение'))
        self.assertNotRegex(reply,'БСО|кассов|модель|переустановим|сохраним все')
        self.assertFalse(out['auto_enabled'])

    def test_public_reviewed_reply_survives_the_actual_reply_guard(self):
        _,p=self.payload()
        reply=policy.compose_reply(p['decision_internal']['next_question']['question'],p['decision_internal'])
        self.assertEqual(policy.validate_reply(reply,p['decision_internal'],p['facts']),[])
        answer=proposals.answer_only_reply(p)
        self.assertEqual(policy.validate_reply(answer,proposals.validation_decision(answer,p),p['facts']),[])

    def test_explicit_negative_guarantee_is_not_an_affirmative_diagnosis(self):
        _,p=self.payload()
        for text in ('Не могу гарантировать сохранность файлов.', 'Сохранность файлов гарантировать не могу.'):
            decision=copy.deepcopy(p['decision_internal']);decision['required_text']=[];decision.pop('next_question',None)
            with self.subTest(text=text):
                self.assertNotIn('unsupported_diagnosis',policy.validate_reply('Здравствуйте! '+text,decision,p['facts']))

    def test_a_negative_guarantee_cannot_hide_an_affirmative_promise(self):
        _,p=self.payload()
        for text in ('Гарантирую сохранить все файлы.', 'Гарантирую не потерять файлы.',
                     'Не могу гарантировать срок, но точно починю.',
                     'Гарантировать срок не могу. Всё исправлю.'):
            with self.subTest(text=text):
                self.assertIn('unsupported_diagnosis',policy.validate_reply('Здравствуйте! '+text,p['decision_internal'],p['facts']))

    def test_exact_answer_only_option_defers_lpr_without_repairing_json_or_dropping_source(self):
        _,p=self.payload();before=copy.deepcopy(p)
        plan=proposals.build(p)
        self.assertIn('answer_current_question',plan['allowed_goals'])
        reply=plan['answer_current_question']
        self.assertIn(policy.DATA_PRESERVATION_REPLY,reply)
        self.assertNotIn('принимать решение',reply)
        self.assertEqual(proposals.wording_violations(reply,p),[])
        checked=proposals.validation_decision(reply,p)
        self.assertEqual(checked['deferred_qualification_question'],p['decision_internal']['next_question'])
        self.assertEqual(p,before)

    def test_data_answer_keeps_free_meaning_and_justified_veto(self):
        _,p=self.payload();contract=proposals.contract(p)
        for key in ('last_intent','latest_client_meaning','note'):
            self.assertNotIn('enum',contract['schema']['properties']['context_review']['properties'][key])
        veto=next(s for s in contract['task']['output_contract']['decision_states']if s['needs_operator']is True)
        self.assertEqual(veto['reply'],'');self.assertFalse(veto['context_review']['selected_step_fits'])
        self.assertEqual(contract['task']['proposal_plan']['action_authority'],'none')

    def test_unobserved_or_removed_disclosure_cannot_authorize_answer_only(self):
        _,p=self.payload()
        p['decision_internal']['required_text']=[]
        self.assertIsNone(proposals.answer_only_reply(p))
        _,p=self.payload();p['messages'][-1]['body']='Word не открывается. Меня зовут Сергей.'
        self.assertIsNone(proposals.answer_only_reply(p))

    def test_existing_order_and_client_pause_still_stop_before_new_reply(self):
        for ctx_change,rows in [({'crmRequestId':'synthetic-existing264'},self.rows(fixture.INITIAL)),
                               ({},self.rows(fixture.INITIAL,'Секунду, уточню у жены.'))]:
            with self.subTest(change=ctx_change),tempfile.TemporaryDirectory()as temp:
                app=Assistant(Store(str(Path(temp)/'db')))
                ctx=dict(convId='office-guard264',messages=rows,dir='kp',city='Чита',partner='7',
                         accountTitle='Георгий КП',itemTitle='Компьютерная помощь',origin='С1',**ctx_change)
                out,code=app.handle(dict(owner='guard264',action='preview',ctx=ctx,wording_mode='reviewed'))
                self.assertEqual(code,200);self.assertIn(out['action'],('handoff','wait'))
                self.assertEqual(out['reply'],'')


if __name__=='__main__':
    unittest.main()
