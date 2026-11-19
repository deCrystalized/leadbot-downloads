"""Primary MNC unit tariffs are distinct from minima, budgets and diagnosis."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import assistant_prices as prices
from assistant_store import Store
from extension_assistant import Assistant
from test_assistant import context


# Independently transcribed from DOC477–537, before model generation.
CASES = [
    ('Установить смеситель', 2000, 3000, 'штуку', 'DOC-L0480'),
    ('Установить сифон', 1000, 2500, 'штуку', 'DOC-L0481'),
    ('Установить полотенцесушитель', 3000, 4000, 'штуку', 'DOC-L0483'),
    ('Установить мойку', 3000, 5000, 'штуку', 'DOC-L0485'),
    ('Герметизация мойки', 1000, 1000, 'точку', 'DOC-L0486'),
    ('Герметизация ванны', 2000, 2000, 'точку', 'DOC-L0492'),
    ('Заменить унитаз', 3500, 6000, 'штуку', 'DOC-L0494'),
    ('Заменить фурнитуру унитаза', 1500, 2500, 'штуку', 'DOC-L0495'),
    ('Заменить шланг', 1500, 2000, 'штуку', 'DOC-L0497'),
    ('Заменить розетку', 1000, 1500, 'штуку', 'DOC-L0502'),
    ('Повесить люстру', 1000, 1500, 'штуку', 'DOC-L0504'),
    ('Монтаж закладной под люстру', 1000, 1500, 'штуку', 'DOC-L0505'),
    ('Установить автомат', 1300, 1500, 'штуку', 'DOC-L0507'),
    ('Проложить силовой кабель', 150, 270, 'погонный метр', 'DOC-L0508'),
    ('Уложить линолеум', 350, 500, 'м²', 'DOC-L0511'),
    ('Уложить ламинат', 600, 800, 'м²', 'DOC-L0512'),
    ('Уложить плинтус на клипсы', 400, 500, 'м²', 'DOC-L0515'),
    ('Уложить плинтус на клей', 500, 600, 'м²', 'DOC-L0516'),
    ('Уложить плинтус на клипсы и клей', 600, 800, 'м²', 'DOC-L0517'),
    ('Уложить потолочную плитку', 400, 600, 'м²', 'DOC-L0518'),
    ('Повесить зеркало', 1000, 1500, 'штуку', 'DOC-L0521'),
    ('Установить кронштейн для телевизора', 1500, 2000, 'штуку', 'DOC-L0522'),
    ('Повесить картину', 400, 800, 'штуку', 'DOC-L0523'),
    ('Повесить полку', 600, 1000, 'штуку', 'DOC-L0524'),
    ('Повесить карниз', 800, 1300, 'штуку', 'DOC-L0525'),
    ('Установить турник', 1200, 1600, 'штуку', 'DOC-L0528'),
    ('Установить сушилку для белья', 2000, 3000, 'штуку', 'DOC-L0531'),
    ('Заменить ручку межкомнатной двери', 2500, 4000, 'штуку', 'DOC-L0533'),
    ('Заменить замок входной двери', 5000, 8000, 'штуку', 'DOC-L0534'),
    ('Регулировка пластикового окна', 1500, 2500, 'штуку', 'DOC-L0536'),
    ('Заменить ручку окна', 5000, 8000, 'штуку', 'DOC-L0537'),
]


def row(text, direction='in', mid='client'):
    return dict(id=mid, direction=direction, body=text)


def known(city='Орск', direction='mnc'):
    return dict(direction=direction, city=city, partner='7', channel='avito')


def third(job='Повесить люстру'):
    return [row(job + '. Сколько стоит?', mid='job'),
            row('Точную стоимость скажу после осмотра.', 'out', 'first'),
            row('А какая цена?', mid='second-ask'),
            row('Стоимость зависит от объёма, нужно посмотреть.', 'out', 'second'),
            row('Назовите конкретную стоимость.', mid='third-ask')]


class MncFixedPrices139Tests(unittest.TestCase):
    def test_all_primary_rows_keep_their_actual_unit_and_both_columns(self):
        for job, ordinary, moscow, unit, ref in CASES:
            for city, amount in [('Орск', ordinary), ('Москва', moscow)]:
                with self.subTest(job=job, city=city):
                    t = prices.mnc_fixed_tariff([row(job)], known(city))
                    self.assertIsNotNone(t); self.assertEqual(t['amount'], amount)
                    self.assertEqual(t['unit'], unit); self.assertIn(ref, t['rules'])

    def test_first_and_second_stages_are_not_advanced_by_unsent_drafts(self):
        rows = third()
        for cut in (1, 3):
            out = prices.answer(rows[:cut], known(), '\n'.join(m['body'] for m in rows[:cut] if m['direction']=='in'))
            self.assertFalse(out['amounts'])
        out = prices.answer(rows, known(), '\n'.join(m['body'] for m in rows if m['direction']=='in'))
        self.assertEqual(out['amounts'], [1000]); self.assertIn('за штуку', out['reply'])
        self.assertNotIn('от 1000', out['reply']); self.assertIn('DOC-L0504', out['rules'])

    def test_third_stage_is_specific_service_price_not_family_floor(self):
        for job, ordinary, moscow, unit, ref in CASES:
            for city, amount in [('Орск', ordinary), ('Москва', moscow)]:
                with self.subTest(job=job, city=city):
                    rows = third(job)
                    out = prices.answer(rows, known(city), '\n'.join(m['body'] for m in rows if m['direction']=='in'))
                    self.assertEqual(out.get('tariff_kind'), 'fixed_service_unit', out)
                    self.assertEqual(out['amounts'], [amount]); self.assertIn(ref, out['rules'])
                    self.assertIn('за '+unit, out['reply']); self.assertIn('без учёта материалов', out['reply'])

    def test_symptom_or_customer_hypothesis_cannot_select_an_installation_price(self):
        for job in ['Люстра не горит', 'Розетка не работает', 'Течёт смеситель',
                    'Может, потребуется заменить смеситель', 'Если нужно заменить розетку, сколько стоит?',
                    'Не нужно повесить люстру', 'Не надо менять смеситель',
                    'Мастер сказал: «Повесить люстру»', 'Раньше хотел повесить люстру',
                    'Сам повесить люстру смогу', 'Повесить люстру буду сам']:
            with self.subTest(job=job): self.assertIsNone(prices.mnc_fixed_tariff([row(job)], known()))

    def test_qualified_cable_and_typed_electrical_work_do_not_cover_internet_cable(self):
        for job in ['Проложить кабель', 'Проложить оптоволокно', 'Проложить сетевой кабель',
                    'Нарастить провод выключателя', 'Соединить провод розетки']:
            with self.subTest(job=job): self.assertIsNone(prices.mnc_fixed_tariff([row(job)], known()))

    def test_multiple_rates_do_not_turn_into_one_order_total(self):
        for job in ['Повесить люстру и установить закладную', 'Повесить зеркало и полку',
                    'Установить смеситель и сифон', 'Повесить люстру и собрать люстру',
                    'Повесить люстру и заменить розетку']:
            with self.subTest(job=job):
                self.assertIsNone(prices.mnc_fixed_tariff([row(job)], known()))
                rows=third(job);out=prices.answer(rows,known(),job)
                self.assertNotEqual(out.get('tariff_kind'),'fixed_service_unit')

    def test_unknown_geography_or_other_direction_does_not_get_mnc_fixed_price(self):
        for city, direction in [('', 'mnc'), ('Неизвестный город', 'mnc'), ('Москва и МО', 'mnc'),
                                ('Москва', 'kp'), ('Орск', 'bt')]:
            self.assertIsNone(prices.mnc_fixed_tariff([row('Повесить люстру')], known(city,direction)))

    def test_known_moscow_administrative_city_uses_moscow_column(self):
        self.assertEqual(prices.mnc_fixed_tariff([row('Повесить люстру')],known('Зеленоград'))['amount'],1500)

    def test_moscow_map_column_also_applies_to_its_named_regional_branches(self):
        for city in ['Подольск','Балашиха','Жуковский']:
            for job,_,msk,_,_ in CASES:
                with self.subTest(city=city,job=job):
                    self.assertEqual(prices.mnc_fixed_tariff([row(job)],known(city))['amount'],msk)
        rows=[row('Установить плинтус на саморезы'),row('Плинтус на саморезы 400 рублей за квадратный метр','out','q'),row('Да',mid='yes')]
        self.assertFalse(prices.prior_quote_verified(rows,known('Подольск'),prices.consent(rows),manual=True))

    def test_valid_human_unit_prices_are_checked_independently_of_bot_stage(self):
        for job, amount, _, unit, ref in CASES:
            with self.subTest(job=job):
                rows=[row(job,mid='job'),row(f'Стоимость услуги — {amount} рублей за {unit}, без учёта материалов.','out','quote'),row('Да, устраивает',mid='yes')]
                state=prices.consent(rows)
                self.assertTrue(prices.prior_quote_verified(rows,known(),state,manual=True))
                self.assertIn(ref,prices.mnc_fixed_quote(rows,known(),state)['rules'])

    def test_other_service_units_amounts_parts_and_bundles_stay_unverified(self):
        for quote in ['Установка люстры 1500 рублей за штуку', 'Установка сифона 1000 рублей за штуку',
                      'Ремонт люстры 1000 рублей', '1000 рублей за час', '1000 рублей за метр',
                      '1000 рублей за всё', '1000 рублей, все материалы включены',
                      '1000 рублей с материалами', '1000 рублей с учётом материалов',
                      '1000 рублей за две штуки', '1000 рублей за 2 люстры',
                      '1000 рублей, максимум 1000 рублей']:
            rows=[row('Повесить люстру'),row(quote,'out','q'),row('Да',mid='yes')]
            with self.subTest(quote=quote):
                self.assertFalse(prices.prior_quote_verified(rows,known(),prices.consent(rows),manual=True))

    def test_multiple_pieces_require_unit_in_a_fixed_human_quote(self):
        for job in ['Повесить две люстры', 'Повесить картину и крючок']:
            amount=1000 if 'люстр' in job else 400
            for unit, expected in [('',False),(' за штуку',True)]:
                rows=[row(job),row(f'{amount} рублей'+unit,'out','q'),row('Да',mid='yes')]
                with self.subTest(job=job,unit=unit):
                    self.assertEqual(prices.prior_quote_verified(rows,known(),prices.consent(rows),manual=True),expected)

    def test_explicit_named_piece_is_an_actual_unit(self):
        rows=[row('Повесить люстру'),row('1000 рублей за одну люстру','out','q'),row('Да',mid='yes')]
        self.assertTrue(prices.prior_quote_verified(rows,known(),prices.consent(rows),manual=True))

    def test_changed_scope_after_quote_requires_new_verification(self):
        rows=[row('Повесить люстру'),row('1000 рублей за штуку','out','q'),row('Да',mid='yes'),row('Ещё нужно заменить розетку',mid='new')]
        self.assertFalse(prices.prior_quote_verified(rows,known(),prices.consent(rows),manual=True))

    def test_customer_budget_is_not_removed_by_a_correct_fixed_tariff(self):
        rows=[row('Повесить люстру'),row('1000 рублей за штуку','out','q'),row('Не больше 1000 рублей, больше нет',mid='cap')]
        self.assertEqual(prices.consent(rows)['status'],'conditional')

    def test_minimum_from_is_still_distinct_from_the_fixed_installation_tariff(self):
        rows=[row('Повесить люстру'),row('От 1000 рублей, точнее после осмотра.','out','q'),row('Да',mid='yes')]
        self.assertTrue(prices.prior_quote_verified(rows,known(),prices.consent(rows),manual=True))
        self.assertIsNone(prices.mnc_fixed_quote(rows,known(),prices.consent(rows)))

    def test_normal_form_uses_fixed_rule_and_preserves_source_consent(self):
        rows=[row('Повесить люстру'),row('1000 рублей за штуку, без учёта материалов','out','q'),row('Да, устраивает',mid='yes')]
        ctx=dict(convId='synthetic-fixed139',city='Орск',dir='mnc',channel='avito',partner='7',accountTitle='Учебный МНЧ',messages=rows)
        with tempfile.TemporaryDirectory()as tmp:
            out,code=Assistant(Store(tmp+'/db')).handle(dict(owner='offline',action='checklist',ctx=ctx))
        self.assertEqual(code,200);self.assertFalse(out['auto_enabled'])
        self.assertIn('DOC-L0504',out['rule_ids'])
        consent=next(r for r in out['results']if r['key']=='price_consent')
        self.assertTrue(consent['done']);self.assertEqual({r['message_id']for r in consent['evidence']},{'q','yes'})

    def test_materials_excluded_wording_is_not_confused_with_an_inclusion_promise(self):
        for quote in ['1000 рублей за штуку, материалы не включены',
                      '1000 рублей за штуку, не включены материалы',
                      '1000 рублей за штуку, без учёта материалов']:
            rows=[row('Повесить люстру'),row(quote,'out','q'),row('Да',mid='yes')]
            self.assertTrue(prices.prior_quote_verified(rows,known(),prices.consent(rows),manual=True))

    def test_unspecified_bracket_does_not_require_a_tv_to_use_the_bracket_tariff(self):
        tariff=prices.mnc_fixed_tariff([row('Установить кронштейн')],known())
        self.assertEqual(tariff['amount'],1500);self.assertIn('DOC-L0522',tariff['rules'])

    def test_owner_tv_mount_and_bracket_use_one_shared_unit_price(self):
        for job in ['Повесить телевизор на кронштейн', 'Телевизор повесить на кронштейн',
                    'Установить телевизор','Повесить телек','Установить кронштейн и повесить телевизор']:
            for city,amount in [('Орск',1500),('Москва',2000),('Подольск',2000)]:
                with self.subTest(job=job,city=city):
                    out=prices.answer(third(job),known(city),job)
                    self.assertEqual(out['amounts'],[amount]);self.assertIn('за штуку',out['reply'])
                    self.assertIn('OWNER-MNC-TV-MOUNT-PRICE-20261021',out['rules'])
                    rows=[row(job),row(f'{amount} рублей за телевизор','out','q'),row('Да',mid='yes')]
                    self.assertTrue(prices.prior_quote_verified(rows,known(city),prices.consent(rows),manual=True))

    def test_tv_mount_price_does_not_price_repairs_or_change_kp_admission(self):
        import assistant_catalog
        for job in ['Телевизор не включается','Нужно отремонтировать телевизор','Не нужно повесить телевизор']:
            self.assertIsNone(prices.mnc_fixed_tariff([row(job)],known()))
        self.assertEqual(assistant_catalog.choose('Повесить телевизор на кронштейн',known())['status'],'supported')
        self.assertEqual(assistant_catalog.choose('Повесить телевизор на кронштейн',known(direction='kp'))['status'],'agree')
        for quote in ['Настройка телевизора 1500 рублей за штуку','Ремонт телевизора 1500 рублей за штуку']:
            rows=[row('Повесить телевизор'),row(quote,'out','q'),row('Да',mid='yes')]
            self.assertFalse(prices.prior_quote_verified(rows,known(),prices.consent(rows),manual=True))

    def test_neural_finalizer_preserves_the_whole_fixed_price_and_unit(self):
        # Synthetic contract checks exercise the same preview/finalize used
        # by the extension. They are not actual model generations or cases.
        for candidate_kind in ['exact','lower_price','wrong_unit','materials','guarantee']:
            with self.subTest(candidate_kind=candidate_kind), tempfile.TemporaryDirectory() as tmp:
                app=Assistant(Store(tmp+'/db'))
                ctx=context(third(),convId='synthetic-fixed139-neural',city='Орск',dir='mnc',
                            channel='avito',accountTitle='Павел МНЧ',itemTitle='Мастер на час')
                prepared,code=app.handle(dict(owner='offline',action='preview',ctx=ctx,wording_mode='neural_review'))
                self.assertEqual(code,200);self.assertTrue(prepared['pending_model'])
                task=json.loads(prepared['model_task']['task']);fixed=task['fixed_reply']
                self.assertIn('1000 рублей за штуку',fixed)
                self.assertIn('DOC-L0504',{r['id'] for r in task['primary_sources']})
                reply={'exact':fixed,'lower_price':fixed.replace('1000','800'),
                       'wrong_unit':fixed.replace('за штуку','за час'),
                       'materials':fixed.replace('без учёта материалов','все материалы включены'),
                       'guarantee':fixed+' Точно всё сделаю за один визит.'}[candidate_kind]
                review=dict(last_intent='Клиент просит конкретную стоимость навески люстры.',
                            latest_client_meaning='Повторно просит назвать цену.',selected_step_fits=True,
                            evidence_ids=['job','third-ask'],note='Тариф на одну люстру, материалы отдельно.')
                final,code=app.handle(dict(owner='offline',action='finalize',request_id=prepared['request_id'],
                                          revision=prepared['revision'],candidate=dict(reply=reply,needs_operator=False,context_review=review)))
                self.assertEqual(code,200);self.assertFalse(final['auto_enabled'])
                if candidate_kind=='exact':
                    self.assertEqual(final['reply'],fixed);self.assertFalse(final['validation'])
                else:
                    self.assertFalse(final['reply']);self.assertIn('fixed_reply_changed',final['validation'])


if __name__=='__main__':unittest.main()
