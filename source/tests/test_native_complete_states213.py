"""Every native alternative must be sufficient without its outer schema."""
import copy
import unittest
import extension_assistant as ext
import test_native_coherence212 as base


class NativeCompleteStates213Tests(unittest.TestCase):
    def schema(self, task=None):
        return ext._structured_response_format(task or base.task())['schema']

    def test_each_alternative_is_a_complete_typed_closed_object(self):
        schema=self.schema()
        for branch in schema['anyOf']:
            self.assertEqual(branch['type'],'object')
            self.assertEqual(branch['required'],schema['required'])
            self.assertFalse(branch['additionalProperties'])
            self.assertEqual(set(branch['properties']),set(schema['properties']))
            review=branch['properties']['context_review']
            self.assertEqual(review['type'],'object');self.assertFalse(review['additionalProperties'])
            self.assertEqual(review['required'],schema['properties']['context_review']['required'])
            self.assertEqual(set(review['properties']),set(schema['properties']['context_review']['properties']))

    def test_standalone_positive_accepts_a_complete_nonempty_answer(self):
        positive,negative=self.schema()['anyOf'];value=base.candidate()
        self.assertTrue(base.valid(positive,value));self.assertFalse(base.valid(negative,value))
        self.assertFalse(base.valid(positive,base.candidate(True,'',False)))

    def test_standalone_veto_preserves_an_independently_justified_rejection(self):
        positive,negative=self.schema()['anyOf'];value=base.candidate(False,'',True)
        value['context_review']['note']='Предлагаемый шаг противоречит сообщению клиента.'
        self.assertTrue(base.valid(negative,value));self.assertFalse(base.valid(positive,value))
        self.assertFalse(base.valid(negative,base.candidate(False,'Любой ответ',True)))

    def test_actual212_missing_review_and_empty_positive_fails_each_alternative(self):
        original={'context_review':{'selected_step_fits':True},'reply':'','needs_operator':False}
        before=copy.deepcopy(original)
        for schema in [self.schema(),*self.schema()['anyOf']]:
            self.assertFalse(base.valid(schema,original))
        self.assertEqual(original,before)

    def test_all_joint_states_match_whole_schema_and_exactly_one_full_alternative(self):
        schema=self.schema()
        for fits in [True,False]:
            for operator in [True,False]:
                for reply in ['','Подскажите номер для связи?']:
                    value=base.candidate(fits,reply,operator)
                    expected=(fits and not operator and bool(reply))or(not fits and operator and not reply)
                    self.assertEqual(base.valid(schema,value),expected)
                    self.assertEqual(sum(base.valid(b,value)for b in schema['anyOf']),int(expected))

    def test_every_free_review_field_is_required_in_each_standalone_alternative(self):
        for branch,value in zip(self.schema()['anyOf'],[base.candidate(),base.candidate(False,'',True)]):
            for key in ['last_intent','latest_client_meaning','evidence_ids','note']:
                changed=copy.deepcopy(value);changed['context_review'].pop(key)
                self.assertFalse(base.valid(branch,changed),key)

    def test_free_meanings_are_not_server_fixed_or_enum_forced(self):
        for branch in self.schema()['anyOf']:
            fields=branch['properties']['context_review']['properties']
            for name in ['last_intent','latest_client_meaning','note']:
                self.assertEqual(fields[name]['type'],'string');self.assertNotIn('enum',fields[name])
        self.assertNotIn('enum',self.schema()['properties']['context_review']['properties']['selected_step_fits'])

    def test_fixed_positive_enum_excludes_empty_and_veto_is_exactly_empty(self):
        value=base.task();value['fixed_reply']='Предварительно проверенный обязательный ответ.'
        positive,negative=self.schema(value)['anyOf']
        self.assertEqual(positive['properties']['reply']['enum'],[value['fixed_reply']])
        self.assertEqual(positive['properties']['reply']['minLength'],1)
        self.assertEqual(negative['properties']['reply']['enum'],[''])
        self.assertEqual(negative['properties']['reply']['maxLength'],0)

    def test_legacy_literal_question_alternative_remains_exact(self):
        value={'output_contract':{},'decision':base.task()['decision'],
               'reply_field_scope':'next_question_only_server_adds_required_text'}
        positive,negative=self.schema(value)['anyOf']
        self.assertEqual(positive['properties']['reply']['enum'],['Номер для связи подскажите?'])
        self.assertTrue(base.valid(negative,base.candidate(False,'',True)))

    def test_conditional_source_reviews_are_complete_and_required_in_both_states(self):
        for condition in ['mnc_callout_terms','diagnostic_only_terms']:
            value=base.task();value[condition]={'source_rule':'synthetic'}
            schema=self.schema(value)
            for branch in schema['anyOf']:
                fields=branch['properties']['context_review']
                self.assertEqual(fields['required'],schema['properties']['context_review']['required'])
                for k,v in schema['properties']['context_review']['properties'].items():
                    if k!='selected_step_fits':self.assertEqual(fields['properties'][k],v)
                current=base.candidate()if branch['properties']['needs_operator']['enum']==[False]else base.candidate(False,'',True)
                self.assertFalse(base.valid(branch,current))

    def test_branch_mutation_cannot_change_outer_or_the_other_verdict(self):
        schema=self.schema();before=copy.deepcopy(schema)
        schema['anyOf'][0]['properties']['context_review']['properties']['note']['maxLength']=1
        self.assertEqual(schema['properties'],before['properties'])
        self.assertEqual(schema['anyOf'][1],before['anyOf'][1])

    def test_generation_does_not_mutate_task_or_add_a_new_receipt(self):
        value=base.task();before=copy.deepcopy(value);schema=self.schema(value)
        self.assertEqual(value,before)
        self.assertEqual(set(schema['properties']),{'context_review','reply','needs_operator'})
        self.assertEqual(set(schema['properties']['context_review']['properties']),
                         {'last_intent','latest_client_meaning','selected_step_fits','evidence_ids','note'})

    def test_standalone_alternatives_reject_wrong_types_and_unknown_fields(self):
        for branch,value in zip(self.schema()['anyOf'],[base.candidate(),base.candidate(False,'',True)]):
            for key,bad in [('reply',None),('needs_operator','false')]:
                changed=copy.deepcopy(value);changed[key]=bad;self.assertFalse(base.valid(branch,changed))
            changed=copy.deepcopy(value);changed['context_review']['invented']='extra'
            self.assertFalse(base.valid(branch,changed))

    def test_positive_natural_wording_is_free_while_needs_operator_is_bound(self):
        schema=self.schema();positive=schema['anyOf'][0]
        self.assertNotIn('enum',positive['properties']['reply'])
        for text in ['Какой номер телефона оставить для связи?','Подскажите, пожалуйста, номер для связи.']:
            self.assertTrue(base.valid(positive,base.candidate(True,text,False)))
            self.assertFalse(base.valid(positive,base.candidate(True,text,True)))
