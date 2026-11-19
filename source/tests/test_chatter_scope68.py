"""Causal work-scope and customer-question checks; all previews are offline."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog
import assistant_prices
import assistant_qualifiers
import contact_facts
from assistant_store import Store
from extension_assistant import Assistant


def history(*rows):
    return [dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(rows)]


class ChatterScope68Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, LEADBOT_ASSISTANT_WORDING='reviewed')
        env.start()
        self.addCleanup(env.stop)
        self.app = Assistant(Store(self.tmp.name + '/db'))

    def preview(self, rows, direction='mnc'):
        out, code = self.app.handle(dict(owner='offline-scope68', action='preview', ctx=dict(
            convId='synthetic-scope68', city='Оренбург', dir=direction, partner='7', channel='avito',
            accountTitle='Иван ' + ('МНЧ' if direction == 'mnc' else 'БТ' if direction == 'bt' else 'КП'),
            itemTitle='Мастер на час' if direction == 'mnc' else 'Ремонт техники', messages=history(*rows))))
        self.assertEqual(code, 200)
        self.assertFalse(out['auto_enabled'])
        return out

    def test_light_switch_wire_is_not_an_internet_cable(self):
        text = 'Обломан провод на выключателе. Сколько стоит опрессовать гильзой и нарастить провод?'
        out = self.preview([('in', text)])
        self.assertEqual(out['action'], 'question')
        self.assertNotIn('cable-fibre', [i['rule_id'] for i in out['service']['items']])
        self.assertEqual(self.preview([('in', text + ' И ещё нарастить интернет-кабель.')])['action'], 'handoff')

    def test_pc_with_power_saving_display_is_one_diagnostic_request(self):
        out = self.preview([('in', 'Сколько стоит диагностика?'),
                            ('out', 'Диагностика чего?'),
                            ('in', 'Монитор показывает power saving mode и чёрный экран. Диагностика ПК нужна')], 'kp')
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], '1000')
        self.assertRegex(out['reply'], 'бесплат')
        separate = self.preview([('in', 'Нужно починить ПК и отдельно ремонт монитора, у него сломан разъём')], 'kp')
        self.assertEqual(separate['action'], 'handoff')

    def test_generic_diagnostic_question_clarifies_the_device(self):
        out = self.preview([('in', 'Здравствуйте'), ('in', 'Сколько стоит диагностика?')], 'kp')
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'техник|устройств|чего')
        self.assertFalse(out.get('allowed_prices'))

    def test_unknown_wires_need_a_scope_question_not_cutting_instructions(self):
        out = self.preview([('in', 'В кабинете раньше были компьютеры, осталось много проводов. Можно их отключить, отрезать?')], 'kp')
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'сетев|электрическ')
        self.assertNotRegex(out['reply'], 'отрежьте|отключите|обесточьте')
        self.assertEqual(self.preview([('in', 'Нужно отрезать и нарастить интернет-кабель')], 'kp')['action'], 'handoff')

    def test_a_program_installation_typo_does_not_establish_an_unlisted_job(self):
        out = self.preview([('in', 'По какой цене программу уставить?')], 'kp')
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'программ|установ|устройств')

    def test_booking_without_a_stated_problem_does_not_promise_a_slot(self):
        out = self.preview([('in', 'Здравствуйте, на когда можно записаться на ваши услуги?')], 'bt')
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'случилось|помощ|требуется')
        self.assertNotRegex(out['reply'], 'приеду|записал|свободно')

    def test_out_of_town_coverage_question_does_not_promise_coverage(self):
        out = self.preview([('in', 'Здравствуйте! За городом выезжаете?')], 'bt')
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'насел[её]нн|адрес')
        self.assertNotRegex(out['reply'], 'да,|выезжаю|бесплатно')

    def test_provider_city_question_does_not_establish_client_location(self):
        ms = history(('in', 'Вы с Благовещенска Амурской области'))
        self.assertEqual(assistant_qualifiers.client_city(ms), '')
        out = self.preview([('in', 'Вы из Оренбурга?')], 'bt')
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'Оренбург')
        self.assertNotRegex(out['reply'], 'я живу|нахожусь')
        self.assertEqual(assistant_qualifiers.client_city(history(('in', 'Вы из Омска? Я в Томске'))), 'Томск')
        self.assertFalse(assistant_qualifiers.provider_location_question('Можете ли вы с этим помочь?'))
        self.assertFalse(assistant_qualifiers.provider_location_question('Вы в субботу можете?'))

    def test_own_number_question_gets_the_avito_call_route(self):
        out = self.preview([('in', 'Повесить карниз'), ('in', 'Напишите пожалуйста свой номер, здесь нет уведомлений')])
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'Авито')
        self.assertNotRegex(out['reply'], r'\d{10}')

    def test_onsite_or_pickup_question_explains_only_the_offered_format(self):
        out = self.preview([('in', 'В принтере засохла краска, сколько стоит ремонт?'),
                            ('in', 'Нужно ли вам забирать его или можно всё сделать дома сразу?')], 'kp')
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'выезжает.*адрес')
        self.assertNotRegex(out['reply'], 'заберу|всё.*сразу|бесплатно|1000')

    def test_three_digit_time_limit_is_not_a_confirmed_slot(self):
        out = self.preview([('in', 'Нужна замена газлифта стола'),
                            ('out', 'Через час-полтора удобно?'),
                            ('in', 'Жду до 111, Металлургов 53 кв 47')])
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'врем|час')
        self.assertNotRegex(out['reply'], '11:00|записал')

    def test_drain_plus_furniture_keeps_the_mandatory_drain_unit_separate(self):
        out = self.preview([('in', 'Кровать доделать двухъярусную и раковина засорилась. Сможете сегодня?')])
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], '500.*погонный метр')
        self.assertRegex(out['reply'], '[Кк]роват|[Оо]стальн|[Дд]руг')
        self.assertNotRegex(out['reply'], 'вс[её].*500|500.*вс[её]')

    def test_router_firmware_is_still_agreement_but_explicit_cancellation_changes_scope(self):
        initial = [('in', 'Помогите с прошивкой роутера под VPN')]
        self.assertEqual(self.preview(initial, 'kp')['action'], 'handoff')
        out = self.preview(initial + [('out', 'Именно прошить или настроить?'),
                                      ('in', 'Можно просто установить VPN. Без прошивки')], 'kp')
        self.assertEqual(out['action'], 'question')
        self.assertNotIn('router-repair', [i['rule_id'] for i in out['service']['items']])
        self.assertEqual(self.preview(initial + [('in', 'Без прошивки'), ('in', 'Нет, всё же прошить роутер')], 'kp')['action'], 'handoff')

    def test_viewed_primary_wardrobe_supplies_the_object_not_an_unrequested_job(self):
        facts = dict(image_observations=[dict(device_kind='wardrobe', source='offline_reviewed_image')])
        text = contact_facts.intent_text('Разобрать и собрать. Цена?', facts)
        self.assertEqual(assistant_catalog.choose(text, dict(direction='mnc'))['status'], 'supported')
        self.assertNotIn('furniture', [r['id'] for r in assistant_catalog.choose(
            contact_facts.intent_text('Повесить телевизор на кронштейн', facts), dict(direction='mnc'))['items']])

    def test_minimum_is_not_a_confirmed_total_but_bare_money_still_needs_review(self):
        ms = history(('in', 'Собрать обувницы'), ('out', 'От 1500 рублей сборка'), ('in', 'От чего сумма зависит?'))
        self.assertFalse(assistant_prices.asks_to_confirm_previous_total(ms))
        self.assertTrue(assistant_prices.asks_to_confirm_previous_total(history(
            ('out', '1500 рублей за всё'), ('in', 'Это итоговая сумма?'))))
        for quote in ('От 800 такая услуга', 'от 1000\\'):
            self.assertTrue(assistant_prices.unverified_bare_quote(history(('out', quote))))
        self.assertFalse(assistant_prices.unverified_bare_quote(history(('out', 'Буду после 1000 метров от дома'))))

    def test_toilet_connector_is_not_a_second_toilet_installation(self):
        out = self.preview([('in', 'Нужно поменять трубу на слив унитаза'), ('out', 'Какая труба?'),
                            ('in', 'Чугунная, заменить на пластиковую хотел, подтекает в месте соединения')])
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'соединение.*стояк')
        self.assertNotRegex(out['reply'], 'отказ|не работаю')
        self.assertEqual(self.preview([('in', 'Нужно заменить чугунный стояк на пластиковый')])['action'], 'handoff')

    def test_restoring_a_door_lock_cutout_is_not_merely_installing_a_lock(self):
        out = self.preview([('in', 'Восстановить замочную скважину для установки замка и починить разъём петли в шкафу')])
        self.assertEqual(out['action'], 'handoff')
        self.assertRegex(out['reason'], 'соглас|оператор')
        ordinary = self.preview([('in', 'Нужно поменять дверной замок и прикрутить петлю шкафа')])
        self.assertNotEqual(ordinary['action'], 'refuse')

    def test_uncertain_ceiling_backing_is_not_an_answered_mounting_condition(self):
        out = self.preview([('in', 'Повесить новую люстру, потолок натяжной. Сколько стоит?'),
                            ('out', 'Закладная есть?'), ('in', 'Должна быть, работники повесили старую')])
        self.assertEqual(out['action'], 'question')
        self.assertRegex(out['reply'], 'проверить.*закладная')
        self.assertNotRegex(out['reply'], 'закладная есть|подходит|смогу повесить')
