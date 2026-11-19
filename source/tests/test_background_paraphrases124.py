"""Independent actor/fragment paraphrases found before deployment124."""
import unittest
import test_client_background_work124 as original
import extension_assistant as ext


class BackgroundParaphrase124Tests(unittest.TestCase):
    setUp = original.ClientBackground124Tests.setUp
    finish = original.ClientBackground124Tests.finish
    prepare = original.ClientBackground124Tests.prepare
    candidate = original.ClientBackground124Tests.candidate

    def test_background_client_actor_may_be_instrumental(self):
        out, task = self.prepare()
        value = self.candidate(task)
        value['context_review']['last_intent'] = 'На фоне поклейки обоев клиентом заказаны две розетки'
        self.assertEqual(self.finish(out, value)['validation'], [])

    def test_self_word_does_not_excuse_a_new_service_order(self):
        out, task = self.prepare()
        value = self.candidate(task)
        value['context_review']['last_intent'] = 'Клиент сам начинал ремонт и теперь заказывает нам поклейку обоев и две розетки'
        self.assertIn('client_background_work_added_to_order', self.finish(out, value)['validation'])

    def test_known_address_may_be_mentioned_in_materials_meaning(self):
        for meaning in ['Ждёт ответа о проводе и розетке; адрес уже передан',
                        'Клиент спрашивает, будут ли провод и розетка, а адрес уже сообщили',
                        'Ждёт провод и розетку, адрес уже известен']:
            with self.subTest(meaning=meaning):
                self.setUp()
                out, task = self.prepare()
                value = self.candidate(task)
                value['context_review']['latest_client_meaning'] = meaning
                self.assertEqual(self.finish(out, value)['validation'], [])

    def test_materials_question_is_not_inventory_confirmation(self):
        out, task = self.prepare()
        value = self.candidate(task)
        value['context_review']['latest_client_meaning'] = 'Не про адрес: это подтверждение, что провод и розетки мастер привезёт'
        self.assertIn('materials_question_used_as_inventory_confirmation', self.finish(out, value)['validation'])

    def test_source_requested_repair_of_diy_object_is_retained(self):
        # Pure meaning validator: this is not a model or functional service pass.
        _, task = self.prepare()
        task['client_background_work'][0]['excluded_from_service_selection'] = False
        task['requested_service_text'] = 'Сам поклеил обои, а они отошли. Нужно исправить поклейку.'
        for intent in ['Клиент просит исправить неудачную поклейку обоев, выполненную самостоятельно',
                       'Нужно исправить поклейку обоев после моей самостоятельной работы']:
            value = self.candidate(task)
            value['context_review']['last_intent'] = intent
            self.assertEqual(ext._context_review(value, task)[2], [])

    def test_order_other_work_does_not_change_background_actor(self):
        out, task = self.prepare()
        value = self.candidate(task)
        value['context_review']['last_intent'] = 'На фоне поклейки обоев клиентом он заказывает нам две розетки'
        self.assertEqual(self.finish(out, value)['validation'], [])

    def test_repair_of_another_object_does_not_order_the_background_work(self):
        # Retaining an object anchor is not proof that its repair was ordered.
        _, task = self.prepare()
        task['client_background_work'][0]['excluded_from_service_selection'] = False
        task['requested_service_text'] = 'Клею обои сам. От вас нужен ремонт телевизора, он не включается.'
        value = self.candidate(task)
        value['context_review']['last_intent'] = 'Нужен ремонт телевизора и поклейка обоев'
        self.assertIn('client_background_work_added_to_order', ext._context_review(value, task)[2])


if __name__ == '__main__':
    unittest.main()

