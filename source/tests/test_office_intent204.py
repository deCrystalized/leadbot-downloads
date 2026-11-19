"""Office installation is a software request, not a hardware model enquiry."""
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_catalog as catalog
import assistant_prices as prices
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant


def rows(*turns):
    return [dict(id=str(i), direction=d, body=b,
                 sender_type='client' if d == 'in' else 'operator')
            for i, (d, b) in enumerate(turns)]


class OfficeIntent204Tests(unittest.TestCase):
    known = dict(direction='kp', partner='7', city='Чита', channel='avito')

    def call(self, turns, action='preview'):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,
                LEADBOT_PERSONAL_OWNER_ID='office204', LEADBOT_PERSONAL_AUTO_AVAILABLE='0'):
            result, code = Assistant(Store(tmp + '/db')).handle(dict(owner='office204', action=action,
                wording_mode='reviewed', ctx=dict(convId='synthetic-office204', dir='kp', partner='7',
                    city='Чита', channel='avito', accountTitle='Учебный мастер КП',
                    itemTitle='Компьютерная помощь', origin='С1', messages=turns)))
        self.assertEqual(code, 200)
        self.assertFalse(result['auto_enabled'])
        return result

    def test_literal_names_and_context_bound_typos_resolve_one_software_service(self):
        for body in ('Установить Word и Excel', 'Сколько стоит поставить ворд и эксель?',
                     'Вы устанавливаете Microsoft Office?', 'Office поставить на ноутбук',
                     'Нужно установить exel и world', 'Поставить программу world и excel',
                     'Установка Эксель на ПК', 'Устанавливаете пакет офис?'):
            with self.subTest(body=body):
                service = catalog.choose(body, self.known)
                self.assertEqual(service['status'], 'supported')
                self.assertEqual([r['id'] for r in service['items']], ['pc'])
                self.assertNotIn('model', service['items'][0]['questions'])
                self.assertNotIn('keep_data', service['items'][0]['questions'])

    def test_availability_answer_addresses_word_excel_before_contacts(self):
        out = self.call(rows(('in', 'Здравствуйте! Вы устанавливаете Word и Excel?')))
        self.assertNotEqual(out['action'], 'handoff')
        self.assertNotRegex(out['reply'].lower(), r'модел|марк|сохран.*данн')
        self.assertRegex(out['reply'].lower(), r'установ|помо[гч]')

    def test_first_cost_answer_keeps_price_stage_and_not_hardware_question(self):
        out = self.call(rows(('in', 'Сколько стоит поставить exel с world?')))
        self.assertNotEqual(out['action'], 'handoff')
        self.assertNotRegex(out['reply'].lower(), r'модел|марк|2000|лиценз')
        self.assertRegex(out['reply'].lower(), r'стоим|цен|осмотр')

    def test_form_and_reply_use_the_same_qualification(self):
        out = self.call(rows(('in', 'Установить Word и Excel на ноутбук')), 'checklist')
        self.assertNotIn('model', [r['key'] for r in out['results']])
        self.assertNotIn('keep_data', [r['key'] for r in out['results']])

    def test_hardware_failure_does_not_disappear_behind_office(self):
        for body in ('Ноутбук не включается. Ещё установить Word и Excel.',
                     'Установить Office и заменить SSD',
                     'Поставить Word, а также заменить термопасту'):
            with self.subTest(body=body):
                service = catalog.choose(body, self.known)
                self.assertIn('model', next(r for r in service['items'] if r['id'] == 'pc')['questions'])

    def test_special_software_and_piracy_remain_guarded(self):
        for body in ('Установить Word и взломать AutoCAD без лицензии',
                     'Установить пиратский Office', 'Настроить Photoshop и установить Excel'):
            with self.subTest(body=body):
                out = self.call(rows(('in', body)))
                self.assertFalse(out['lead']['can_create_automatically'])

    def test_nonsoftware_homonyms_do_not_become_office_installation(self):
        for body in ('Установить телевизор World Vision', 'Собрать стол в офисе',
                     'Установить World of Tanks', 'Установить world', 'Установить вывеску Office'):
            with self.subTest(body=body):
                self.assertFalse(catalog.office_installation_request(body))

    def test_quoted_negated_hypothetical_or_reported_installation_is_not_ordered(self):
        for body in ('Сосед сказал: «Поставить Word и Excel»',
                     'Не нужно устанавливать Word и Excel',
                     'Установка Office не нужна', 'Если понадобится установка Office, напишу',
                     'Мастер сказал установить Office', 'Уже установили Word и Excel'):
            with self.subTest(body=body):
                self.assertFalse(catalog.office_installation_request(body))

    def test_third_price_stage_resolves_office_package_once_including_typos(self):
        for body in ('Установить Word и Excel', 'Поставить exel с world', 'Установить Office'):
            with self.subTest(body=body):
                tariff = prices.select_tariff(body)
                self.assertEqual(tariff, ('office', 2000, 'KP-L0539'))
                history = rows(('in', body + '. Сколько стоит?'),
                               ('out', 'Точную стоимость скажу после осмотра.'),
                               ('in', 'Хотя бы от какой суммы?'),
                               ('out', 'Такая услуга от 500 рублей, без запчастей.'),
                               ('in', 'Назовите точную стоимость.'))
                answer = prices.answer(history, self.known, body)
                self.assertEqual(answer['amounts'], [2000])

    def test_two_distinct_services_do_not_get_a_fabricated_office_only_total(self):
        self.assertIsNone(prices.select_tariff('Установить Windows и Office'))

    def test_office_request_does_not_override_non_pc_device(self):
        for body in ('Установить Word на телефон', 'Установить Excel на планшет'):
            self.assertEqual(prices.device(body), 'phone')

    def test_existing_software_fault_is_not_an_installation_request(self):
        for body in ('Word и Excel не открываются', 'Office уже установлен, но зависает'):
            self.assertFalse(catalog.office_installation_request(body))

    def test_client_software_operation_has_exact_source_without_rewriting(self):
        body = 'Установить exel и world'
        state = qs.inspect(rows(('in', body)))
        self.assertEqual(state['software_use']['status'], 'answered')
        self.assertEqual(state['software_use']['quote'], body)

    def test_staff_or_system_software_is_not_a_client_answer(self):
        history = rows(('in', 'Нужна помощь с компьютером'), ('out', 'Установить Word и Excel?'))
        history.append(dict(id='sys', direction='in', sender_type='system', body='Установить exel и world'))
        self.assertNotEqual(qs.inspect(history)['software_use']['status'], 'answered')

    def test_client_data_requirement_is_not_lost(self):
        body = 'Установить Word и Excel на ноутбук. Данные нужно сохранить.'
        out = self.call(rows(('in', body)), 'checklist')
        self.assertTrue(any('Данные нужно сохранить' in x for x in out['facts']['comment_lines']))

    def test_bt_appliance_model_requirement_is_unchanged(self):
        service = catalog.choose('Стиральная машина не сливает', dict(direction='bt', city='Чита'))
        self.assertIn('model', service['items'][0]['questions'])

    def test_owner_reported_actual_software_fault_answers_help_cost_and_symptom(self):
        body = 'Здравствуйте,не работает Word/Exel на компьютере.Можете помочь?И какая стоимость?'
        out = self.call(rows(('in', body)))
        self.assertNotEqual(out['action'], 'handoff')
        self.assertNotRegex(out['reply'].lower(), r'модел|марк|год|переустанов|лиценз|2000')
        self.assertRegex(out['reply'].lower(), r'стоим|осмотр')
        self.assertRegex(out['reply'].lower(), r'ошиб|запуск|открыва')
        self.assertRegex(out['reply'].lower(), r'помо[гч]')

    def test_software_symptom_is_a_distinct_question_with_exact_client_evidence(self):
        history = rows(('in', 'Не работают Word и Excel'),
                       ('out', 'Что происходит при запуске программы: появляется ошибка или она не открывается?'),
                       ('in', 'При запуске пишет ошибку 0xc0000142'))
        state = qs.inspect(history)['office_symptom']
        self.assertEqual(state['status'], 'answered')
        self.assertEqual(state['message_id'], '2')
        self.assertEqual(state['quote'], history[2]['body'])
        out = self.call(history)
        self.assertNotRegex(out['reply'].lower(), r'что происходит|модел|марк|переустанов')

    def test_stated_concrete_software_symptom_is_not_reasked(self):
        out = self.call(rows(('in', 'Word не открывается, выдаёт ошибку 0xc0000142. Сколько стоит помощь?')))
        self.assertNotRegex(out['reply'].lower(), r'что происходит|модел|марк|год')

    def test_unnecessary_old_model_question_cannot_force_human_handoff(self):
        out = self.call(rows(('in', 'Не работают Word и Excel на компьютере'),
                             ('out', 'Марку и модель подскажите?'), ('in', 'Старенький компьютер, я не знаю')))
        self.assertNotEqual(out['action'], 'handoff')
        self.assertNotRegex(out['reply'].lower(), r'модел|марк|какого года')

    def test_real_hardware_failure_retains_model_in_mixed_software_fault(self):
        service = catalog.choose('Word не работает, а компьютер не включается', self.known)
        self.assertIn('model', next(r for r in service['items'] if r['id'] == 'pc')['questions'])

    def test_staff_system_quote_or_conditional_cannot_supply_a_software_symptom(self):
        for text in ('Если Word не откроется, напишу', 'Мастер сказал, что Word не открывается',
                     'В инструкции: «Word не открывается»'):
            self.assertFalse(catalog.office_fault_request(text))
        for sender in ('system', 'operator', 'bot'):
            state = qs.inspect([dict(id='foreign', direction='in', sender_type=sender,
                                     body='Word не открывается')])['office_symptom']
            self.assertEqual(state['status'], 'missing')

    def test_provider_city_question_with_particle_is_answered_before_intake(self):
        out = self.call(rows(('in', 'Не работает Word и Excel'), ('out', 'Марку и модель подскажите?'),
                             ('in', 'Вы же из Норильска,верно?Где эту информацию я могу посмотреть?Марку и модель?')))
        self.assertIn('Чита', out['reply'])
        self.assertNotIn('Норильск', out['reply'])
        self.assertNotRegex(out['reply'].lower(), r'модел|марк|год')

    def test_postfix_installation_negation_is_not_a_new_software_order(self):
        for body in ('Устанавливать Office не надо', 'Поставить Word не нужно'):
            self.assertFalse(catalog.office_installation_request(body))
