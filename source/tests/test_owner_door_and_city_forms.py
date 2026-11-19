"""Reviewed ordinary door fittings and physical-city/CRM-branch boundaries."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadbot/brain'))
import assistant_catalog as catalog
import assistant_prices as prices
import qualification_state as qs
from assistant_store import Store
from extension_assistant import Assistant, _parse


def msg(body, direction='in', mid='client'):
    return dict(id=mid, direction=direction, body=body, sender_type='client' if direction == 'in' else 'operator')


def rows():
    return [msg('Нужно заменить в межкомнатной двери ручку, какая стоимость?', mid='task'),
            msg('Без врезки. Просто замена', mid='clarification'),
            msg('У вас она в наличии уже есть?', 'out', 'question'), msg('Да', mid='answer'),
            msg('Цена какая', mid='price'), msg('ОТ 800 рублей такая работа, более точно по месту', 'out', 'quote')]


class OwnerDoorAndCityTests(unittest.TestCase):
    def test_ordinary_handle_is_one_supported_door_job_without_cutting(self):
        service = catalog.choose('\n'.join(m['body'] for m in rows() if m['direction'] == 'in'), {'direction': 'mnc'})
        self.assertEqual(service['status'], 'supported')
        self.assertEqual([x['id'] for x in service['items']], ['lock'])
        for text in ('Нужно врезать замок в дверь', 'Нужно заменить ручку и врезать замок в дверь'):
            self.assertNotEqual(catalog.choose(text, {'direction': 'mnc'})['status'], 'supported')

    def test_separate_appliance_handle_keeps_operator_route(self):
        for text in ('Заменить ручку межкомнатной двери и ручку холодильника',
                     'Ручка двери, без врезки. Также заменить ручку холодильника.'):
            service = catalog.choose(text, {'direction': 'mnc'})
            self.assertEqual(service['status'], 'mixed')
            self.assertIn('body-handles', [x['id'] for x in service['items']])

    def test_fitting_availability_answer_and_singular_task_are_not_asked_again(self):
        state = qs.inspect(rows())
        self.assertEqual(state['materials']['status'], 'answered')
        self.assertEqual(state['materials']['value'], 'yes')
        self.assertEqual(state['materials']['question_message_id'], 'question')
        self.assertEqual(state['volume']['status'], 'answered')
        self.assertEqual(state['door_type']['status'], 'answered')
        self.assertEqual(state['door_material']['status'], 'missing')
        unrelated = [msg('Нужно заменить ручку двери'), msg('У вас квартира есть?', 'out'), msg('Да')]
        self.assertEqual(qs.inspect(unrelated)['materials']['status'], 'missing')
        self.assertEqual(qs.inspect([msg('Нужно заменить ручки двери')])['volume']['status'], 'missing')

    def test_documented_door_minimum_is_valid_but_earlier_material_yes_is_not_price_consent(self):
        source = rows();consent = prices.consent(source)
        self.assertEqual(consent['status'], 'pending')
        self.assertTrue(prices.prior_quote_verified(source, {'direction': 'mnc'}, consent, manual=True))
        self.assertEqual(prices.door_minimum_quote(source, {'direction': 'mnc'}, consent)['rules'], ['DOC-L0367'])
        for quote in ('От 1000 рублей', '800 рублей окончательно', 'От 800 рублей за час', 'От 800 рублей за штуку'):
            changed = source[:-1] + [msg(quote, 'out', 'quote')]
            self.assertIsNone(prices.door_minimum_quote(changed, {'direction': 'mnc'}, prices.consent(changed)))
        entrance = [msg('Заменить ручку входной двери'), msg('От 1000 рублей', 'out', 'quote')]
        self.assertEqual(prices.door_minimum_quote(entrance, {'direction': 'mnc'}, prices.consent(entrance))['rules'], ['DOC-L0368'])

    def test_manual_form_keeps_real_missing_contacts_and_pending_price_consent(self):
        ctx=dict(convId='synthetic-door-form', dir='mnc', city='Саранск', partner='7', channel='avito',
                 accountTitle='Михаил МНЧ',itemTitle='Мастер на час',origin='В75',messages=rows())
        with tempfile.TemporaryDirectory() as t:
            out, code = Assistant(Store(t+'/db')).handle(dict(owner='offline',action='checklist',ctx=ctx))
        self.assertEqual(code, 200);self.assertFalse(out['auto_enabled'])
        self.assertEqual(out['approval'], '')
        self.assertTrue(out['hard_block'])
        self.assertIn('явное согласие', out['operator_review'])
        self.assertFalse(out['facts']['contact_phone_to_use']);self.assertFalse(out['facts']['address'])
        self.assertTrue(next(r for r in out['results'] if r['key']=='materials')['done'])

    def test_same_listing_city_is_not_called_a_customer_city_mistake(self):
        ctx=dict(convId='synthetic-troitsk',dir='kp',city='Челябинск',crmCity='Челябинск',
                 cityRaw='chelyabinskaya_oblast_troitsk',partner='7',channel='avito',accountTitle='Дамир КП',
                 itemTitle='Ремонт принтеров',messages=[msg('Принтер Epson не печатает'),msg('Троицк 10 квартал дом 28 3 подъезд кв 60',mid='address')])
        _,m,k,_=_parse(ctx)
        self.assertEqual(k['city'], 'Троицк')
        self.assertEqual(k['selected_crm_city'], 'Челябинск')
        from contact_facts import collect
        self.assertEqual(collect(m,k)['client_location']['status'],'confirmed')
        self.assertNotIn('printer_connection',catalog.choose('Принтер Epson не печатает',k)['items'][0]['questions'])
        self.assertIn('printer_connection',catalog.choose('Подключить принтер Epson к телефону',k)['items'][0]['questions'])

    def test_true_other_city_and_corrected_branch_keep_existing_verification(self):
        for selected,want in [('Омск','Омск'),('Томск','Томск')]:
            ctx=dict(convId='synthetic-city-correction',dir='mnc',city=selected,crmCity=selected,cityRaw='omsk',
                     messages=[msg('Я живу в Томске, Южные Ворота. Улица Королева 8')])
            _,_,known,_=_parse(ctx);self.assertEqual(known['city'],want)


if __name__ == '__main__':
    unittest.main()
