"""Public synthetic media receipts; no real history, files or operator grants."""
import copy,json,os,tempfile,time,unittest
from unittest.mock import patch
import assistant_policy as policy
import personal_media
from assistant_store import Store,digest
from extension_assistant import Assistant


class PhotoWorkClarificationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='owner',LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start();self.addCleanup(env.stop)
        self.store=Store(tmp.name+'/db');self.app=Assistant(self.store);self.serial=0
    def context(self,body='',prior=None):
        self.serial+=1
        data=[dict(id='hello',direction='in',sender_type='client',body='Здравствуйте')]
        if prior:data.append(dict(id='staff',direction='out',sender_type='operator',body=prior))
        data.append(dict(id='image',direction='in',sender_type='client',body=body,
                         attachments=[dict(id='synthetic-photo',type='image',version='1')]))
        return dict(convId='synthetic-photo-work-'+str(self.serial),city='Коломна',dir='mnc',channel='avito',partner='7',
                    accountTitle='Учебный мастер',origin='С85',itemTitle='Услуги электрика',messages=data)
    def preview(self,ctx):
        result,status=self.app.handle(dict(owner='owner',action='preview',wording_mode='neural_review',ctx=ctx))
        self.assertEqual(status,200);self.assertFalse(result['auto_enabled']);return result
    def receipt(self,ctx,*,wrong=None,observations=None):
        first=self.preview(ctx);pending=first['media_review_required'];self.assertTrue(pending)
        for row in pending:
            with self.store.connect() as db:
                personal_media.schema(db)
                db.execute('INSERT INTO personal_media_reviews (scope,chat,message_id,signature,policy,operator,reviewed,observations) VALUES (?,?,?,?,?,?,?,?)',
                  ('assistant:'+digest('owner'),ctx['convId'],row['message_id'] if wrong!='message' else 'wrong',row['signature'],
                   policy.VERSION if wrong!='policy' else 'old-policy','synthetic-test-review',time.time(),json.dumps(observations if observations is not None else {'content_kind':'product_photo'})))
        return self.preview(ctx)
    def candidate(self,preview):
        self.assertTrue(preview.get('pending_model'),preview.get('reason'))
        task=json.loads(preview['model_task']['task']);photo=task['photo_work_clarification']
        c=dict(reply='Спасибо за фото. Что требуется сделать?',needs_operator=False,context_review=dict(
            last_intent='Требуемая работа пока не указана',latest_client_meaning='Клиент прислал фото без указания желаемого действия',
            selected_step_fits=True,evidence_ids=['image'],note='Ручной synthetic review: фото не доказывает диагноз или объём работ.',
            photo_work_review=copy.deepcopy(photo['required_review'])))
        if task.get('latest_visual_message_context'):
            c['context_review']['latest_client_meaning'] = task['output_contract']['fixed_latest_client_meaning']
        return task,c
    def finish(self,preview,c):
        out,status=self.app.handle(dict(owner='owner',action='finalize',request_id=preview['request_id'],revision=preview['revision'],candidate=c))
        self.assertEqual(status,200);self.assertFalse(out['auto_enabled']);return out
    def test_exact_reviewed_photo_gets_useful_work_question(self):
        preview=self.receipt(self.context());task,c=self.candidate(preview);out=self.finish(preview,c)
        self.assertEqual(out['validation'],[]);self.assertFalse(out['needs_operator'])
        self.assertIn('Что требуется сделать?',out['reply']);self.assertIn('Спасибо за фото.',out['reply'])
        self.assertEqual(task['service_constraints']['status'],'unknown')
        self.assertNotIn('согласован',out['reply'])
    def test_object_noun_does_not_order_electrical_work(self):
        preview=self.receipt(self.context('Проводка'));task,c=self.candidate(preview);out=self.finish(preview,c)
        self.assertEqual(out['validation'],[]);self.assertNotIn('щиток',out['reply'])
    def test_staff_proposal_does_not_become_client_request(self):
        preview=self.receipt(self.context(prior='Поменяем всю проводку и отделку.'));task,c=self.candidate(preview)
        out=self.finish(preview,c);self.assertEqual(out['validation'],[])
        self.assertEqual(task['photo_work_clarification']['required_review']['requested_action'],'unspecified')
    def test_named_operation_keeps_panel_question(self):
        preview=self.receipt(self.context('Нужно поменять провода и собрать в распаячную коробку'))
        task=json.loads(preview['model_task']['task']);self.assertNotIn('photo_work_clarification',task)
        self.assertEqual(task['decision']['next_question']['question'],'Где расположен щиток или автомат?')
    def test_capability_and_materials125_are_preserved(self):
        ctx=self.context('Нужно поменять провода и собрать в распаячную коробку')
        ctx['messages'].append(dict(id='capability',direction='in',sender_type='client',body='Возьмётесь?'))
        preview=self.receipt(ctx);task=json.loads(preview['model_task']['task'])
        self.assertIn('Да, помогу.',task['proposed_reply']);self.assertNotIn('По материалам',task['proposed_reply'])
        self.assertNotIn('photo_work_clarification',task)
    def test_unreviewed_photo_stays_media_review(self):
        out=self.preview(self.context());self.assertTrue(out['media_review_required']);self.assertFalse(out.get('pending_model'))
    def test_changed_attachment_invalidates_receipt(self):
        ctx=self.context();ready=self.receipt(ctx);task,c=self.candidate(ready);self.finish(ready,c)
        ctx['messages'][-1]['attachments'][0]['version']='2'
        out=self.preview(ctx);self.assertTrue(out['media_review_required']);self.assertFalse(out.get('pending_model'))
    def test_wrong_message_or_policy_cannot_mark_media_reviewed(self):
        for wrong in ['message','policy']:
            ctx=self.context();out=self.receipt(ctx,wrong=wrong)
            self.assertTrue(out['media_review_required']);self.assertFalse(out.get('pending_model'))
    def test_raw_media_review_fields_cannot_bypass_guard(self):
        ctx=self.context();ctx['messages'][-1].update(media_reviewed=True,unread_media=False,media_observation={'content_kind':'product_photo'})
        out=self.preview(ctx);self.assertTrue(out['media_review_required']);self.assertFalse(out.get('pending_model'))
    def test_source_actor_admission_or_future_proof_mismatch_is_rejected(self):
        bad=[('requested_action','replace_wiring'),('request_actor','staff_requested_repair'),('service_admission','accepted'),
             ('source_rule','DOC-L0308'),('future_messages_used',True),('future_messages_used',0),('evidence_id','staff')]
        for field,value in bad:
            preview=self.receipt(self.context());task,c=self.candidate(preview);c['context_review']['photo_work_review'][field]=value
            out=self.finish(preview,c);self.assertFalse(out['reply']);self.assertIn('photo_work_review_mismatch',out['validation'])
    def test_future_work_cannot_be_invented_in_context_review(self):
        for field in ['last_intent','latest_client_meaning','note']:
            preview=self.receipt(self.context());task,c=self.candidate(preview)
            c['context_review'][field]='Клиент просит поменять провода и собрать в распаячную коробку.'
            out=self.finish(preview,c);self.assertFalse(out['reply']);self.assertIn('photo_unstated_work_or_diagnosis',out['validation'])
    def test_uncertainty_does_not_launder_following_work_assertion(self):
        preview=self.receipt(self.context());task,c=self.candidate(preview)
        c['context_review']['note']='Фото не доказывает диагноз, клиент просит заменить всю проводку.'
        out=self.finish(preview,c);self.assertFalse(out['reply']);self.assertIn('photo_unstated_work_or_diagnosis',out['validation'])
    def test_panel_materials_or_phone_cannot_replace_unknown_work_question(self):
        for reply in ['Где расположен щиток или автомат?','Материалы есть?','Номер для связи подскажите?']:
            preview=self.receipt(self.context());task,c=self.candidate(preview);c['reply']=reply
            out=self.finish(preview,c);self.assertFalse(out['reply']);self.assertIn('required_question_missing',out['validation'])
    def test_promises_or_diagnosis_are_rejected_with_correct_question(self):
        bad=['Поменяю всю проводку.','Это высоковольтное напряжение.','Причина — короткое замыкание.',
             'Привезу все материалы.','Приеду завтра.','Точно всё починю за один визит.']
        for claim in bad:
            preview=self.receipt(self.context());task,c=self.candidate(preview);c['reply']=claim+' Что требуется сделать?'
            out=self.finish(preview,c);self.assertFalse(out['reply']);self.assertTrue(out['validation'])
    def test_specialized_media_reasoning_is_not_reclassified(self):
        preview=self.receipt(self.context(),observations={'content_kind':'device_message','error_system':'windows','error_code':'0X80070005'})
        if preview.get('model_task'):
            self.assertNotIn('photo_work_clarification',json.loads(preview['model_task']['task']))
    def test_wire_schema_has_strict_unknown_action_proof(self):
        preview=self.receipt(self.context());task,c=self.candidate(preview)
        properties=preview['model_task']['response_format']['schema']['properties']['context_review']['properties']['photo_work_review']
        self.assertFalse(properties['additionalProperties']);self.assertEqual(properties['properties']['future_messages_used']['enum'],[False])
        self.assertEqual(properties['properties']['requested_action']['enum'],['unspecified'])
    def test_ambiguous_evidence_id_cannot_create_model_task(self):
        ctx=self.context(prior='Здравствуйте');ctx['messages'][-2]['id']='image'
        out=self.receipt(ctx);self.assertFalse(out.get('pending_model'));self.assertTrue(out['needs_operator'])
    def test_explicit_high_voltage_stays_restricted(self):
        out=self.receipt(self.context('Нужно заменить высоковольтный трансформатор на столбе'))
        self.assertEqual(out['action'],'handoff');self.assertFalse(out.get('pending_model'))

if __name__=='__main__':unittest.main()
