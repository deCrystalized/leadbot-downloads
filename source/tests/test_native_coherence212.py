"""Joint wire states constrain output shape, never the truth of model review."""
import copy
import unittest
import extension_assistant as ext


def valid(schema, value):
    """Evaluate the schema vocabulary used here; not a provider grammar emulator."""
    types={'object':lambda x:isinstance(x,dict),'string':lambda x:isinstance(x,str),
           'boolean':lambda x:type(x)is bool,'array':lambda x:isinstance(x,list),
           'integer':lambda x:type(x)is int}
    if 'type'in schema and not types[schema['type']](value):return False
    if 'enum'in schema and not any(type(value)is type(v)and value==v for v in schema['enum']):return False
    if isinstance(value,str)and not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',10**9):return False
    if isinstance(value,list):
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',10**9):return False
        if not all(valid(schema.get('items',{}),x)for x in value):return False
    if isinstance(value,dict):
        if not set(schema.get('required',[]))<=set(value):return False
        props=schema.get('properties',{})
        if schema.get('additionalProperties')is False and not set(value)<=set(props):return False
        if not all(valid(props[k],v)for k,v in value.items()if k in props):return False
    if 'anyOf'in schema and not any(valid(s,value)for s in schema['anyOf']):return False
    return True


def task():
    return dict(output_contract={},decision=dict(next_question=dict(question='Номер для связи подскажите?')),
                experience_context=dict(conversation_style=dict(source='server_bound_linguistic_options_not_model_understanding')))


def candidate(fits=True,reply='Номер для связи подскажите?',operator=False):
    return dict(context_review=dict(last_intent='Помощь с текущей задачей',latest_client_meaning='Клиент спрашивает о помощи.',
        selected_step_fits=fits,evidence_ids=['client'],note='Оцениваю вопрос независимо.'),reply=reply,needs_operator=operator)


class NativeCoherence212Tests(unittest.TestCase):
    def schema(self,value=None):return ext._structured_response_format(value or task())['schema']

    def test_complete_joint_state_truth_table(self):
        schema=self.schema()
        for fits in [True,False]:
            for operator in [True,False]:
                for reply in ['','Подскажите номер для связи?']:
                    with self.subTest(fits=fits,operator=operator,reply=reply):
                        self.assertEqual(valid(schema,candidate(fits,reply,operator)),
                            (fits and not operator and bool(reply))or(not fits and operator and not reply))

    def test_original_empty_positive_does_not_match_native_schema(self):
        self.assertFalse(valid(self.schema(),candidate(True,'',False)))

    def test_independent_veto_is_permitted_without_forcing_true(self):
        self.assertTrue(valid(self.schema(),candidate(False,'',True)))
        props=self.schema()['properties']
        self.assertNotIn('enum',props['context_review']['properties']['selected_step_fits'])
        self.assertNotIn('enum',props['needs_operator'])

    def test_fixed_reply_and_legacy_question_keep_exact_positive_and_empty_veto(self):
        for value,reply in [(dict(task(),fixed_reply='Обязательный текст.'),'Обязательный текст.'),
                            (dict(output_contract={},decision=task()['decision'],
                                  reply_field_scope='next_question_only_server_adds_required_text'),'Номер для связи подскажите?')]:
            schema=self.schema(value)
            self.assertTrue(valid(schema,candidate(True,reply,False)))
            self.assertFalse(valid(schema,candidate(True,'Подменённый вопрос?',False)))
            self.assertTrue(valid(schema,candidate(False,'',True)))

    def test_free_intent_meaning_evidence_and_note_remain_required(self):
        schema=self.schema();value=candidate()
        for key in ['last_intent','latest_client_meaning','evidence_ids','note']:
            changed=copy.deepcopy(value);changed['context_review'].pop(key)
            self.assertFalse(valid(schema,changed),key)
        value['context_review']['last_intent']='Самостоятельное точное понимание цели'
        self.assertTrue(valid(schema,value))

    def test_conditional_reviews_keep_source_link_and_cannot_be_omitted(self):
        value=task();value['mnc_callout_terms']={}
        # A populated real condition triggers the pre-existing source review.
        value['mnc_callout_terms']={'source_rule':'MNC'};schema=self.schema(value)
        current=candidate();self.assertFalse(valid(schema,current))
        proof={'callout_rub':0,'diagnostic_fee_quoted':False,'repair_included':False}
        current['context_review']['mnc_callout_review']=proof
        self.assertTrue(valid(schema,current))
        current['context_review']['mnc_callout_review']['repair_included']=True
        self.assertFalse(valid(schema,current))

    def test_non_boolean_flags_and_non_string_reply_never_match(self):
        for key,val in [('needs_operator','false'),('reply',None)]:
            current=candidate();current[key]=val;self.assertFalse(valid(self.schema(),current))
        current=candidate();current['context_review']['selected_step_fits']='true'
        self.assertFalse(valid(self.schema(),current))

    def test_native_format_only_does_not_mutate_task_or_add_receipts(self):
        current=task();before=copy.deepcopy(current);schema=self.schema(current)
        self.assertEqual(current,before)
        self.assertEqual(set(schema['properties']),{'context_review','reply','needs_operator'})
        self.assertEqual(set(schema['properties']['context_review']['properties']),
                         {'last_intent','latest_client_meaning','selected_step_fits','evidence_ids','note'})
        self.assertEqual(len(schema.get('anyOf',[])),2)
