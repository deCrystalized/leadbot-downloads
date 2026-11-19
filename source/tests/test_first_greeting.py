"""The first delivered operator reply must greet, on every reply generation path."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "leadbot/brain"))
import assistant_policy as policy
from assistant_store import Store
from extension_assistant import Assistant


def message(body, direction="in", mid="1", **extra):
    return {"id": mid, "body": body, "direction": direction, **extra}


class FirstGreetingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Assistant(Store(str(Path(self.temp.name) / "test.sqlite")))

    def tearDown(self):
        self.temp.cleanup()

    def preview(self, messages, **extra):
        ctx = {
            "convId": "synthetic-first-greeting",
            "city": "Оренбург", "dir": "mnc", "partner": "7",
            "accountTitle": "Григорий МНЧ", "itemTitle": "Сборка и ремонт мебели",
            "channel": "avito", "messages": messages, **extra,
        }
        out, status = self.app.handle({"owner": "test-greeting", "action": "preview", "ctx": ctx})
        self.assertEqual(status, 200)
        return out

    def test_live_first_price_answer_greets_despite_avito_system_notice(self):
        out = self.preview([
            message("Здравствуйте, кухонный гарнитур собрать цена от чего зависит? Эскиз кухни есть."),
            message('[Системное сообщение] Ассистент Авито ответил: "Здравствуйте!"', "system", "2"),
        ])
        self.assertTrue(out["reply"].startswith("Здравствуйте! "))
        self.assertIn("Точную стоимость скажу после осмотра.", out["reply"])
        self.assertEqual(out["reply"].count("Здравствуйте"), 1)

    def test_first_reviewed_question_greets(self):
        with patch.dict(os.environ, {"LEADBOT_ASSISTANT_WORDING": "reviewed"}):
            out = self.preview([message("Компьютер не включается в Оренбурге")],
                               dir="kp", accountTitle="Тест КП", itemTitle="Компьютерная помощь")
        self.assertTrue(out["reply"].startswith("Здравствуйте! "))
        self.assertFalse(out["validation"])

    def test_first_refusal_greets(self):
        out = self.preview([message("Ремонт газовой плиты в Оренбурге")],
                           dir="bt", accountTitle="Тест БТ", itemTitle="Ремонт бытовой техники")
        self.assertEqual(out["action"], "refuse")
        self.assertTrue(out["reply"].startswith("Здравствуйте! "))

    def test_follow_up_reply_does_not_greet_again(self):
        out = self.preview([
            message("Нужна сборка кухни в Оренбурге, схема есть."),
            message("Здравствуйте! Схема сборки есть?", "out", "2"),
            message("Сколько стоит?", mid="3"),
        ])
        self.assertTrue(out["reply"])
        self.assertNotIn("Здравствуйте", out["reply"])

    def test_model_and_fallback_replies_receive_one_server_greeting(self):
        for index, candidate in enumerate(("Марку и модель подскажите?", "Здравствуйте! Марку и модель подскажите?", None)):
            with self.subTest(candidate=candidate):
                prepared = self.preview([message("Компьютер не включается в Оренбурге")],
                                        convId=f"synthetic-model-{index}", dir="kp",
                                        accountTitle="Тест КП", itemTitle="Компьютерная помощь")
                args = {"owner": "test-greeting", "action": "finalize", "request_id": prepared["request_id"], "revision": prepared["revision"]}
                if candidate is None:
                    args["model_failure"] = "transport"
                else:
                    args["candidate"] = {"reply": candidate, "needs_operator": False}
                out, _ = self.app.handle(args)
                self.assertTrue(out["reply"].startswith("Здравствуйте! "))
                self.assertEqual(out["reply"].count("Здравствуйте"), 1)
                self.assertFalse(out["validation"])

    def test_validator_rejects_missing_first_and_repeated_greetings(self):
        first = {"action": "draft", "greeting_required": True, "greeting_allowed": True}
        self.assertIn("missing_first_greeting", policy.validate_reply("Какой у вас город?", first, {"contact_phone_to_use": ""}))
        later = {"action": "draft", "greeting_required": False, "greeting_allowed": False}
        self.assertIn("repeated_greeting", policy.validate_reply("Доброе утро! Какой у вас город?", later, {"contact_phone_to_use": ""}))


if __name__ == "__main__":
    unittest.main()
