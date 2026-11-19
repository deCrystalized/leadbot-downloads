"""Owner amendment129: MNC callout and exact BT inheritance boundaries."""
import unittest
import assistant_catalog as catalog
import assistant_prices as prices
import test_diagnostic_reasoning119 as native


def rows(*turns):
    return [dict(id=str(i), direction=d, body=t) for i, (d, t) in enumerate(turns)]


class MncScope129Tests(unittest.TestCase):
    def test_diagnostic_only_does_not_quote_a_separate_mnc_fee(self):
        ms = rows(('in', 'Нужна только диагностика без ремонта. Сколько стоит?'))
        for partner in ('7', '723', '748', '340', ''):
            out = prices.answer(ms, dict(direction='mnc', city='Абакан', partner=partner), '')
            self.assertEqual(out['amounts'], [])
            self.assertIn('Выезд в черте города бесплатный.', out['reply'])
            self.assertNotIn('диагностика', out['reply'].lower())
            self.assertIn('OWNER-MNC-FREE-CALLOUT-20261021', out['rules'])

    def test_mnc_visit_and_diagnostic_question_has_same_free_callout(self):
        for question in ('Сколько стоит выезд и диагностика?', 'Диагностика платная?', 'Сколько стоит вызов?'):
            ms = rows(('in', question))
            out = prices.answer(ms, dict(direction='mnc', city='Абакан', partner='7'), question)
            self.assertEqual(out['amounts'], [])
            self.assertIn('бесплатный', out['reply'])
            self.assertNotIn('500', out['reply'])

    def test_kp_and_bt_diagnostic_only_keep_minimum500(self):
        ms = rows(('in', 'Нужна только диагностика без ремонта. Сколько стоит?'))
        for direction in ('kp', 'bt'):
            out = prices.answer(ms, dict(direction=direction, partner='7'), '')
            # ID retained; owner223 changes BT only, not KP or MNC scope.
            self.assertEqual(out['amounts'], [500 if direction=='kp' else 800])
            self.assertIn('от 500' if direction=='kp' else 'от 800', out['reply'])

    def test_kp_ordinary_partner_fee_stays1000(self):
        ms = rows(('in', 'Принтер не печатает. Сколько стоит выезд и диагностика?'))
        self.assertEqual(prices.answer(ms, dict(direction='kp', partner='7'), '')['amounts'], [1000])

    def test_mnc_callout_still_requires_city(self):
        for question in ('За выезд берёте?', 'Нужна только диагностика без ремонта. Сколько стоит?'):
            out = prices.answer(rows(('in', question)), dict(direction='mnc', partner='7'), '')
            self.assertIn('handoff', out)
            self.assertNotIn('reply', out)

    def test_mnc_paid_diagnostic_is_not_certified_even_in_manual_mode(self):
        ms = rows(('in', 'Нужна только диагностика без ремонта.'),
                  ('out', 'Диагностика без ремонта — от 500 рублей.'), ('in', 'Да, устраивает'))
        for manual in (False, True):
            self.assertFalse(prices.prior_quote_verified(ms, dict(direction='mnc'), prices.consent(ms), manual=manual))

    def test_appliance_repair_stays_mnc_in_city_without_bt(self):
        out = catalog.choose('Стиральная машина не сливает воду.', dict(direction='mnc', city='Абакан'))
        self.assertEqual(out['status'], 'supported')
        self.assertNotIn('target_direction', out)
        self.assertIn('DOC-L0375', out['rules'])
        self.assertIn('DOC-L0416', out['rules'])

    def test_mnc_inherited_fridge_always_needs_agreement(self):
        out = catalog.choose('Холодильник не морозит.', dict(direction='mnc', city='Абакан'))
        self.assertEqual(out['status'], 'agree')
        self.assertIn('DOC-L0375', out['rules'])

    def test_existing_bt_branch_requires_route_review(self):
        out = catalog.choose('Стиральная машина не сливает воду.', dict(direction='mnc', city='Оренбург'))
        self.assertEqual(out['status'], 'route')
        self.assertEqual(out['target_direction'], 'bt')

    def test_missing_city_does_not_prove_absence_of_bt(self):
        for city in ('', 'Неизвестный город'):
            out = catalog.choose('Стиральная машина не сливает воду.', dict(direction='mnc', city=city))
            self.assertNotEqual(out['status'], 'supported')
            self.assertIn('DOC-L0375', out['rules'])

    def test_connection_is_native_mnc_even_with_bt_branch(self):
        out = catalog.choose('Нужно подключить стиральную машину к воде и сливу.',
                             dict(direction='mnc', city='Оренбург'))
        self.assertEqual(out['status'], 'supported')
        self.assertNotIn('target_direction', out)
        self.assertIn('DOC-L0294', out['rules'])

    def test_mnc_repair_ad_does_not_erase_permitted_inheritance(self):
        known = dict(direction='mnc', account_name='Мастер МНЧ', channel='avito',
                     title='Ремонт стиральных машин', city='Абакан')
        self.assertEqual(catalog.source_direction(known)[0], 'mnc')

    def test_mixed_account_repair_ad_still_resolves_bt(self):
        known = dict(direction='mnc', account_name='БТ/МНЧ', channel='avito',
                     title='Ремонт стиральных машин', city='Абакан')
        self.assertEqual(catalog.source_direction(known)[0], 'bt')


