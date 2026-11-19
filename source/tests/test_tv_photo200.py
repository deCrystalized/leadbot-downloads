"""Source-bound screen appearance and photo coordination never approve a repair."""
import copy
import unittest

import assistant_catalog
import assistant_policy as policy
import contact_facts
import personal_media
import qualification_state as qs
import test_caller_id189 as helper
import test_personal_media as media_fixture

row=helper.row


def known(direction='kp',**extra):
    value=dict(direction=direction,channel='avito',city='Оренбург',partner='7',
               title='Ремонт телевизоров',account_name='Учебный мастер')
    value.update(extra)
    return value


def image():
    m=row('',ident='photo',media_reviewed=True,unread_media=False,media_signature='signature')
    personal_media.attach_observation(m,dict(content_kind='product_photo',device_kind='tv',
        visible_symptom='screen_cracks'),source='offline_reviewed_image')
    return m


def assess(messages,direction='kp',**extra):
    k=known(direction,**extra)
    return policy.assess(messages,k,contact_facts.collect(messages,k))


class TvPhoto200Tests(unittest.TestCase):
    def test_literal_tv_cracks_are_not_bands_or_matrix_diagnosis(self):
        value=personal_media.normalize_observations(dict(content_kind='product_photo',device_kind='tv',visible_symptom='screen_cracks'))
        self.assertEqual(value['visible_symptom'],'screen_cracks');self.assertNotIn('matrix',str(value))

    def test_other_subject_or_image_kind_cannot_claim_tv_cracks(self):
        for device,kind in [('monitor','product_photo'),('pc','product_photo'),('tv','product_card'),
                            ('tv','device_label'),('tv','assembly_diagram'),('','product_photo')]:
            with self.subTest(device=device,kind=kind),self.assertRaises(ValueError):
                personal_media.normalize_observations(dict(content_kind=kind,device_kind=device,visible_symptom='screen_cracks'))

    def test_exact_client_image_binding_is_required(self):
        original=image();self.assertTrue(personal_media.reviewed_tv_screen_cracks(original))
        for field,value in [('direction','out'),('sender_type','operator'),('sender_type','system'),
                            ('media_reviewed',False),('unread_media',True),('media_signature','other')]:
            m=copy.deepcopy(original);m[field]=value
            with self.subTest(field=field,value=value):self.assertFalse(personal_media.reviewed_tv_screen_cracks(m))
        for field,value in [('message_id','other'),('signature','other'),('source','client'),('device_kind','monitor')]:
            m=copy.deepcopy(original);m['media_observation'][field]=value
            with self.subTest(field=field):self.assertFalse(personal_media.reviewed_tv_screen_cracks(m))

    def test_literal_photo_facts_and_comment_keep_unknown_cause(self):
        messages=[row('Телевизор, можно помочь?',ident='job'),image()]
        facts=contact_facts.collect(messages,known())
        self.assertEqual(facts['image_observations'][0]['visible_symptom'],'screen_cracks')
        text=contact_facts.intent_text('Телевизор, можно помочь?',facts)
        self.assertIn('трещины',text);self.assertNotIn('полосы',text);self.assertNotIn('матриц',text)
        self.assertTrue(any('трещины' in line and 'причина не установлена' in line for line in facts['comment_lines']))

    def test_photo_damage_has_its_own_evidence_and_unknown_tv_type(self):
        state=qs.inspect([row('Телевизор',ident='job'),image()])
        self.assertEqual(state['screen_damage']['status'],'answered')
        self.assertEqual(state['screen_damage']['reviewed_screen_cracks']['message_id'],'photo')
        self.assertNotEqual(state['tv_type']['status'],'answered')

    def test_wrong_signature_is_not_a_physical_damage_answer(self):
        m=image();m['media_observation']['signature']='other'
        state=qs.inspect([row('Телевизор',ident='job'),m])
        self.assertNotIn('reviewed_screen_cracks',state['screen_damage'])
        self.assertFalse(contact_facts.collect([m],known())['image_observations'])

    def test_new_enquiry_does_not_reuse_old_screen_photo(self):
        messages=[row('Телевизор',ident='old'),image(),row('Новая заявка: принтер не печатает',ident='new')]
        self.assertNotIn('reviewed_screen_cracks',qs.inspect(messages)['screen_damage'])
        self.assertFalse(contact_facts.collect(messages,known())['image_observations'])

    def test_another_tv_does_not_inherit_the_first_screen_cracks(self):
        messages=[row('Телевизор',ident='old'),image(),row('Теперь другой телевизор: нет звука',ident='new')]
        self.assertFalse(personal_media.current_tv_screen_crack_images(messages))
        self.assertNotIn('reviewed_screen_cracks',qs.inspect(messages)['screen_damage'])

    def test_quoted_or_staff_new_order_is_not_a_scope_reset(self):
        for message in [row('Новая заявка: принтер',role='operator'),row('Сосед написал «Новая заявка: принтер»')]:
            with self.subTest(message=message):
                self.assertEqual([m['id']for m in personal_media.current_tv_screen_crack_images([image(),message])],['photo'])

    def test_observed_cracks_require_operator_without_claiming_matrix_failure(self):
        out=assess([row('Телевизор, можно помочь?',ident='job'),image()])
        self.assertEqual(out['action'],'handoff');self.assertFalse(out.get('forced_reply'))
        self.assertIn('DOC-L0223',out['rule_ids'])
        self.assertNotIn('OWNER-TV-BANDS-20261017',out['rule_ids'])

    def test_negative_caption_cannot_erase_the_independent_photo_observation(self):
        m=image();m['body']='Экран не разбит'
        out=assess([row('Телевизор',ident='job'),m])
        self.assertEqual(out['action'],'handoff')
        self.assertIn('DOC-L0223',out['rule_ids'])

    def test_real_tv_photo_reply_condition_is_not_a_request_to_accept_repair(self):
        out=assess([row('Упал телевизор, не дает отправить фото, пока вы не ответите)',ident='upload')])
        self.assertEqual(out['action'],'question');self.assertEqual(out['forced_reply'],'Пришлите, пожалуйста, фото.')
        self.assertNotIn('crm_preparation',out);self.assertNotIn('visit_offer',out)

    def test_reply_wording_is_bound_to_photo_sending(self):
        for text in ['Ответьте, пожалуйста, чтобы я смог отправить фото',
                     'Фото не могу отправить, пока вы не ответите',
                     'Напишите мне что-нибудь, отправлю фото']:
            with self.subTest(text=text):self.assertEqual(assess([row(text)])['forced_reply'],'Пришлите, пожалуйста, фото.')

    def test_received_photo_does_not_restart_old_upload_request(self):
        messages=[row('Не могу отправить фото, пока вы не ответите',ident='upload'),
                  row('Вот фото, раньше не мог отправить, пока вы не ответите',ident='received',attachments=[{'kind':'image'}])]
        self.assertIsNone(policy._photo_upload_unblock(messages))

    def test_delivered_reply_does_not_make_a_new_unblock_request(self):
        messages=[row('Не могу отправить фото, пока вы не ответите',ident='upload'),
                  row('Здравствуйте',ident='staff',role='operator'),row('жду',ident='staff2',role='operator')]
        self.assertIsNotNone(policy.photo_reply_progress(messages,known(),{}))
        self.assertEqual(assess(messages)['action'],'wait')

    def test_quotes_hypotheses_roles_and_price_keep_their_own_scope(self):
        for text in ['Сосед написал «не могу отправить фото, пока вы не ответите»',
                     'Если не смогу отправить фото, пока вы не ответите?',
                     'Сколько стоит ремонт? Не могу отправить фото, пока вы не ответите']:
            with self.subTest(text=text):self.assertIsNone(policy._photo_upload_unblock([row(text)]))
        self.assertIsNone(policy._photo_upload_unblock([row('Не могу отправить фото, пока вы не ответите',role='operator')]))

    def test_vague_initial_question_asks_for_actual_missing_problem(self):
        for text in ['Добрый день, подскажите пожалуйста, это все, ничего не сделать?',
                     'Уже ничего нельзя сделать?', 'Ничего сделать нельзя?']:
            with self.subTest(text=text):
                out=assess([row(text)]);self.assertEqual(out['action'],'draft')
                self.assertEqual(out['next_question']['kind'],'problem')

    def test_vague_question_does_not_replace_a_known_damaged_tv(self):
        out=assess([row('Телевизор упал',ident='job'),row('Ничего не сделать?',ident='question')])
        self.assertEqual(out['action'],'handoff');self.assertNotIn('next_question',out)
        self.assertNotIn('next_question',assess([row('Мастер сказал: «Ничего не сделать?»')]))

    def test_source_and_territory_guards_still_precede_photo_reply(self):
        out=assess([row('Упал телевизор, не могу отправить фото, пока вы не ответите')],partner='999999')
        self.assertEqual(out['action'],'handoff');self.assertFalse(out.get('forced_reply'))


