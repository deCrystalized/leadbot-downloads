"""Device models must not be inferred from measurements in a customer message."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "leadbot/brain"))
import qualification_state as qs


def message(body, direction="in", mid="1"):
    return {"id": mid, "direction": direction, "body": body}


class ModelEvidenceTests(unittest.TestCase):
    def test_live_paper_size_is_not_printer_model(self):
        text = (
            "Здравствуйте! Подскажите, вы занимаетесь настройкой принтеров? "
            "Подключила его к ноутбуку, но не могу выбрать нужный формат. "
            "Мне нужно печатать на листах 10x15, а в настройках доступен только А4. "
            "Помогите, пожалуйста."
        )
        self.assertEqual(qs.inspect([message(text)])["model"]["status"], "missing")

    def test_measurements_and_addresses_do_not_answer_model_question(self):
        for text in (
            "10x15", "10х15", "10x15см", "А4", "A10", "16GB", "8гб",
            "220В", "50Hz", "24дюйма", "12к2", "кв15", "Windows10",
        ):
            with self.subTest(text=text):
                state = qs.inspect([
                    message("Марку и модель подскажите?", "out"),
                    message(text, mid="2"),
                ])
                self.assertEqual(state["model"]["status"], "missing")
                self.assertEqual(state["model"]["asked"], 1)

    def test_real_model_after_paper_size_is_found_with_exact_evidence(self):
        for text, expected in (
            ("Листы 10x15, принтер Canon G3411", "G3411"),
            ("Стиральная машина Samsung WW60A не сливает", "WW60A"),
            ("Принтер Epson L3150", "L3150"),
            ("Ноутбук HP 15s-eq", "15s-eq"),
            ("Телефон Samsung A51", "A51"),
            ("Телефон Samsung A10", "A10"),
            ("Модель: A10", "A10"),
            ("16GB памяти, модель Lenovo IdeaPad3", "IdeaPad3"),
        ):
            with self.subTest(text=text):
                row = qs.inspect([message(text)])["model"]
                self.assertEqual(row["status"], "answered")
                self.assertEqual(row["value"], expected)
                self.assertIn(row["value"], text)

    def test_yes_does_not_confirm_measurement_as_model(self):
        state = qs.inspect([
            message("У вас модель 10x15?", "out"),
            message("Да", mid="2"),
        ])
        self.assertEqual(state["model"]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
