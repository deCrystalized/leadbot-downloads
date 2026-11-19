"""Owner's optional extra look does not become approved extra execution."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_catalog as catalog
import assistant_policy as policy
import contact_facts
import extension_assistant as ext
from assistant_store import Store


def rows(*values):
    return [dict(id='m'+str(i), direction=d, sender_type='client' if d=='in' else 'operator', body=b)
            for i,(d,b) in enumerate(values)]


class MixedOptional186Tests(unittest.TestCase):
    def known(self, **extra):
        return dict(direction='mnc', city='Тула', channel='avito', title='Мастер на час',
                    partner='7', origin='С1', account_name='Мастер МНЧ', **extra)

    def facts(self, messages, known=None):
        return contact_facts.collect(messages, known or self.known())

    def scope(self, body):
        return self.facts(rows(('in',body))).get('mixed_optional_work')

    def preview(self, messages):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,
                LEADBOT_PERSONAL_OWNER_ID='mixed186', LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            app = ext.Assistant(Store(tmp+'/db'))
            ctx = dict(convId='synthetic-mixed186', dir='mnc', city='Тула', partner='7',
                channel='avito', origin='С1', accountTitle='Мастер МНЧ', itemTitle='Мастер на час', messages=messages)
            value, code = app.handle(dict(owner='mixed186', action='preview', wording_mode='neural_review', ctx=ctx))
            self.assertEqual(code,200)
            self.assertFalse(value['auto_enabled'])
            self.assertFalse(value['lead']['can_create_automatically'])
            return value

    def test_owner_example_separates_primary_from_optional_heat(self):
        scope=self.scope('Заменить смеситель и установить карниз. По возможности посмотреть отопление.')
        self.assertEqual(scope['primary_service']['status'],'supported')
        self.assertEqual(scope['extras'][0]['message_id'],'m0')
        self.assertTrue(scope['extras'][0]['client_requested_look'])
        self.assertFalse(scope['extra_execution_approved'])
        self.assertNotRegex(scope['primary_text'],'отоплен')
        self.assertRegex(scope['comment'],'по возможности посмотреть отопление')

    def test_heating_shutoff_does_not_become_branch_approval(self):
        scope=self.scope('Установить унитаз на готовое место; установить умывальник и подключить смеситель; '
                         'посмотреть батарею, она текла, отопление отключили, возможен мелкий ремонт.')
        self.assertIsNotNone(scope)
        self.assertFalse(scope['extra_execution_approved'])
        self.assertFalse(scope['client_consent_to_extra_execution'])
        self.assertNotIn('pipes-riser',[i['id'] for i in scope['primary_service']['items']])

    def test_catalogue_still_requires_approval_for_heating_execution(self):
        service=catalog.choose('Заменить смеситель; заменить радиатор отопления.',self.known())
        self.assertEqual(service['status'],'mixed')
        self.assertIn('DOC-L0286',service['rules'])
        self.assertIsNone(self.scope('Заменить смеситель; заменить радиатор отопления.'))

    def test_only_agreement_work_does_not_gain_primary_intake(self):
        for body in ['Посмотреть батарею, она течёт.','По возможности заменить радиатор отопления.']:
            with self.subTest(body=body): self.assertIsNone(self.scope(body))

    def test_mandatory_extra_or_conditional_whole_order_stays_guarded(self):
        for body in ['Заменить смеситель. Обязательно отремонтировать отопление.',
                     'Повесить полку. Только если установите перегородку.',
                     'Заменить смеситель. Без ремонта отопления не надо приезжать.']:
            with self.subTest(body=body): self.assertIsNone(self.scope(body))

    def test_refused_work_is_not_optional_intake(self):
        for body in ['Заменить смеситель; посмотреть газовую плиту.',
                     'Повесить полку; посмотреть несущую перегородку и снести стену.',
                     'Заменить смеситель; посмотреть отопление и газовый котёл.']:
            with self.subTest(body=body): self.assertIsNone(self.scope(body))

    def test_unknown_independent_job_cannot_hide_behind_supported_tap(self):
        for body in ['Построить сарай, заменить смеситель; посмотреть батарею.',
                     'Заменить смеситель; установить неизвестный агрегат; посмотреть батарею.',
                     'Заменить смеситель; по возможности починить телепорт.']:
            with self.subTest(body=body): self.assertIsNone(self.scope(body))

    def test_specific_owner_examples_offer_inspection_without_promising_installation(self):
        for body,subject in [('Повесить полку. Установить реечную перегородку.','partition'),
                             ('Заменить смеситель; установить светодиодную ленту.','led_strip')]:
            with self.subTest(body=body):
                scope=self.scope(body)
                self.assertEqual(scope['extras'][0]['subject'],subject)
                self.assertFalse(scope['extra_execution_approved'])
                self.assertRegex(scope['comment'],'выполнение работ не подтверждено')

    def test_quote_or_foreign_report_does_not_supply_optional_work(self):
        for extra in ['Сосед сказал посмотреть батарею.', 'Вчера смотрели батарею.',
                      '«Посмотреть батарею».','Если когда-нибудь понадобится посмотреть отопление.']:
            with self.subTest(extra=extra): self.assertIsNone(self.scope('Заменить смеситель. '+extra))

    def test_staff_system_and_bot_cannot_add_client_extra(self):
        for direction,kind in [('out','operator'),('system','system'),('in','bot')]:
            messages=rows(('in','Заменить смеситель.'))+[dict(id='x',direction=direction,sender_type=kind,body='Посмотреть батарею.')]
            self.assertNotIn('mixed_optional_work',self.facts(messages))

    def test_other_directions_and_max_do_not_gain_this_scope(self):
        messages=rows(('in','Заменить смеситель; посмотреть батарею.'))
        for known in [dict(self.known(),direction='kp'),dict(self.known(),direction='bt'),dict(self.known(),channel='max_user')]:
            self.assertNotIn('mixed_optional_work',self.facts(messages,known))

    def test_literal_extra_quote_and_id_are_not_rewritten_as_execution(self):
        quote='посмотреть одну батарею - она текла, возможен мелкий ремонт.'
        scope=self.scope('Заменить смеситель; '+quote)
        self.assertEqual(scope['extras'][0]['quote'],quote)
        self.assertEqual(scope['extras'][0]['source'],'client_message')

    def test_main_qualification_survives_instead_of_whole_job_handoff(self):
        out=self.preview(rows(('in','Установить унитаз на готовое место; посмотреть батарею.')))
        self.assertTrue(out.get('pending_model'))
        self.assertEqual(out['service']['status'],'supported')
        self.assertEqual(json.loads(out['model_task']['task'])['decision']['next_question']['kind'],'toilet_type')
        self.assertIn('OWNER-MIXED-OPTIONAL-LOOK-20261023',out['rule_ids'])

    def test_model_gets_separate_extra_with_no_execution_or_client_consent(self):
        out=self.preview(rows(('in','Заменить смеситель; посмотреть батарею.')))
        task=json.loads(out['model_task']['task'])
        context=task['mixed_optional_work_context']
        self.assertFalse(context['extra_execution_approved'])
        self.assertFalse(context['client_consent_to_extra_execution'])
        self.assertEqual(context['extras'][0]['message_id'],'m0')
        self.assertRegex(context['instruction'],'не согласованное выполнение')

    def test_reply_must_keep_caveat_and_cannot_promote_to_repair(self):
        messages=rows(('in','Заменить смеситель; посмотреть батарею.'))
        facts=self.facts(messages);decision=policy.assess(messages,self.known(),facts)
        reply=policy.compose_reply('Смеситель у вас куплен?',decision)
        self.assertIn(facts['mixed_optional_work']['disclosure'],reply)
        self.assertNotIn('optional_inspection_caveat_missing',policy.validate_reply(reply,decision,facts))
        bad=reply+' По отоплению всё отремонтирую.'
        self.assertIn('optional_inspection_promoted_to_execution',policy.validate_reply(bad,decision,facts))
        self.assertIn('optional_inspection_caveat_missing',policy.validate_reply('Здравствуйте! Всё сделаю.',decision,facts))

    def test_crm_projection_restores_caveat_without_changing_service_phone(self):
        facts=self.facts(rows(('in','Заменить смеситель; посмотреть батарею.')))
        self.assertEqual(facts['comment_lines'].count(facts['mixed_optional_work']['comment']),1)
        self.assertEqual(contact_facts.crm_comment_lines(facts),facts['comment_lines'])
        self.assertNotIn('service_comment_instruction',facts)

    def test_manual_form_uses_primary_conditions_and_keeps_optional_note(self):
        messages=rows(('in','Установить унитаз на готовое место; посмотреть батарею.'))
        ctx=dict(convId='synthetic-manual186',dir='mnc',city='Тула',channel='avito',partner='7',origin='С1',
                 accountTitle='Мастер МНЧ',itemTitle='Мастер на час',messages=messages)
        _,parsed,known,_=ext._parse(ctx)
        out=ext.manual_checklist(parsed,known)
        self.assertFalse(out['auto_enabled'])
        self.assertEqual(out['approval'],'')
        self.assertTrue(any(x['key']=='toilet_type' and not x['done'] for x in out['results']))
        self.assertRegex('\n'.join(out['facts']['comment_lines']),'по возможности посмотреть отопление')

    def test_later_withdrawn_extra_removes_old_caveat_and_keeps_primary(self):
        messages=rows(('in','Заменить смеситель; посмотреть батарею.'),('in','Батарею смотреть не нужно.'))
        facts=self.facts(messages)
        scope=facts['mixed_optional_work']
        self.assertEqual(scope['extras'],[])
        self.assertEqual(scope['withdrawn_subjects'],['heating'])
        self.assertEqual(scope['primary_service']['status'],'supported')
        self.assertFalse(any('Дополнительно' in x for x in facts['comment_lines']))

    def test_positive_execution_claim_in_internal_meaning_is_not_an_inspection(self):
        scope=self.scope('Заменить смеситель; посмотреть батарею.')
        for text in ['По батарее согласован ремонт.', 'Мастер заменит батарею.', 'Отопление отремонтирую.',
                     'Ремонт отопления не обещаю, но батарею заменю.']:
            self.assertTrue(catalog.optional_execution_claim(text,scope),text)
        for text in ['Клиент просит посмотреть батарею.', 'По батарее ремонт не согласован.',
                     'Отопление смогу только посмотреть.', 'Смеситель заменю.']:
            self.assertFalse(catalog.optional_execution_claim(text,scope),text)

    def test_internal_semantic_guard_rejects_extra_approval_without_repairing_json(self):
        out=self.preview(rows(('in','Установить унитаз; посмотреть батарею.')))
        task=json.loads(out['model_task']['task'])
        candidate=dict(reply=task['proposed_reply'],needs_operator=False,
            context_review=dict(last_intent='Установить унитаз и дополнительно посмотреть батарею.',
                latest_client_meaning='Клиент просит установить унитаз и посмотреть батарею.',
                selected_step_fits=True,evidence_ids=[task['latest_client_message']['id']],note='Дополнительный ремонт не согласован.'))
        original=copy.deepcopy(candidate)
        self.assertEqual(ext._context_review(candidate,task)[1:],('provided',[]))
        candidate['context_review']['note']='Ремонт батареи согласован.'
        negative=copy.deepcopy(candidate)
        self.assertIn('optional_inspection_promoted_to_execution',ext._context_review(candidate,task)[2])
        self.assertEqual(candidate,negative)
        self.assertNotEqual(candidate,original)

    def test_battery_of_device_and_unqualified_partition_are_not_heating_scope(self):
        for body in ['Заменить смеситель; посмотреть батарею ноутбука.',
                     'Повесить полку; установить перегородку неизвестного типа.']:
            self.assertIsNone(self.scope(body))

    def test_browser_cannot_supply_optional_approval_instead_of_client_source(self):
        ctx=dict(convId='synthetic-forged186',dir='mnc',city='Тула',channel='avito',partner='7',origin='С1',
                 accountTitle='Мастер МНЧ',itemTitle='Мастер на час',messages=rows(('in','Заменить смеситель.')),
                 mixed_optional_work=dict(extra_execution_approved=True))
        _,parsed,known,_=ext._parse(ctx)
        self.assertNotIn('mixed_optional_work',self.facts(parsed,known))

    def test_mandatory_call_ahead_does_not_turn_optional_heat_into_mandatory_repair(self):
        scope=self.scope('Заменить смеситель; посмотреть батарею. Обязательно позвоните перед приездом.')
        self.assertIsNotNone(scope)
        self.assertFalse(scope['extra_execution_approved'])


if __name__=='__main__': unittest.main()
