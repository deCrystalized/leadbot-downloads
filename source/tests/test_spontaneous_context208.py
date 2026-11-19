"""Conversation failures found in spontaneous192 cases, frozen before208 code."""
import unittest
import assistant_catalog as catalog
import qualification_state as qs


def client(text, mid='client', role='client', direction='in'):
    return dict(id=mid, direction=direction, sender_type=role, body=text)


class SpontaneousContext208Tests(unittest.TestCase):
    known = dict(direction='mnc', channel='avito', partner='7', city='Чита')

    def instructions(self, text):
        return qs.inspect([client(text)])['instructions']

    def test_current_possession_in_a_box_avoids_a_repeat_without_claiming_visual_review(self):
        for text in ('Схема осталась в коробке.', 'Инструкция лежит в упаковке.',
                     'Инструкция сборки у меня на руках.', 'Схема находится у меня.'):
            with self.subTest(text=text):
                row = self.instructions(text)
                self.assertEqual(row['status'], 'answered')
                self.assertEqual(row['message_id'], 'client')
                self.assertEqual(row['evidence_source'], 'client_message')
                self.assertEqual(row['quote'], text)
                self.assertNotIn('media_reviewed', row)

    def test_coordinated_existence_is_not_lost_to_the_old_twenty_character_limit(self):
        row = self.instructions('Схема и комплект крепежа есть.')
        self.assertEqual(row['status'], 'answered')
        self.assertEqual(row['message_id'], 'client')

    def test_question_hypothesis_and_uncertainty_do_not_establish_current_possession(self):
        for text in ('Схема лежит в коробке?', 'Если схема останется в коробке, пришлю.',
                     'Наверное, схема лежит в коробке.', 'Не уверен, инструкция в коробке.',
                     'А схема и комплект крепежа есть?'):
            self.assertNotEqual(self.instructions(text)['status'], 'answered', text)

    def test_future_delivery_or_past_missing_scheme_is_not_current_possession(self):
        for text in ('Инструкция будет в коробке завтра.', 'Схема раньше лежала в коробке.',
                     'Завтра привезут шкаф, схема в коробке есть.', 'Инструкция была, но потерялась.'):
            row = self.instructions(text)
            self.assertFalse(row['status'] == 'answered' and row['value'].lower() not in ('no', 'нет')
                             and not any(x in row['value'].lower() for x in ('потер', 'нет')), text)

    def test_quoted_foreign_and_different_order_possession_cannot_supply_instructions(self):
        for text in ('Сосед сказал: «Схема осталась в коробке».',
                     'Мастер говорит, инструкция лежит в коробке.',
                     'Схема от другого шкафа лежит в коробке.',
                     'Инструкция от старого заказа у меня на руках.'):
            self.assertNotEqual(self.instructions(text)['status'], 'answered', text)

    def test_staff_system_and_bot_cannot_fill_client_instruction_possession(self):
        for role in ('operator', 'system', 'assistant', 'bot'):
            self.assertNotEqual(qs.inspect([client('Схема и комплект крепежа есть.', role=role)])['instructions']['status'], 'answered', role)

    def test_instruction_statement_does_not_establish_material_completeness(self):
        state = qs.inspect([client('Нужно собрать комод. Схема осталась в коробке.')])
        self.assertEqual(state['instructions']['status'], 'answered')
        self.assertEqual(state['materials']['status'], 'missing')

    def test_new_order_does_not_inherit_the_previous_instruction(self):
        state = qs.inspect([client('Схема для шкафа есть.', 'old'), client('Новая заявка: собрать кровать.', 'new')])
        self.assertNotEqual(state['instructions']['status'], 'answered')

    def test_colloquial_explicit_absence_keeps_the_previous_answer(self):
        for text in ('Инструкции нету.', 'Нету схемы сборки.'):
            row = self.instructions(text)
            self.assertEqual(row['status'], 'answered')
            self.assertIn('нету', row['value'].lower())

    def test_adjacent_request_can_refer_to_named_absent_office_apps(self):
        for text in ('На ноутбуке нет exel и world. Сможете поставить?',
                     'У меня нет Word и Excel. Можете установить?',
                     'Нет программы Excel. Установите, пожалуйста.',
                     'Microsoft Office отсутствует. Поставить сможете?'):
            self.assertTrue(catalog.office_installation_request(text), text)
            self.assertTrue(catalog.ordinary_office_installation(text), text)

    def test_absence_or_past_installation_alone_is_not_a_new_software_job(self):
        for text in ('На ноутбуке нет Word и Excel.', 'Word и Excel уже установили.',
                     'Раньше не было Office. Сейчас всё поставлено.'):
            self.assertFalse(catalog.office_installation_request(text), text)

    def test_anaphora_cannot_bind_another_object_or_a_different_order(self):
        for text in ('Нет Word и Excel. Сможете поставить телевизор?',
                     'Нет Excel. Новая заявка: поставить полку.',
                     'На ноутбуке нет Office. В квартире надо поставить шкаф.',
                     'Установить World of Tanks. Word у меня нет.'):
            self.assertFalse(catalog.office_installation_request(text), text)

    def test_quoted_hypothetical_or_negated_anaphoric_request_is_not_ordered(self):
        for text in ('Сосед сказал: «Нет Excel. Сможете поставить?»',
                     'Нет Word и Excel. Если понадобится, сможете поставить?',
                     'Нет Excel. Но устанавливать не нужно.',
                     'Нет Office. Мастер сказал поставить.',
                     'Вчера не было Excel. Тогда просили поставить.'):
            self.assertFalse(catalog.office_installation_request(text), text)

    def test_named_app_context_does_not_turn_any_world_homonym_into_word(self):
        for text in ('Нет World Vision. Сможете поставить?',
                     'Нет World of Tanks. Установите?', 'Нет world. Сможете поставить?'):
            self.assertFalse(catalog.office_installation_request(text), text)

    def test_hardware_fault_still_requires_its_own_qualification(self):
        text = 'Ноутбук не включается. На нём нет Word и Excel. Сможете поставить?'
        self.assertTrue(catalog.office_installation_request(text))
        self.assertFalse(catalog.ordinary_office_installation(text))

    def optional(self, text, role='client'):
        return catalog.mixed_optional_scope([client(text, role=role)], self.known, text)

    def test_nonmandatory_extra_repair_does_not_block_ordinary_jobs(self):
        for tail in ('не обязательно сразу чинить', 'необязательно сразу чинить',
                     'ремонт сейчас не обязателен'):
            text = 'Нужно поменять смеситель и повесить карниз. Отопление по возможности посмотреть, ' + tail + '.'
            scope = self.optional(text)
            self.assertIsNotNone(scope, text)
            self.assertFalse(scope['extras'][0]['execution_approved'])
            self.assertFalse(scope['client_consent_to_extra_execution'])
            self.assertIn('смесител', scope['primary_text'])
            self.assertIn('карниз', scope['primary_text'])

    def test_mandatory_or_conditional_execution_is_not_an_optional_look(self):
        for tail in ('обязательно починить', 'только если отопление почините',
                     'не обязательно сегодня, но обязательно завтра починить'):
            self.assertIsNone(self.optional('Заменить смеситель. Отопление посмотреть и ' + tail + '.'), tail)

    def test_nonmandatory_words_alone_do_not_create_an_inspection_request(self):
        for text in ('Заменить смеситель. Заменить стояк отопления, не обязательно сразу.',
                     'Отопление посмотреть, не обязательно чинить.',
                     'Заменить смеситель. Неизвестный механизм по возможности посмотреть, необязательно чинить.'):
            self.assertIsNone(self.optional(text), text)

    def test_optional_quote_or_foreign_role_cannot_approve_main_intake(self):
        text = 'Поменять смеситель. Отопление по возможности посмотреть, не обязательно чинить.'
        for role in ('system', 'operator', 'bot'):
            self.assertIsNone(self.optional(text, role), role)
        self.assertIsNone(self.optional('Поменять смеситель. Сосед сказал: «Отопление посмотреть, необязательно чинить».'))

    def test_withdrawal_and_later_mandatory_demand_preserve_the_extra_boundary(self):
        original = 'Поменять смеситель. Отопление по возможности посмотреть, не обязательно чинить.'
        messages = [client(original, 'first'), client('Отопление смотреть не надо.', 'later')]
        withdrawn = catalog.mixed_optional_scope(messages, self.known, original+'\nОтопление смотреть не надо.')
        self.assertIsNotNone(withdrawn)
        self.assertEqual(withdrawn['extras'], [])
        self.assertIn('heating', withdrawn['withdrawn_subjects'])
        self.assertFalse(withdrawn['extra_execution_approved'])
        correction = 'Отопление обязательно починить.'
        self.assertIsNone(catalog.mixed_optional_scope([client(original, 'first'), client(correction, 'later')],
                                                    self.known, original+'\n'+correction))

    def test_optional_inspection_never_accepts_a_repair_promise_in_free_model_text(self):
        scope = self.optional('Поменять смеситель. Отопление по возможности посмотреть, необязательно чинить.')
        self.assertIsNotNone(scope)
        self.assertTrue(catalog.optional_execution_claim('Отопление отремонтирую за один визит.', scope))
        self.assertFalse(catalog.optional_execution_claim('По отоплению только посмотрю на месте.', scope))

