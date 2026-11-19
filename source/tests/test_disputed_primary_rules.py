"""Cases reviewed with actual photos/CRM and the current primary wording."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "leadbot/brain"))
import assistant_catalog as catalog
import assistant_qualifiers as qualifiers
import qualification_state as qs
import contact_facts


def msg(body, direction="in"):
    return {"body": body, "direction": direction}


class DisputedPrimaryRulesTests(unittest.TestCase):
    known = {"direction": "mnc", "city": "Омск", "partner": "7"}

    def test_countertop_cut_is_not_a_technical_hole_in_the_sink(self):
        for text in ("Врезать мойку в столешницу в Омске", "Вырезать отверстие в столешнице под мойку в Омске", "Установить новую мойку, надо пропилить столешницу в Омске"):
            with self.subTest(text=text):
                service = catalog.choose(text, self.known)
                self.assertEqual(service["status"], "supported")
                self.assertEqual(service["items"][0]["id"], "sink")
                self.assertIn("DOC-L0271", service["rules"])
                question = qualifiers.next_question([msg(text)], dict(self.known, service=service), contact_facts.collect([msg(text)], self.known))
                self.assertEqual(question["kind"], "countertop_material")

    def test_actual_hole_in_sink_still_requires_agreement(self):
        for text in ("Врезать отверстие в раковине", "Просверлить саму мойку под смеситель", "Вырезать в мойке отверстие под кран", "Нужна врезка технического отверстия в самой раковине и пропил столешницы"):
            with self.subTest(text=text):
                service = catalog.choose(text, self.known)
                self.assertIn(service["status"], ("agree", "mixed"))
                self.assertTrue(any(item["id"] == "sink-hole" and item["status"] == "agree" for item in service["items"]))

    def test_short_material_answer_is_grounded_in_the_actual_question(self):
        messages = [msg("В Омске нужно врезать мойку"), msg("Из какого материала столешница?", "out"), msg("ДСП")]
        self.assertEqual(qs.inspect(messages)["countertop_material"]["status"], "answered")
        self.assertEqual(qs.inspect([msg("ДСП")])["countertop_material"]["status"], "missing")
        messages[-1] = msg("Не знаю")
        question = qualifiers.next_question(messages, self.known, contact_facts.collect(messages, self.known))
        self.assertTrue(question.get("requires_operator"))

    def test_ordinary_sink_repair_does_not_invent_countertop_cutting(self):
        messages = [msg("В Омске протекает мойка, надо устранить течь")]
        question = qualifiers.next_question(messages, self.known, contact_facts.collect(messages, self.known))
        self.assertNotEqual(question["kind"], "countertop_material")

    def test_automatic_does_not_mean_capsular_in_the_primary_rule(self):
        known = dict(self.known, direction="bt")
        service = catalog.choose("Не работает автоматическая кофемашина", known)
        issue = catalog.condition_issue(service, qs.inspect([msg("Не работает автоматическая кофемашина")]), "Не работает автоматическая кофемашина")
        self.assertIn("не уточнён", issue[0])
        self.assertEqual(issue[1], ["DOC-L0405"])
        capsule = catalog.condition_issue(service, qs.inspect([msg("Не работает капсульная кофемашина")]), "Не работает капсульная кофемашина")
        self.assertEqual(capsule[1], ["DOC-L0406"])


if __name__ == "__main__":
    unittest.main()
