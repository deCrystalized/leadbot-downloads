"""Acceptance/price cases adjudicated against current primary paragraphs."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog as catalog
import assistant_prices as prices
import assistant_qualifiers as qualifiers
import contact_facts
import qualification_state as qs
from extension_assistant import Assistant
from assistant_store import Store


def msg(text, direction='in'):
    return dict(id=text[:20] + direction, direction=direction, body=text)


class ManualBatch7RuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Assistant(Store(str(Path(self.tmp.name) / 'db')))
        self.env = os.environ.get('LEADBOT_ASSISTANT_WORDING')
        os.environ['LEADBOT_ASSISTANT_WORDING'] = 'reviewed'

    def tearDown(self):
        self.tmp.cleanup()
        if self.env is None:
            os.environ.pop('LEADBOT_ASSISTANT_WORDING', None)
        else:
            os.environ['LEADBOT_ASSISTANT_WORDING'] = self.env

    def preview(self, messages, direction='mnc', title='Сборка и ремонт мебели', account='Григорий МНЧ'):
        r, code = self.app.handle(dict(owner='offline-batch7', action='preview', ctx=dict(convId='synthetic',
            city='Оренбург', dir=direction, partner='7', channel='avito', accountTitle=account,
            itemTitle=title, messages=messages)))
        self.assertEqual(code, 200)
        self.assertFalse(r['auto_enabled'])
        self.assertFalse(r.get('validation'))
        return r

    def test_normal_furniture_price_first_turn_is_not_limited_to_word_shkaf(self):
        for item in ('два комода', 'пеленальный комод', 'кресло', 'полки'):
            with self.subTest(item=item):
                r = self.preview([msg('Здравствуйте, сколько стоит собрать ' + item + '?')])
                self.assertEqual(r['action'], 'question')
                self.assertRegex(r['reply'], 'стоим|цен')
                self.assertNotRegex(r['reply'], r'\b1500\b')

    def test_shelves_assembly_is_furniture_not_wall_mounting(self):
        known = dict(direction='mnc', title='Сборка мебели')
        self.assertEqual(catalog.choose('Сборка полок', known)['items'][0]['family'], 'furniture')
        self.assertEqual(catalog.choose('Повесить полки на стену', known)['items'][0]['family'], 'hanging')

    def test_semi_automatic_washer_is_not_a_circuit_breaker(self):
        s = catalog.choose('Машинки полуавтомат делаете?', dict(direction='bt'))
        self.assertEqual(s['status'], 'supported')
        self.assertEqual(s['items'][0]['family'], 'washer')
        self.assertEqual(catalog.choose('Заменить автомат в щитке', dict(direction='mnc'))['items'][0]['family'], 'electric')

    def test_broken_technical_housing_requires_agreement_in_its_actual_profile(self):
        for direction, text in (('bt', 'Машинка полуавтомат, лопнул корпус'), ('kp', 'Ремонт корпуса ноутбука')):
            s = catalog.choose(text, dict(direction=direction))
            self.assertEqual(s['status'], 'agree')
            self.assertIn('DOC-L0467', s['rules'])
        self.assertNotEqual(catalog.choose('Корпус не поврежден, стиральная машина не включается', dict(direction='bt'))['status'], 'agree')
        self.assertEqual(catalog.choose('Ремонт корпуса шкафа', dict(direction='mnc'))['status'], 'supported')

    def test_payment_verb_and_telephone_communication_are_not_extra_jobs(self):
        self.assertEqual(catalog.choose('Принтер не работает, оплату проводить не буду', dict(direction='kp'))['status'], 'supported')
        self.assertEqual(prices.device('Компьютер не включается, обсудим по телефону'), 'pc')
        self.assertEqual(catalog.choose('Нужно отремонтировать телефон', dict(direction='kp'))['items'][0]['family'], 'phone')

    def test_washing_and_latch_context_is_not_a_house_door_lock(self):
        s = catalog.choose('Машинка закончила стирку, замок щелкнул, дверца не открывается', dict(direction='bt'))
        self.assertEqual(s['status'], 'supported')
        self.assertEqual(s['items'][0]['family'], 'washer')
        s = catalog.choose('Стиральная машина не работает. Еще заменить замок входной двери', dict(direction='bt'))
        self.assertIn(s['status'], ('mixed', 'route'))

    def test_windows_spelling_has_one_general_pc_tariff(self):
        for name in ('Виндоус', 'виндовс', 'Windows'):
            self.assertEqual(prices.device('Установить ' + name), 'pc')
            self.assertEqual(prices.select_tariff('Установить ' + name)[1], 2000)

    def test_boiler_dripping_and_fuel_are_not_guessed(self):
        known = dict(channel='avito', direction='mnc', account_name='Матвей БТ/МНЧ', title='Бойлер не греет воду / Ремонт бойлеров')
        direction, _ = catalog.source_direction(known)
        self.assertEqual(direction, 'bt')
        s = catalog.choose('С бойлера капает вода холодная снизу', dict(known, direction=direction))
        self.assertEqual(s['status'], 'agree')
        self.assertIn('DOC-L0390', s['rules'])
        self.assertNotEqual(catalog.choose('С бойлера не капает вода, он не греет', dict(direction='bt'))['status'], 'agree')

    def test_unknown_boiler_fuel_is_asked_before_invitation_or_contacts(self):
        r = self.preview([msg('Упало давление в котле')], 'bt', 'Ремонт бойлеров', 'Виктор БТ')
        self.assertEqual(r['action'], 'question')
        self.assertRegex(r['reply'], 'газ|электр')
        s = catalog.choose('Газовый котёл не греет', dict(direction='bt'))
        self.assertEqual(s['status'], 'refuse')

    def test_mouse_pc_requirement_precedes_address_collection(self):
        r = self.preview([msg('Нужно поменять энкодер мыши'), msg('Когда удобно?', 'out'), msg('Колесо туда сюда ходит')], 'kp', 'Ремонт компьютеров', 'Денис КП')
        self.assertRegex(r['reply'], 'компьют|ПК|ноутбук|моноблок')
        rows = [msg('Ремонт мыши'), msg('ПК или ноутбук есть?', 'out'), msg('Нет')]
        r = self.preview(rows, 'kp', 'Ремонт компьютеров', 'Денис КП')
        self.assertEqual(r['action'], 'handoff')

    def test_countertop_reverse_word_order_and_uncertain_followup(self):
        rows = [msg('В столешнице дырку под газовую панель вырезать'), msg('Столешница из ДСП?', 'out'), msg('Да'), msg('Вроде как')]
        s = catalog.choose('\n'.join(x['body'] for x in rows if x['direction'] == 'in'), dict(direction='mnc'))
        self.assertEqual(s['status'], 'supported')
        self.assertEqual(qs.inspect(rows)['countertop_material']['status'], 'uncertain')
        r = self.preview(rows)
        self.assertEqual(r['action'], 'question')
        self.assertRegex(r['reply'], 'материал|ДСП')

    def test_drain_in_a_toilet_is_one_job_with_mandatory_per_metre_quote(self):
        r = self.preview([msg('В Оренбурге нужно устранить засор в унитазе. Что по цене?')], title='Сантехник')
        self.assertEqual(r['action'], 'question')
        self.assertRegex(r['reply'], '500.*погонный метр')
        self.assertNotIn('1500', r['reply'])
        s = catalog.choose('Устранить засор в унитазе. Также заменить крепления унитаза', dict(direction='mnc'))
        self.assertIn('toilet', [x['id'] for x in s['items']])

    def test_shower_assembly_is_a_normal_bath_service(self):
        self.assertEqual(catalog.choose('Собрать душевую кабину', dict(direction='mnc'))['items'][0]['id'], 'bath')

    def test_screen_bands_do_not_confirm_matrix_damage(self):
        for body in ('Телевизор LED, на экране цветные полосы', 'Телевизор с полосами, матрица целая'):
            self.assertFalse(catalog.confirmed_tv_matrix(body))
            service = catalog.choose(body, dict(direction='kp'))
            self.assertEqual(service['status'], 'refuse')
            self.assertIn('OWNER-TV-BANDS-20261017', service['rules'])

    def test_negative_inventory_does_not_invent_nonpurchase_or_branch_agreement(self):
        rows = [msg('Повесить карниз и поменять смеситель'), msg('У вас всё в наличии?', 'out'), msg('Нет ещё'), msg('Карниз на потолок или стену?', 'out'), msg('На потолок')]
        self.assertEqual(qs.inspect(rows)['materials']['value'], 'no')
        reply = self.preview(rows, title='Мастер на час')
        self.assertNotRegex(reply['reason'], 'не приобретены')
        self.assertNotIn('Изделия или материалы', reply['reason'])
        self.assertEqual(reply['facts']['material_availability']['value'], 'no')
        self.assertTrue(any('Нет ещё' in line for line in reply['facts']['comment_lines']))

    def test_broken_matrix_route_depends_on_confirmed_tv_kind(self):
        for body, expected in (('Разбита матрица телевизора', 'agree'), ('Телевизор LED, разбита матрица', 'refuse'), ('Плазменный телевизор, разбита матрица', 'agree')):
            self.assertEqual(catalog.choose(body, dict(direction='kp'))['status'], expected)

    def test_elliptic_screen_problem_uses_ad_context_without_diagnosing(self):
        r = self.preview([msg('Не горит экран, сверху тонкая разноцветная полоска, Алиса отвечает')], 'kp', 'Ремонт телевизоров', 'Денис КП')
        self.assertEqual(r['action'], 'refuse')
        self.assertRegex(r['reply'], 'К сожалению.*не смогу помочь')
        self.assertNotRegex(r['reply'], 'матриц|повреждена')
        s = catalog.choose('Разбит экран смартфона', dict(direction='kp', title='Ремонт телевизоров'))
        self.assertNotIn('tv', [x['family'] for x in s['items']])

    def test_ad_profile_can_correct_an_account_guess_but_not_operator_choice(self):
        for account, title, before, after in (('Никита МНЧ', 'Ремонт и настройка принтеров и МФУ', 'mnc', 'kp'), ('Марк КП', 'Муж на час / Сборка мебели', 'kp', 'mnc')):
            known = dict(channel='avito', direction=before, direction_basis='account', account_name=account, title=title)
            self.assertEqual(catalog.source_direction(known)[0], after)
            self.assertEqual(catalog.source_direction(dict(known, direction_basis='operator'))[0], before)
            self.assertEqual(catalog.source_direction(dict(known, channel='max'))[0], before)

    def test_custom_accounting_integration_is_not_basic_tv_setup(self):
        r = self.preview([msg('Директор хочет выводить количество оплат на телевизор в реальном времени: бухгалтерия вбивает данные, появляется новая оплата')], 'kp', 'Установка программ', 'Денис КП')
        self.assertEqual(r['action'], 'handoff')

    def test_full_kiosk_fitout_is_not_a_small_furniture_job(self):
        r = self.preview([msg('Там ларек общепита, электрики и сантехники. Нужно полностью подготовить точку, рассмотреть весь проект')])
        self.assertEqual(r['action'], 'handoff')
        self.assertEqual(catalog.choose('В павильоне общепита собрать стол', dict(direction='mnc'))['status'], 'supported')

    def test_bt_does_not_confirm_kp_fee_suggested_by_the_customer(self):
        r = self.preview([msg('В Оренбурге стиральная машина Leran не открывает дверцу'), msg('Когда удобно?', 'out'), msg('Диагностика 1000р?')], 'bt', 'Ремонт стиральных машин', 'Матвей БТ')
        self.assertEqual(r['action'], 'question')
        self.assertRegex(r['reply'], '800')
        self.assertRegex(r['reply'], 'При продолжении работ')
        self.assertRegex(r['reply'], 'бесплатн')
        self.assertNotIn('1000', r['reply'])

    def test_electrical_plug_does_not_establish_boiler_fuel(self):
        self.assertEqual(qs.inspect([msg('К бойлеру подключена электрическая вилка')])['gas_type']['status'], 'missing')
        self.assertEqual(qs.inspect([msg('Бойлер электрический')])['gas_type']['status'], 'answered')

    def test_explicit_old_service_price_without_currency_is_not_silently_accepted(self):
        rows = [msg('Прошивка телевизора'), msg('От 600 стоит прошивка', 'out'), msg('Хорошо')]
        r = self.preview(rows, 'kp', 'Ремонт телевизоров', 'Денис КП')
        self.assertEqual(r['action'], 'handoff')
        self.assertRegex(r['reason'], 'стоим|цен')


if __name__ == '__main__':
    unittest.main()