class VoluntaryFurnitureInventory208Tests(unittest.TestCase):
    def state(self, text, **extra):
        return qs.inspect([dict(client(text), **extra)])['materials']

    def test_inline_complete_parts_and_fasteners_do_not_need_a_previous_question(self):
        text='Нужно собрать комод. Схема осталась в коробке, все детали и крепёж на месте.'
        row=self.state(text)
        self.assertEqual(row['status'],'answered')
        self.assertEqual(row['value'],'yes')
        self.assertEqual(row['message_id'],'client')
        self.assertEqual(row['quote'],text)
        self.assertEqual(row['availability_scope'],'client_stated_complete_furniture_kit')
        self.assertNotIn('question_message_id',row)

    def test_material_statement_can_be_on_a_later_turn_without_a_staff_prompt(self):
        row=qs.inspect([client('Собрать шкаф-купе.','work'),client('Все детали и крепёж уже в наличии.','parts')])['materials']
        self.assertEqual(row['status'],'answered')
        self.assertEqual(row['message_id'],'parts')

    def test_partial_inventory_or_another_trade_does_not_establish_complete_furniture_kit(self):
        for text in ('Нужно собрать комод. Крепёж есть.',
                     'Нужно собрать комод. Комплект крепежа есть.',
                     'Повесить полку. Все детали и крепёж на месте.',
                     'Нужно собрать комод. Все детали и крепёж для другой кровати на месте.'):
            row=self.state(text)
            self.assertNotEqual(row.get('availability_scope'),'client_stated_complete_furniture_kit',text)

    def test_future_negated_uncertain_or_quoted_kit_is_not_current_inventory(self):
        for tail in ('Все детали и крепёж завтра будут на месте.', 'Все детали и крепёж не на месте.',
                     'Кажется, все детали и крепёж на месте.', 'Все детали и крепёж на месте?',
                     'Мастер сказал: «Все детали и крепёж на месте».', 'У вас все детали и крепёж на месте?'):
            self.assertNotEqual(self.state('Собрать комод. '+tail).get('availability_scope'),
                                'client_stated_complete_furniture_kit',tail)

    def test_foreign_roles_and_new_order_cannot_supply_complete_inventory(self):
        for role in ('system','operator','bot'):
            self.assertNotEqual(self.state('Собрать шкаф. Все детали и крепёж на месте.',sender_type=role).get('availability_scope'),'client_stated_complete_furniture_kit')
        row=qs.inspect([client('Собрать шкаф. Все детали и крепёж на месте.','old'),
                        client('Новая заявка: собрать кровать.','new')])['materials']
        self.assertNotEqual(row.get('availability_scope'),'client_stated_complete_furniture_kit')


if __name__ == '__main__':
    unittest.main()
