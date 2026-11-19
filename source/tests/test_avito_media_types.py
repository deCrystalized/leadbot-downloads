"""Real database envelopes: kind=file, avito_type=voice with a transcript."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "leadbot/brain"))
from extension_assistant import _parse, _unread_media
import personal_media
import assistant_policy
import contact_facts


class AvitoMediaTypeTests(unittest.TestCase):
    def test_generic_file_wrapper_uses_specific_voice_type(self):
        raw = {"attachments": [{"kind": "file", "avito_type": "voice", "media_id": "voice-example"}], "voice_transcript": "В Оренбурге нужно собрать кухню, инструкция есть"}
        self.assertFalse(_unread_media(raw))
        _, messages, known, _ = _parse({"convId": "synthetic-voice", "city": "Оренбург", "dir": "mnc", "partner": "7", "accountTitle": "Григорий МНЧ", "itemTitle": "Сборка мебели", "channel": "avito",
                                       "messages": [{"id": "voice-1", "direction": "in", "body": "", **raw}]})
        self.assertIn("инструкция есть", messages[0]["body"])
        decision = assistant_policy.assess(messages, known, contact_facts.collect(messages, known))
        self.assertNotEqual(decision["action"], "handoff")
        self.assertFalse(messages[0]["unread_media"])

    def test_missing_blank_or_unrelated_transcript_does_not_clear_other_media(self):
        for transcript in (None, "", "   "):
            self.assertTrue(_unread_media({"attachments": [{"kind": "file", "avito_type": "voice"}], "voice_transcript": transcript}))
        for kind in ("image", "video", "file", "location", "appCall"):
            with self.subTest(kind=kind):
                self.assertTrue(_unread_media({"attachments": [{"kind": "file", "avito_type": kind}], "voice_transcript": "Текст голоса"}))

    def test_mixed_voice_and_image_stays_unread(self):
        self.assertTrue(_unread_media({"attachments": [{"kind": "file", "avito_type": "voice"}, {"kind": "image", "avito_type": "image"}], "voice_transcript": "Расшифровка только аудио"}))

    def test_conflicting_specific_types_stay_unknown(self):
        raw = {"kind": "image", "avito_type": "voice"}
        self.assertEqual(personal_media.attachment_kind(raw), "conflicting_types")
        self.assertTrue(_unread_media({"attachments": [raw], "voice_transcript": "Текст"}))
        self.assertFalse(personal_media.metadata({"attachments": [raw]})["reviewable_image"])

    def test_file_image_is_reviewable_but_not_automatically_read(self):
        raw = {"attachments": [{"kind": "file", "avito_type": "image", "media_id": "image-example"}]}
        self.assertTrue(personal_media.metadata(raw)["reviewable_image"])
        self.assertTrue(_unread_media(raw))

    def test_ordinary_aliases_and_contact_card_remain_supported(self):
        for kind in ("audio", "voice_message", "voice_note", "voice"):
            self.assertFalse(_unread_media({"attachments": [{"type": kind}], "voice_transcript": "Распознанная речь"}))
        self.assertFalse(_unread_media({"attachments": [{"kind": "file", "type": "vcard"}]}))


if __name__ == "__main__":
    unittest.main()