class MncNeuralScope129Tests(unittest.TestCase):
    setUp = native.DiagnosticReasoning119Tests.setUp
    prepare = native.DiagnosticReasoning119Tests.prepare
    candidate = native.DiagnosticReasoning119Tests.candidate
    finish = native.DiagnosticReasoning119Tests.finish

    def check_free_callout_form(self, job):
        ctx = dict(convId='synthetic-mnc-free-form130', city='Оренбург', dir='mnc', channel='avito',
                   partner='7', accountTitle='Учебный мастер', itemTitle='Услуги сантехника', origin='С1',
                   messages=rows(('in', job), ('out', 'Выезд в черте города бесплатный.'),
                                 ('in', 'Да, устраивает')))
        form, code = self.app.handle(dict(owner='owner', action='checklist', dir='mnc', ctx=ctx))
        self.assertEqual(code, 200)
        self.assertFalse(form['auto_enabled'])
        self.assertFalse(any(x['key'] == 'partner_visit_terms' for x in form['results']))
        fee = next((x for x in form['results'] if x['key'] == 'price_consent'), None)
        self.assertTrue(fee is None or fee['done'])

    def test_free_mnc_callout_does_not_require_paid_fee_consent(self):
        self.check_free_callout_form('Нужно заменить розетку. Сколько стоит диагностика?')

    def test_mnc_diagnostic_only_does_not_create_a_paid_fee_gate(self):
        self.check_free_callout_form('Течёт смеситель. Нужна только диагностика без ремонта. Сколько стоит?')

    def test_native_model_and_finalize_use_mnc_callout_proof(self):
        out, task = self.prepare(job='Нужно заменить розетку.',
                                 latest='Нужна только диагностика без ремонта. Сколько стоит?', direction='mnc')
        self.assertNotIn('diagnostic_only_terms', task)
        self.assertEqual(task['mnc_callout_terms']['callout_rub'], 0)
        candidate = self.candidate(task)
        candidate['context_review']['note'] = 'На МНЧ бесплатен выезд, отдельную платную диагностику не озвучиваем. Работа в выезд не включена.'
        candidate['context_review']['mnc_callout_review'] = dict(callout_rub=0, diagnostic_fee_quoted=False, repair_included=False)
        final = self.finish(out, candidate)
        self.assertEqual(final['validation'], [])
        self.assertIn('бесплатный', final['reply'])

    def test_wrong_callout_proof_is_rejected(self):
        out, task = self.prepare(job='Нужно заменить розетку.', latest='Сколько стоит диагностика?', direction='mnc')
        candidate = self.candidate(task)
        candidate['context_review']['mnc_callout_review'] = dict(callout_rub=500, diagnostic_fee_quoted=True, repair_included=True)
        self.assertIn('mnc_callout_review_mismatch', self.finish(out, candidate)['validation'])
