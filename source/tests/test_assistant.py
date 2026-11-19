import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "leadbot/brain"))

import assistant_policy as policy
import assistant_prices as prices
import contact_address
import contact_facts
import contact_phone
from assistant_store import Store
from extension_assistant import Assistant


def message(body, direction="in", mid="m1"):
    return {"id": mid, "body": body, "direction": direction, "sender_type": "client" if direction == "in" else "bot"}


def context(messages=None, **extra):
    return {"convId": "chat-1", "messages": messages or [message("Компьютер не включается, я в Чите")],
            "city": "Чита", "dir": "kp", "partner": "7", "accountTitle": "Денис КП", "itemTitle": "Ремонт компьютеров",
            "adIdentity": "Денис", "origin": "С1", **extra}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "requests.sqlite")
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parallel_claim_once(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            states = list(pool.map(lambda _: Store(self.path).claim("owner", "same", "fp")[0], range(20)))
        self.assertEqual(states.count("claimed"), 1)
        self.assertEqual(states.count("pending"), 19)

    def test_survives_restart_and_payload_collision(self):
        self.store.claim("owner", "r1", "fp")
        self.store.complete("owner", "r1", {"reply": "ответ"})
        self.assertEqual(Store(self.path).claim("owner", "r1", "fp"), ("done", {"reply": "ответ"}))
        self.assertEqual(self.store.claim("owner", "r1", "other")[0], "mismatch")
        self.assertEqual(self.store.claim("other-owner", "r1", "other")[0], "claimed")

    def test_expired_request_never_blindly_reexecuted(self):
        self.store.claim("owner", "r1", "fp", lease=-1)
        self.assertEqual(self.store.claim("owner", "r1", "fp")[0], "interrupted")

    def test_new_revision_fences_old_worker(self):
        first, held = self.store.observe("owner", "chat", "old")
        second, held = self.store.observe("owner", "chat", "new")
        self.assertGreater(second, first)
        self.assertIsNone(self.store.save_draft("owner", "chat", "old", first, {}))
        draft = self.store.save_draft("owner", "chat", "new", second, {"reply": "new"})
        self.assertIsNotNone(draft)
        self.assertIsNone(self.store.draft("other-owner", draft, "new"))

    def test_takeover_and_resume_never_revive_old_draft(self):
        generation, _ = self.store.observe("owner", "chat", "revision")
        draft = self.store.save_draft("owner", "chat", "revision", generation, {"reply": "old"})
        self.store.observe("owner", "chat", "revision", takeover=True)
        self.assertIsNone(self.store.draft("owner", draft, "revision"))
        self.store.resume("owner", "chat", "revision")
        self.assertIsNone(self.store.draft("owner", draft, "revision"))

    def test_one_dialog_worker_and_scoped_release(self):
        self.assertEqual(self.store.acquire_dialog("owner", "chat", "r1"), "claimed")
        self.assertEqual(self.store.acquire_dialog("owner", "chat", "r2"), "busy")
        self.store.release_dialog("owner", "chat", "r2")
        self.assertEqual(self.store.acquire_dialog("owner", "chat", "r3"), "busy")
        self.store.release_dialog("owner", "chat", "r1")
        self.assertEqual(self.store.acquire_dialog("owner", "chat", "r2"), "claimed")


class ContactTests(unittest.TestCase):
    def test_phone_formats_and_no_device_ids(self):
        for value in ["8_999_556_00_00", "+7 (999) 556-00-00", "999 556 00 00", "8.999.556.00.00", "8 999 5560000"]:
            with self.subTest(value=value):
                self.assertEqual(contact_phone.find_first(value).value, "+79995560000")
        for value in ["дом 12 кв 3", "Sony 55 дюймов", "12.05.2026", "заказ 1234567890123"]:
            with self.subTest(value=value):
                self.assertFalse(contact_phone.find_all(value))

    def test_explicit_second_number_is_selected(self):
        f = contact_facts.collect([message("Мой телефон +7 999 556 00 00"),
                                   message("Для связи звоните на +7 999 556 00 01", mid="m2")])
        self.assertEqual(f["contact_phone_to_use"], "+79995560001")
        self.assertEqual(f["evidence"]["contact_phone_to_use"]["message_id"], "m2")

    def test_multiple_unspecified_numbers_need_confirmation(self):
        f = contact_facts.collect([message("+7 999 556 00 00 и +7 999 556 00 01")])
        self.assertTrue(f["phone_needs_confirmation"])
        self.assertEqual(f["contact_phone_to_use"], "")

    def test_invalid_number_correction_does_not_keep_old_number(self):
        f = contact_facts.collect([message("+7 999 556 00 00"), message("Номер неверный, сейчас уточню", mid="m2")])
        self.assertTrue(f["phone_needs_confirmation"])
        self.assertFalse(f["contact_phone_to_use"])

    def test_address_in_fragments(self):
        f = contact_facts.collect([message("Какой адрес?", "out"), message("улица Тестовая", mid="m2"),
                                   message("дом 12", mid="m3"), message("квартира 3, второй подъезд", mid="m4")])
        self.assertEqual(f["address"]["building"], "12")
        self.assertIn("Тестовая", f["address"]["street"])
        self.assertEqual(f["address"]["office"], "3")
        self.assertEqual(f["address"]["entrance"], "2")
        self.assertEqual(f["evidence"]["address.building"]["message_id"], "m3")

    def test_new_address_clears_previous_apartment(self):
        f = contact_facts.collect([message("ул. Тестовая д.12 кв.3"), message("Исправление: ул. Другая д.5", mid="m2")])
        self.assertEqual(f["address"]["building"], "5")
        self.assertNotIn("office", f["address"])
        self.assertFalse(f["address_needs_confirmation"])

    def test_dimensions_are_not_addresses(self):
        f = contact_facts.collect([message("Зеркало 130 на 40 см, телевизор 55 дюймов")])
        self.assertFalse(f["address"])

    def test_contacts_redacted_before_model(self):
        msgs = [message("ул. Тестовая д.12 кв.3, мой номер +7 999 556 00 00")]
        facts = contact_facts.collect(msgs)
        model = json.dumps(contact_facts.redact_for_model(msgs, facts), ensure_ascii=False)
        self.assertNotIn("900", model)
        self.assertNotIn("Тестовая", model)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.assistant = Assistant(Store(str(Path(self.tmp.name) / "db.sqlite")))

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, action="preview", ctx=None, **extra):
        return self.assistant.handle({"owner": "owner-token-id", "action": action, "ctx": ctx or context(), **extra})

    def test_auto_always_disabled(self):
        for action in ["send", "enable", "auto", "crm_write"]:
            with self.subTest(action=action):
                out, status = self.call(action)
                self.assertEqual(status, 403)
                self.assertFalse(out["auto_enabled"])

    def test_normal_draft_only_after_server_validation(self):
        ctx = context([message("Компьютер не включается, я в Чите")])
        prepared, status = self.call(ctx=ctx)
        self.assertTrue(prepared["pending_model"])
        finalized, status = self.call("finalize", request_id=prepared["request_id"], revision=prepared["revision"],
                                     candidate={"reply": "Здравствуйте. Подскажите марку и модель компьютера.", "needs_operator": False})
        self.assertFalse(finalized["auto_enabled"])
        self.assertFalse(finalized["lead"]["can_create_automatically"])
        self.assertFalse(finalized["needs_operator"])
        self.assertTrue(finalized["reply"])

    def test_model_cannot_promise_booking(self):
        prepared, _ = self.call()
        out, _ = self.call("finalize", request_id=prepared["request_id"], revision=prepared["revision"],
                           candidate={"reply": "Уже записал вас, мастер точно будет через час.", "needs_operator": False})
        self.assertEqual(out["reply"], "")
        self.assertTrue(out["needs_operator"])

    def test_same_request_runs_no_second_model(self):
        prepared, _ = self.call()
        again, _ = self.call()
        self.assertTrue(prepared["pending_model"])
        self.assertEqual(again["code"], "pending")

    def test_revision_change_cancels_model_result(self):
        prepared, _ = self.call()
        self.call("observe", context([message("Компьютер не включается, я в Чите"), message("Спасибо, уже не нужно", mid="m2")]))
        out, _ = self.call("finalize", request_id=prepared["request_id"], revision=prepared["revision"],
                           candidate={"reply": "Подскажите марку и модель.", "needs_operator": False})
        self.assertEqual(out["code"], "stale")
        self.assertFalse(out["reply"])

    def test_tv_matrix_refusal_does_not_apply_to_monitor(self):
        out, _ = self.call(ctx=context([message("Телевизор LED, разбита матрица")], itemTitle="Ремонт телевизоров"))
        self.assertEqual(out["action"], "refuse")
        monitor, _ = self.call(ctx=context([message("Разбита матрица монитора")], convId="monitor", itemTitle="Ремонт телевизоров"))
        self.assertNotEqual(monitor["action"], "refuse")

    def test_619_and_620_flags(self):
        out, _ = self.call(ctx=context(partner="619", channel="jivo"))
        self.assertTrue(out["crm_flags"]["callbefore"])
        prepared, _ = self.call(ctx=context(partner="620", convId="620", channel="jivo"))
        self.assertNotIn('"required_text"',prepared["model_task"]["task"])

    def test_operator_pause_invalidates_worker(self):
        prepared, _ = self.call()
        self.call("takeover")
        out, _ = self.call("finalize", request_id=prepared["request_id"], revision=prepared["revision"],
                           candidate={"reply": "Подскажите марку и модель.", "needs_operator": False})
        self.assertEqual(out["code"], "stale")
        self.assertFalse(out["reply"])

    def test_wait_when_operator_already_answered(self):
        out, _ = self.call(ctx=context([message("Компьютер не включается"), message("Что происходит при включении?", "out", "m2")]))
        self.assertEqual(out["action"], "wait")
        self.assertNotIn("pending_model", out)


