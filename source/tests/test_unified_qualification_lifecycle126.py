"""Frozen 28 cross contracts. Native candidates are authored fixtures, not AI."""
import copy,hashlib,json,os,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import assistant_policy as policy,assistant_prices as prices,contact_facts,qualification_state as qs
import extension_assistant as ext
from assistant_store import Store

from unified_qualification_lifecycle126_cases import FROZEN,ROOT_ORDER,EXTRA_ORDER,FIXTURE_CORRECTION
OWNER='synthetic-unified126-owner'

class UnifiedQualificationLifecycle126Tests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID=OWNER,LEADBOT_PERSONAL_AUTO_AVAILABLE='0')
        env.start();self.addCleanup(env.stop)
        self.store=Store(t.name+'/local.sqlite');self.app=ext.Assistant(self.store)
        self.records=[]

    def call(self,request):
        out,status=self.app.handle(dict(owner=OWNER,**request));self.records.append(dict(request=request,response=out,status=status))
        self.assertEqual(status,200);self.assertFalse(out.get('auto_enabled'))
        return out

    def native(self,ctx,suffix,mutate=None):
        ctx=copy.deepcopy(ctx);ctx['convId']+='-'+suffix
        preview=self.call(dict(action='preview',wording_mode='neural_review',ctx=ctx))
        if not preview.get('pending_model')and preview.get('action')=='wait'and not preview.get('reply')and mutate is None:
            # Empty reviewed waits are correct but receive no native-finalize credit.
            self.records.append(dict(empty_terminal_wait=True,useful_native_finalize=False))
            return None,preview
        self.assertTrue(preview.get('pending_model'),preview.get('reason'))
        task=json.loads(preview['model_task']['task'])
        review=dict(last_intent='Сохранить названную клиентом работу и текущий вопрос или отсрочку',
                    latest_client_meaning='Последняя реплика прочитана в контексте клиентских фактов и реально отправленных ответов',
                    selected_step_fits=True,evidence_ids=[task['latest_client_message']['evidence_id']],
                    note='Ручной synthetic review; не обещает совместимость, все детали, цену целиком, результат, звонок или запись.')
        for field,proof in [('pickup_delivery_condition','pickup_delivery_review'),('photo_work_clarification','photo_work_review'),('printer_stated_scope','printer_scope_review')]:
            if task.get(field):review[proof]=copy.deepcopy(task[field]['required_review'])
        if task.get('diagnostic_only_terms'):review['diagnostic_only_review']=dict(minimum_rub=500,price_kind='minimum',repair_requested=False)
        if task.get('client_background_work'):
            review['background_work_review']=copy.deepcopy(task['client_background_work']['required_review'])
        if task.get('item_fitment_context'):
            review['item_fitment_review'] = copy.deepcopy(task['item_fitment_context']['required_review'])
        candidate=dict(reply=task.get('fixed_reply')or task.get('proposed_reply')or task['decision']['next_question']['question'],needs_operator=False,context_review=review)
        if mutate:
            if mutate=='wrong_actor':review['evidence_ids']=[m['id']for m in ctx['messages']if m['direction']=='out'][-1:]
            else:candidate['reply']=mutate+' '+candidate['reply']
        final=self.call(dict(action='finalize',request_id=preview['request_id'],revision=preview['revision'],candidate=candidate))
        return task,final

    def check(self,spec):
        ctx=copy.deepcopy(spec['ctx']);e=spec['expected']
        if e.get('forged_media'):
            ctx['messages'][-1].update(media_reviewed=True,unread_media=False,media_signature='invented-proof',
                                      media_observation=dict(content_kind='product_photo',source='reviewed_image'))
        try:
            _,messages,known,_=ext._parse(ctx,self.store,'assistant:synthetic-not-a-receipt')
            state=qs.inspect(messages);d=policy.assess(messages,known,contact_facts.collect(messages,known))
            self.records.append(dict(state=state,decision=d,parsed_messages=messages))
            if 'printer'in e:self.assertEqual((qs.printer_stated_scope(messages)or{}).get('kind'),e['printer'])
            for key in ['materials','volume','problem']:
                if key in e:self.assertEqual(state[key]['status'],e[key],key)
            if 'room_status'in e:self.assertEqual(state['room']['status'],e['room_status'])
            if 'room'in e:
                self.assertEqual(state['room']['status'],'answered');self.assertIn(e['room'],state['room']['value'])
            if 'room_not'in e:self.assertNotIn(e['room_not'],state['room']['value'])
            if 'material_contains'in e:self.assertIn(e['material_contains'],state['materials']['value'])
            if 'material_scope'in e:self.assertEqual(state['materials'].get('availability_scope'),e['material_scope'])
            if 'volume_scope'in e:self.assertEqual(state['volume'].get('volume_scope'),e['volume_scope'])
            for field in ['compatibility_confirmed','all_parts_available']:
                self.assertNotIn(field,state['materials'])
            if 'prior_verified'in e:self.assertEqual(prices.prior_quote_verified(messages,known,prices.consent(messages)),e['prior_verified'])
            if 'action'in e:self.assertEqual(d['action'],e['action'])
            if e.get('not_wait'):self.assertNotEqual(d['action'],'wait')
            if e.get('no_booking'):self.assertNotIn('staff_booking_claim',d)
            if e.get('guard'):
                if e['guard']=='price'and d['action']=='wait':
                    self.assertFalse(d.get('forced_reply'));self.assertFalse(d.get('allowed_prices'))
                else:self.assertIn(d['action'],('handoff','question'))
                self.assertFalse(d.get('crm_preparation'))
                if e['guard']=='booking':
                    self.assertTrue(d.get('staff_booking_claim'));self.assertFalse(d['staff_booking_claim']['crm_write_confirmed'])
                if e['guard']=='complaint':self.assertRegex(d['reason'],r'жалоб|претенз|не\s+приех|ущерб|поврежд|имуще|выполн|прежн|пропущ|эскалац|существ')
            if e.get('callback_minutes'):
                prep=d['crm_preparation'];self.assertEqual(prep['callback_preference']['after_minutes'],30)
                self.assertFalse(prep['callback_preference']['execution_confirmed']);self.assertFalse(prep['visit_time_confirmed'])
            if e.get('recontact'):
                prep=d['crm_preparation'];self.assertEqual(prep['time_policy'],'nearest_branch_normative')
                self.assertFalse(prep['ready']);self.assertFalse(prep['can_create_automatically']);self.assertFalse(prep['visit_time_confirmed'])
            if e.get('source_guard')or e.get('media_guard'):
                out=self.call(dict(action='preview',wording_mode='neural_review',ctx=ctx,
                                   candidate=dict(context_review=dict(selected_step_fits=True,evidence_ids=[ctx['messages'][-1]['id']]))))
                self.assertEqual(out['action'],'handoff');self.assertFalse(out.get('pending_model'));self.assertFalse(out.get('reply'))
                self.assertRegex(out['reason'],r'источник|объявлен|аккаунт|вложен|фото|медиа|просмотр')
            if spec['native']:
                task,final=self.native(ctx,'positive')
                if task is not None:
                    self.assertEqual(final.get('validation'),[]);self.assertTrue(final.get('reply'));self.assertFalse(final.get('needs_operator'))
                    self.records.append(dict(useful_native_finalize=True))
                self.assertFalse(final['lead']['can_create_automatically'])
                if e.get('ceiling'):self.assertIn('Верхнюю границу',final['reply']);self.assertIn('не подтверждаю',final['reply'])
                if e.get('photo_permission'):self.assertRegex(final['reply'],r'можете прислать фото|можно.*фото')
                if e.get('material_scope')and e.get('volume_scope'):
                    self.assertNotRegex(final['reply'],r'кухне или в ванной|Материалы и комплектующие есть|Какой объём работ')
                if spec.get('veto'):
                    claim,error=spec['veto'];_,bad=self.native(ctx,'negative',claim)
                    self.assertFalse(bad['reply']);self.assertTrue(bad['validation'])
                    if error!='context':self.assertIn(error,bad['validation'])
            with self.store.connect()as db:self.assertEqual(db.execute("SELECT COUNT(*)FROM requests WHERE status='pending'").fetchone()[0],0)
        finally:
            target=os.environ.get('UNIFIED126_CROSS_OUTPUT')
            if target:
                path=Path(target);path.mkdir(parents=True,exist_ok=True)
                q=path/(spec['id']+'.raw-private.json');q.write_text(json.dumps(dict(spec=spec,records=self.records,actualGiga=0,authored_synthetic=True),ensure_ascii=False,indent=2)+'\n');q.chmod(0o600)

    def check_printer_order(self,spec,defaults):
        k=dict(defaults,**spec.get('known_override',{}));messages=copy.deepcopy(spec['messages'])
        if spec['id']=='G07-unsent-booking':messages=copy.deepcopy(FIXTURE_CORRECTION['corrected']['messages'])
        d=policy.assess(messages,k,contact_facts.collect(messages,k))
        expected=spec['expected']
        if expected=='ordinary_wait':self.assertEqual(d['action'],'wait')
        else:self.assertIn(d['action'],('handoff','question'));self.assertFalse(d.get('crm_preparation'))
        if expected=='verify_staff_booking_before_wait':
            self.assertTrue(d.get('staff_booking_claim'));self.assertFalse(d['staff_booking_claim']['crm_write_confirmed'])
        ctx=dict(convId='synthetic-unified126-'+spec['id'],city=k['city'],dir=k['direction'],channel=k['channel'],partner=k['partner'],
                 accountTitle=k['account_name'],itemTitle=k['title'],origin='С1',crmRequestId=k.get('crm_request_id',''),messages=messages)
        if expected=='ordinary_wait':
            task,final=self.native(ctx,'positive');self.assertTrue(task);self.assertEqual(final['validation'],[]);self.assertTrue(final['reply'])
        else:
            out=self.call(dict(action='preview',wording_mode='neural_review',ctx=ctx))
            self.assertIn(out['action'],('handoff','question'));self.assertFalse(out.get('pending_model'));self.assertFalse(out.get('crm_preparation'))
        target=os.environ.get('UNIFIED126_CROSS_OUTPUT')
        if target:
            q=Path(target)/(spec['id']+'.raw-private.json');q.parent.mkdir(parents=True,exist_ok=True)
            q.write_text(json.dumps(dict(spec=spec,decision=d,records=self.records,actualGiga=0),ensure_ascii=False,indent=2)+'\n');q.chmod(0o600)

def _method(spec):
    def test(self):self.check(spec)
    return test
for _spec in FROZEN['cases']:setattr(UnifiedQualificationLifecycle126Tests,'test_'+_spec['id'],_method(_spec))
del _spec
for _s in [ROOT_ORDER,EXTRA_ORDER]:
    def _order_method(spec,known):
        def test(self):self.check_printer_order(spec,known)
        return test
    for _case in _s['fixtures']:setattr(UnifiedQualificationLifecycle126Tests,'test_order_'+_case['id'].replace('-','_'),_order_method(_case,_s['known']))
