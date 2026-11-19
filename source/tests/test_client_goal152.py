"""The service's next qualification question is not the client's goal."""
import json,os,tempfile,unittest
from unittest.mock import patch
import test_dialogue_context150 as fixture
import extension_assistant as ext
from assistant_store import Store


class ClientGoal152Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,LEADBOT_PERSONAL_OWNER_ID='synthetic152',LEADBOT_PERSONAL_AUTO_AVAILABLE='0');env.start();self.addCleanup(env.stop)
        h=fixture.cabinet()+[fixture.row('Подсоединить раковину, надо прорезь в столешнице сделать',mid='scope'),
                            fixture.row('Какой материал столешницы?','out','materialq'),
                            fixture.row('Если сегодня не получается, давайте на другой день',mid='alternative')]
        a=ext.Assistant(Store(tmp.name+'/db'));o,status=a.handle(dict(owner='synthetic152',action='preview',wording_mode='neural_review',ctx=dict(convId='synthetic152-'+self.id().split('.')[-1],city='Томск',dir='mnc',channel='avito',partner='7',origin='С1',accountTitle='Учебный МНЧ',itemTitle='Сборка мебели',messages=h)))
        self.assertEqual(status,200);self.assertFalse(o['auto_enabled']);self.assertFalse(o['lead']['can_create_automatically']);self.out=o;self.task=json.loads(o['model_task']['task'])
    def candidate(self,intent):
        return dict(reply=self.task['proposed_reply'],needs_operator=False,context_review=dict(last_intent=intent,latest_client_meaning='Клиент допускает другой день, если сегодня не получится',selected_step_fits=True,evidence_ids=[self.task['latest_client_message']['evidence_id']],note='Материал ещё неизвестен; уточняющий вопрос не обещает конкретную дату.'))
    def test_native_goal_description_separates_service_question_roles(self):
        t=self.task;self.assertEqual(t['decision']['next_question']['kind'],'countertop_material');self.assertFalse(t['client_goal_boundary']['service_question_is_client_goal']);s=self.out['model_task']['response_format']['schema']['properties']['context_review']['properties'];self.assertEqual(s['last_intent']['description'],t['client_goal_boundary']['meaning'])
    def test_actual_wrong_goal_from_native151_is_rejected(self):
        c=self.candidate('Запрос информации о материале столешницы для уточнения стоимости и способа работы');self.assertIn('staff_question_as_client_goal',ext._context_review(c,self.task)[2])
    def test_common_qualification_goal_variants_are_rejected(self):
        for intent in ['Узнать материал столешницы','Уточнить состав столешницы','Получение информации о материале столешницы','Определение материала столешницы']:
            with self.subTest(intent=intent):self.assertIn('staff_question_as_client_goal',ext._context_review(self.candidate(intent),self.task)[2])
    def test_actual_work_and_scheduling_goal_stays_valid(self):
        c=self.candidate('Заказать врезку мойки и договориться об удобном времени работ');self.assertFalse(ext._context_review(c,self.task)[2])
    def test_negating_the_false_goal_does_not_assert_it(self):
        c=self.candidate('Клиент не просит узнать материал столешницы');self.assertFalse(ext._context_review(c,self.task)[2])
    def test_unrelated_or_explicit_client_question_boundary_is_not_invented(self):
        t=dict(self.task);t.pop('client_goal_boundary');self.assertFalse(ext._planned_question_as_client_goal(self.candidate('Узнать материал столешницы')['context_review'],t))
    def test_latest_alternative_day_is_not_rewritten_into_material_answer(self):
        self.assertNotIn('fixed_latest_client_meaning',self.task['output_contract']);self.assertEqual(self.task['latest_client_message']['id'],'alternative');self.assertEqual(self.out['qualification']['countertop_material']['status'],'missing')
    def test_native_top_level_schema_and_single_question_are_preserved(self):
        schema=self.out['model_task']['response_format']['schema'];self.assertEqual(set(schema['properties']),{'reply','needs_operator','context_review'});self.assertEqual(self.task['proposed_reply'],'Из какого материала столешница?')