class PriceTests(unittest.TestCase):
    def test_price_stages_group_bubbles(self):
        history = [message("Установка Windows. Сколько стоит?"), message("Точная цена?", mid="m2")]
        self.assertEqual(prices.price_turns(history), 1)
        history += [message("Нужно посмотреть", "out", "m3"), message("Сколько хотя бы от?", mid="m4")]
        self.assertEqual(prices.price_turns(history), 2)
        self.assertIn("500", prices.answer(history, {"direction": "kp"}, "Установка Windows на ноутбук")["reply"])
        history += [message("От 500", "out", "m5"), message("Точную стоимость Windows скажите", mid="m6")]
        self.assertIn("2000", prices.answer(history, {"direction": "kp"}, "Установка Windows на ноутбук")["reply"])

    def test_duration_is_not_price(self):
        self.assertFalse(prices.asks("Сколько времени занимает установка Windows?"))
        self.assertTrue(prices.asks("Сколько стоит установка Windows?"))

    def test_tariffs_have_primary_source_and_exact_amount(self):
        sources = {s["id"]: s for s in policy.registry()["sources"]}
        for name, scope, pattern, amount, ref in prices.TARIFFS:
            with self.subTest(tariff=name):
                self.assertIn(str(amount), sources[ref]["text"])

    def test_backlight_has_no_fixed_price(self):
        out = prices.answer([message("Сколько стоит замена подсветки телевизора?")], {"direction": "kp"}, "Замена подсветки телевизора")
        self.assertIn("после осмотра", out['reply'])
        self.assertEqual(out['amounts'], [])


