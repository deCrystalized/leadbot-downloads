import copy
import json
import unittest
import test_neural_auto203 as helpers


class ProviderFailure207Tests(unittest.TestCase):
    setUp=helpers.NeuralAuto203Tests.setUp
    call=helpers.NeuralAuto203Tests.call
    enable=helpers.NeuralAuto203Tests.enable

    def prepare(self,mode='neural_review'):
        self.ctx['convId']+='x'
        if mode=='neural_auto':self.enable()
        out,status=self.call('preview',wording_mode=mode)
        self.assertEqual(status,200);self.assertTrue(out['pending_model'])
        return out

    def finish_failure(self,candidate=None,failure='transport',mode='neural_review',**extra):
        out=self.prepare(mode)
        candidate={} if candidate is None else candidate
        before=copy.deepcopy(candidate)
        result,status=self.call('finalize',request_id=out['request_id'],revision=out['revision'],candidate=candidate,model_failure=failure,**extra)
        self.assertEqual(status,200);self.assertEqual(candidate,before)
        self.assertEqual(result['reply'],'');self.assertTrue(result['needs_operator']);self.assertFalse(result['auto_enabled'])
        return result

    def test_absent_transport_candidate_is_not_a_model_or_template_answer(self):
        for mode in ('neural_review','neural_auto'):
            out=self.finish_failure(mode=mode)
            self.assertEqual(out['response_source'],'provider_error');self.assertEqual(out['code'],'model_unavailable')
            self.assertEqual(out['model_status'],'transport');self.assertIn('missing_context_review',out['validation'])
            self.assertNotIn('model_context_mismatch',out['validation']);self.assertNotIn('Модель запросила',out['reason'])

    def test_safe_empty_root_handoff_preserves_technical_failure(self):
        out=self.finish_failure(dict(reply='',needs_operator=True))
        self.assertEqual(out['response_source'],'provider_error');self.assertEqual(out['code'],'model_unavailable')

    def test_format_is_distinct_from_transport_or_semantic_veto(self):
        out=self.finish_failure(failure='format')
        self.assertEqual(out['response_source'],'model_format_error');self.assertEqual(out['code'],'model_format_error')
        self.assertEqual(out['model_status'],'format');self.assertIn('missing_context_review',out['validation'])

    def test_nonempty_candidate_and_transport_flag_are_a_control_conflict(self):
        out=self.finish_failure(dict(reply='Марку и модель подскажите?',needs_operator=False))
        self.assertEqual(out['code'],'model_contract_conflict');self.assertEqual(out['response_source'],'control_error')
        self.assertIn('candidate_with_model_failure',out['validation'])

    def test_semantic_handoff_and_transport_flag_are_not_relabelled_as_absent_model(self):
        out=self.finish_failure(dict(reply='',needs_operator=True,context_review=dict(last_intent='Починить компьютер')))
        self.assertEqual(out['code'],'model_contract_conflict')

    def test_safe_error_metadata_is_projected_without_secret_or_message(self):
        out=self.finish_failure(model_error=dict(provider='gigachat',status=429,stage='oauth',category='rate_limited',retry_after_seconds=12,secret='Bearer hidden',message='client-private'))
        self.assertEqual(out['model_error'],dict(provider='gigachat',status=429,stage='oauth',category='rate_limited',retry_after_seconds=12))
        self.assertNotIn('hidden',json.dumps(out));self.assertNotIn('client-private',json.dumps(out))

    def test_untrusted_unknown_error_fields_are_never_echoed(self):
        out=self.finish_failure(model_error=dict(provider='gigachat',status=None,stage='https://private',category='network_timeout',retry_after_seconds=None))
        self.assertNotIn('private',json.dumps(out));self.assertIsNone(out.get('model_error'))

    def test_fixed_price_failure_remains_empty_and_never_a_price_approval(self):
        self.ctx.update(itemTitle='Ремонт принтеров',messages=[dict(id='in-1',direction='in',body='Нужна только диагностика принтера, без ремонта.')])
        out=self.finish_failure();self.assertEqual(out['response_source'],'provider_error');self.assertFalse(out['reply'])

    def test_completed_failure_cannot_be_replaced_by_a_later_candidate(self):
        prepared=self.prepare();args=dict(request_id=prepared['request_id'],revision=prepared['revision'])
        first,_=self.call('finalize',candidate={},model_failure='transport',**args)
        second,_=self.call('finalize',candidate=dict(reply='Починю бесплатно.',needs_operator=False),**args)
        self.assertTrue(second['cached']);self.assertEqual(second['reply'],'');self.assertEqual(second['response_source'],'provider_error')

    def test_valid_model_response_is_unchanged(self):
        prepared=self.prepare();t=json.loads(prepared['model_task']['task'])
        candidate=dict(reply=t['decision']['next_question']['question'],needs_operator=False,context_review=dict(last_intent='Починить компьютер.',latest_client_meaning='Компьютер не включается, город Чита.',selected_step_fits=True,evidence_ids=['in-1'],note='Модель ещё не указана.'))
        result,_=self.call('finalize',request_id=prepared['request_id'],revision=prepared['revision'],candidate=candidate)
        self.assertEqual(result['validation'],[]);self.assertEqual(result['response_source'],'model');self.assertFalse(result['needs_operator'])

    def test_genuine_semantic_veto_is_still_a_model_verdict(self):
        prepared=self.prepare();candidate=dict(reply='',needs_operator=True,context_review=dict(last_intent='Починить компьютер.',latest_client_meaning='Компьютер не включается.',selected_step_fits=False,evidence_ids=['in-1'],note='Нужна проверка уместности шага.'))
        result,_=self.call('finalize',request_id=prepared['request_id'],revision=prepared['revision'],candidate=candidate)
        self.assertEqual(result['response_source'],'model');self.assertEqual(result['context_review_status'],'provided');self.assertIn('model_context_mismatch',result['validation'])

    def test_technical_failure_cannot_reach_an_automatic_reply_step(self):
        self.body['mine_count']=0
        self.ctx.update(assigneeId='george',assignmentKnown=True,conversationStatus='in_progress',botActive=False,hasTransfer=False,channelAssigned=True)
        self.ctx['messages'].insert(0,dict(id='staff-greeting',direction='out',sender_type='operator',body='Здравствуйте!',delivery_status='delivered'))
        out=self.finish_failure(mode='neural_auto')
        plan,_=self.call('personal_plan')
        grant,_=self.call('personal_authorize',operation=dict(kind='reply',operation_id=plan['operation_id'],revision=plan['revision'],draft_id=out['draft_id']))
        self.assertFalse(grant['ok']);self.assertNotIn('permit',grant)
