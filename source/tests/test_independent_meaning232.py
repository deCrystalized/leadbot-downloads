"""Research meaning is free prose; legacy literals remain source hints only."""
import copy
import json
import unittest
import research_proposals as proposals
from assistant_store import digest
import test_client_contact142 as fixture


class IndependentMeaning232Tests(unittest.TestCase):
    preview=fixture.ClientContact142Tests.preview
    candidate=fixture.ClientContact142Tests.candidate

    def payload(self):
        out,task,_=self.preview()
        self.scope='assistant:'+digest('contact142')
        _,payload=self.app.store.request(self.scope,out['request_id'])
        return out,task,payload

    def test_research_schema_frees_meaning_in_all_branches_without_changing_legacy_schema(self):
        out,task,payload=self.payload();original=copy.deepcopy(payload)
        contract=proposals.contract(payload)
        for schema in [contract['schema'],*contract['schema']['anyOf']]:
            self.assertNotIn('enum',schema['properties']['context_review']['properties']['latest_client_meaning'])
        self.assertNotIn('fixed_latest_client_meaning',contract['task']['output_contract'])
        observation=contract['task']['output_contract']['server_latest_client_observation']
        self.assertFalse(observation['mandatory_copy'])
        self.assertEqual(observation['text'],task['output_contract']['fixed_latest_client_meaning'])
        self.assertEqual(payload,original)
        self.assertIn('enum',out['model_task']['response_format']['schema']['properties']['context_review']['properties']['latest_client_meaning'])

    def test_original_free_meaning_survives_real_native_validation_without_repair(self):
        out,task,payload=self.payload();candidate=self.candidate(task)
        meaning='Клиент сообщает адрес, номер телефона и имя для обращения по навеске гардины.'
        candidate['context_review']['latest_client_meaning']=meaning;original=copy.deepcopy(candidate)
        result=self.app.finalize(self.scope,dict(request_id=out['request_id'],revision=out['revision'],candidate=candidate),research_proposal=proposals.build(payload))
        self.assertEqual(result['validation'],[],result)
        self.assertEqual(result['context_review']['latest_client_meaning'],meaning)
        self.assertEqual(candidate,original)

    def test_free_meaning_cannot_reverse_who_supplied_the_phone(self):
        out,task,payload=self.payload();candidate=self.candidate(task)
        candidate['context_review']['latest_client_meaning']='Клиент просит наш номер телефона.'
        result=self.app.finalize(self.scope,dict(request_id=out['request_id'],revision=out['revision'],candidate=candidate),research_proposal=proposals.build(payload))
        self.assertTrue(result['validation']);self.assertFalse(result['reply'])


if __name__=='__main__':unittest.main()
