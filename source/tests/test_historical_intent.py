"""Semantic failures found by reading full historical conversations."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "leadbot/brain"))
import assistant_policy as policy
import contact_facts


def msg(body, direction="in"):
    return {"body": body, "direction": direction}


class HistoricalIntentTests(unittest.TestCase):
    def assess(self, messages, city="Омск"):
        known = {"direction": "mnc", "city": city, "partner": "7", "account_name": "Георгий МНЧ", "title": "Мастер на час", "channel": "avito"}
        return policy.assess(messages, known, contact_facts.collect(messages, known))

    def test_client_farewell_after_booking_someone_else_never_reopens_collection(self):
        messages = [msg("Нужно повесить два зеркала"), msg("Здравствуйте, какая стена?", "out"),
                    msg("Пеноблок"), msg("Адрес и номер подскажите?", "out"),
                    msg("Я записался у другого матсера"), msg("Всего доброго", "out"), msg("До свидания")]
        result = self.assess(messages)
        self.assertEqual(result["action"], "wait")
        self.assertFalse(result["forced_reply"])

    def test_explicit_other_master_declines_without_repeated_questions(self):
        for text in ("Я записался у другого мастера", "Записалась у другого специалиста", "Нашли другого мастера", "Я записался у другого матсера"):
            with self.subTest(text=text):
                result = self.assess([msg("Собрать кухню"), msg("Здравствуйте!", "out"), msg(text)])
                self.assertEqual(result["action"], "wait")
                self.assertTrue(result["crm_flags"]["customer_declined"])
                self.assertNotIn("?", result["forced_reply"])

    def test_thanks_after_farewell_is_wait_but_new_request_is_not(self):
        prefix = [msg("Собрать кухню в Омске"), msg("Всего доброго", "out")]
        self.assertEqual(self.assess(prefix + [msg("Спасибо!")])["action"], "wait")
        self.assertNotEqual(self.assess(prefix + [msg("Спасибо! Ещё нужна сборка шкафа")])["action"], "wait")

    def test_region_disclaimer_survives_followup_question_until_city_is_known(self):
        messages = [msg("Нужно установить смеситель"), msg("Здравствуйте, когда удобно?", "out"),
                    msg("Извините, не ваш регион"), msg("А вы где находитесь?", "out"), msg("Пермский край")]
        result = self.assess(messages, "Краснокамск")
        self.assertEqual(result["action"], "handoff")
        self.assertFalse(result["forced_reply"])
        self.assertIn("регион", result["reason"])

    def test_concrete_city_correction_resolves_old_disclaimer(self):
        messages = [msg("Нужно установить смеситель"), msg("Извините, не ваш регион"),
                    msg("Какой город?", "out"), msg("Ошиблась, я в Краснокамске")]
        self.assertNotEqual(self.assess(messages, "Краснокамск")["action"], "handoff")

    def test_region_without_city_is_not_a_phone_collection_step(self):
        result = self.assess([msg("Нужно собрать кухню"), msg("Где вы находитесь?", "out"), msg("Пермский край")], "Краснокамск")
        self.assertEqual(result["action"], "handoff")
        self.assertIn("регион", result["reason"].lower())

    def test_client_mentions_someone_else_without_declining_is_not_cancelled(self):
        result = self.assess([msg("Мастер другой сломал шкаф, нужен ремонт в Омске")])
        self.assertFalse(result["crm_flags"].get("customer_declined"))
        self.assertNotEqual(result["action"], "wait")

    def test_historical_human_price_does_not_become_an_approved_tariff(self):
        messages = [msg("В Омске нужно заменить мойку"), msg("Замена мойки 5000 рублей за штуку", "out"), msg("Поняла")]
        result = self.assess(messages)
        self.assertEqual(result["action"], "handoff")
        self.assertFalse(result["forced_reply"])
        self.assertIn("стоимость не подтверждена", result["reason"])

    def test_acceptance_does_not_validate_wrong_old_price(self):
        messages = [msg("В Омске нужно заменить мойку"), msg("Замена мойки 5000 рублей за штуку", "out"), msg("Согласна")]
        self.assertEqual(self.assess(messages)["action"], "handoff")

    def test_special_document_request_is_not_silently_promised(self):
        for text in ("Холодильник после перенапряжения, нужен акт для управляющей компании", "Сможете выдать заключение для страховой? Холодильник сломался"):
            result = self.assess([msg(text)])
            self.assertEqual(result["action"], "handoff")
            self.assertFalse(result["forced_reply"])
            self.assertIn("документ", result["reason"])

    def test_document_negation_does_not_invent_a_special_requirement(self):
        result = self.assess([msg("Собрать кухню в Омске, акт не нужен")])
        self.assertNotIn("документ", result["reason"])

    def test_customer_reported_phone_appointment_is_not_a_new_request(self):
        rows = [msg("Принтер не подключается"), msg("Можно позвонить через Авито?"),
                msg("Обещали с 10.00 до 10.30 в это время подъехать")]
        result = self.assess(rows)
        self.assertEqual(result["action"], "handoff")
        self.assertIn("существующей заявке", result["reason"])
        self.assertFalse(result["forced_reply"])
        self.assertNotIn("существующей заявке", self.assess([msg("Вы обещаете приехать? Нужно собрать шкаф в Омске")])["reason"])

    def test_avito_form_payment_option_is_not_a_previous_warranty_claim(self):
        form = ('Монтаж шведской стенки\nКак бы хотели оплатить:\n'
                'Онлайн с\u00a0«Защитой\u00a0сделки» и\u00a0бесплатной гарантией\n'
                'Скажите, сколько это будет стоить?\n'
                'Задача составлена по  ответам клиента в  анкете')
        result = self.assess([msg(form)])
        self.assertNotIn("существующей заявке", result["reason"])
        for complaint in (" Нужен ремонт по гарантии", " Где мастер?", " Хочу вернуть деньги"):
            self.assertIn("существующей заявке", self.assess([msg(form + complaint)])["reason"])
        self.assertIn("существующей заявке", self.assess([msg('Онлайн с «Защитой сделки» и бесплатной гарантией')])["reason"])

    def test_absent_customer_is_not_replaced_by_an_unconfirmed_worker_contact(self):
        rows = [msg("В Омске нужно установить мойку, на адресе работают ремонтники"),
                msg("Я не смогу присутствовать. Живу в другом городе"),
                msg("Вот телефон работника, он откроет дверь")]
        result = self.assess(rows)
        self.assertEqual(result["action"], "handoff")
        self.assertIn("DOC-L0798", result["rule_ids"])
        self.assertFalse(result["forced_reply"])
        self.assertNotIn("DOC-L0798", self.assess(rows + [msg("Я смогу присутствовать")])["rule_ids"])
        self.assertIn("DOC-L0798", self.assess(rows + [msg("Возможно, я смогу присутствовать")])["rule_ids"])

    def test_sports_installation_price_uses_primary_rule_not_an_old_human_quote(self):
        import assistant_prices
        known = {"direction": "mnc", "city": "Омск", "partner": "7"}
        rows = [msg("Монтаж шведской стенки, сколько стоит?"), msg("Точно после осмотра", "out"),
                msg("Примерно сколько?"), msg("После осмотра", "out"), msg("От какой суммы?")]
        result = assistant_prices.answer(rows, known, "Монтаж шведской стенки")
        self.assertEqual(result["amounts"], [1200])
        self.assertIn("DOC-L0527", result["rules"])
        self.assertIn("за штуку", result["reply"])


if __name__ == "__main__":
    unittest.main()