class TvPhotoReceipt200Tests(unittest.TestCase):
    setUp=media_fixture.PersonalMediaTests.setUp
    tearDown=media_fixture.PersonalMediaTests.tearDown
    call=media_fixture.PersonalMediaTests.call
    confirmation=media_fixture.PersonalMediaTests.confirmation

    def tv(self):
        self.ctx.update(dir='kp',itemTitle='Ремонт телевизоров',messages=[
            {'id':'1','direction':'in','body':'Телевизор упал, что можно сделать?'},
            {'id':'2','direction':'in','body':'','attachments':[{'kind':'image','media_id':'photo','url':'https://example.test/tv.jpg'}]}])

    def test_real_review_receipt_preserves_cracks_and_stays_operator_only(self):
        self.tv();approval=self.confirmation();approval['client_version']='2.8.16'
        out=self.call('personal_media_review',**approval,observations=dict(content_kind='product_photo',device_kind='tv',visible_symptom='screen_cracks'))
        self.assertTrue(out['ok']);fresh=self.call('preview')
        self.assertEqual(fresh['action'],'handoff');self.assertFalse(fresh['lead']['can_create_automatically'])
        self.assertEqual(fresh['facts']['image_observations'][0]['visible_symptom'],'screen_cracks')
        self.assertFalse(self.call('personal_media_review',**approval,observations=dict(content_kind='product_photo',device_kind='tv',visible_symptom='screen_cracks'))['ok'])

    def test_raw_browser_review_flags_cannot_forge_the_new_observation(self):
        self.tv();self.ctx['messages'][-1].update(media_reviewed=True,media_observation=dict(
            source='reviewed_image',content_kind='product_photo',device_kind='tv',visible_symptom='screen_cracks'))
        out=self.call('preview');self.assertTrue(out['media_review_required'])
        self.assertFalse(out['facts']['image_observations'])
