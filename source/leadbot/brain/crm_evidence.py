"""A staff CRM note is a reason to verify an existing request, not to create one."""
import re

_NOTE_ID = re.compile(r"\s*(\d{6,8})(?:\s+(?:прозвон|гара|гарантия|ут|повтор|отказ|на\s+прозвоне|на\s+прозвон\s+создал|создан[ао]?|создали\s+по\s+другому\s+источнику|дубль|есть(?:\s+другой\s+источник|\s+заявка|\s+уже(?:\s+пациент)?)?))?\s*", re.IGNORECASE)
_LABEL = re.compile(r"\b(?:заявк\w*|заказ\w*)\s*(?:CRM|№|#|:)?\s*(\d{6,8})(?!\d)", re.IGNORECASE)
_OUT_ID = re.compile(r"\s*(\d{6,8})\s+(?:на\s+прозвон(?:е|\s+создал)|есть\s+заявка)\s*", re.IGNORECASE)
_OUT_LABEL = re.compile(r"\s*(?:есть\s+)?(?:заявка|заказ)\s*(?:CRM|№|#|:)?\s*(\d{6,8})\s*", re.IGNORECASE)


def note_references(messages):
    hints = []
    for message in messages:
        if message.get("sender_type") != "operator":
            continue
        text = str(message.get("body") or message.get("text") or "")
        if message.get("direction") == "note":
            match = _NOTE_ID.fullmatch(text) or _LABEL.search(text)
        elif message.get("direction") == "out":
            # A historical staff message may accidentally expose a queue ID.
            # It is only a lookup candidate, never proof of a created order.
            match = _OUT_ID.fullmatch(text) or _OUT_LABEL.fullmatch(text)
        else:
            continue
        if match:
            hints.append({"message_id": str(message.get("id") or "")[:200], "request_id_candidate": match[1], "quote": text[:500]})
    return hints