class GeographyTests(unittest.TestCase):
    def test_latest_city_states(self):
        self.assertEqual(policy.geography("Ковров", "kp")["crm_city"], "Владимир")
        self.assertTrue(policy.geography("Ковров", "kp")["far_trip"])
        self.assertEqual(policy.geography("Феодосия", "kp")["status"], "known")
        self.assertEqual(policy.geography("Курган", "kp")["status"], "known")
        self.assertEqual(policy.geography("Элиста", "kp")["status"], "needs_confirmation")

    def test_satellite_far_trip_only_explicit_exception(self):
        self.assertFalse(policy.geography("Муром", "kp")["far_trip"])
        self.assertTrue(policy.geography("Воткинск", "kp")["far_trip"])

    def test_mytishchi_polygon_specific_windows(self):
        import territory
        for expected, area in [("north", a) for a in territory.zones()["areas"] if a.get("policy_zone") == "north"] + [("south", a) for a in territory.zones()["areas"] if a.get("policy_zone") == "south"]:
            points = area["ring"]
            selected = None
            lat0, lat1 = min(x[0] for x in points), max(x[0] for x in points)
            lon0, lon1 = min(x[1] for x in points), max(x[1] for x in points)
            for i in range(1, 10):
                for j in range(1, 10):
                    lat, lon = lat0 + (lat1-lat0)*i/10, lon0+(lon1-lon0)*j/10
                    if territory.point_in_ring(lat, lon, points):
                        selected = (lat, lon)
                        break
                if selected:
                    break
            self.assertIsNotNone(selected)
            geo = policy.geography("Мытищи", "kp", *selected)
            self.assertEqual(geo["zone"], expected)
            self.assertEqual(geo["lead"].startswith("три"), expected == "north")


if __name__ == "__main__":
    unittest.main()
