"""Exact image acknowledgements by the active reviewing operator; no inferred facts."""

import re
import json
import secrets
import time

import assistant_policy
from assistant_store import digest

FURNITURE_SIGNS = {
    'detached_bed_joint': ('bed', 'Разъединённый узел кровати'),
    'damaged_fastener_holes': ('wardrobe', 'Повреждённые отверстия креплений шкафа'),
    'detached_drawer_front': ('dresser', 'Отделившийся фасад мебельного ящика'),
}


def attachment_kind(attachment):
    """Avito's generic `file` wrapper does not override its semantic type.

    Specific conflicting types remain unknown; a transcript cannot make a
    photo/video understood. Types are metadata, never proof of image contents.
    """
    if not isinstance(attachment, dict):
        return str(attachment).lower()
    aliases = {"photo": "image", "picture": "image", "audio": "voice",
               "voice_message": "voice", "voice_note": "voice",
               "contact_card": "contact", "vcard": "contact"}
    types = {aliases.get(str(attachment.get(k) or "").lower(), str(attachment.get(k) or "").lower())
             for k in ("type", "kind", "avito_type")}
    specific = types - {"", "file", "attachment"}
    if len(specific) > 1:
        return "conflicting_types"
    return next(iter(specific)) if specific else "file"


def metadata(raw):
    attachments = raw.get("attachments") or []
    if not attachments:
        return {}
    images_only = all(
        isinstance(a, dict) and attachment_kind(a) == "image"
        for a in attachments
    )
    return {"media_signature": digest(attachments), "reviewable_image": images_only, "image_count": len(attachments) if images_only else 0}


def awaiting_voice(raw):
    """Only unfinished ASR, without another unread media kind, can wait.

    Failed/too-long or unknown-status empty audio needs review. A nonempty
    legacy transcript without a status is usable ASR text. Mere attachment
    presence does not prove ASR is running. Never acknowledges image/audio.
    """
    attachments = raw.get('attachments') or []
    if not isinstance(attachments, list):
        return False
    kinds = [attachment_kind(item) for item in attachments]
    status = str(raw.get('voice_transcript_status') or '').lower()
    voice = bool(raw.get('voice') or status or 'voice' in kinds)
    if not voice or any(kind not in ('voice', 'contact') for kind in kinds):
        return False
    # Native LeadChat emits running/done/failed/too_long. The other pending
    # spellings remain supported for existing historical/source adapters.
    return status in ('pending', 'queued', 'processing', 'transcribing', 'running')


def normalize_observations(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {'brand', 'model', 'content_kind', 'device_kind', 'visible_symptom', 'connector_type', 'error_system', 'error_code', 'contact_role', 'contact_phone'}:
        raise ValueError('С фото сохраняются только проверяемые видимые признаки')
    result = {}
    model = value.get('model', '')
    if not isinstance(model, str):
        raise ValueError('Модель должна быть текстом с изображения')
    model = model.strip()
    if model:
        if (not re.fullmatch(r'[A-Za-zА-Яа-яЁё0-9 ._()+/-]{2,80}', model)
                or not re.search(r'[A-Za-zА-Яа-яЁё]', model)
                or model.casefold() in {'a4','а4','a3','а3','xiaomi','hp','canon','epson','brother','samsung','apple','lenovo','asus','acer','polaris','philips','филипс','lg','sony','bosch'}
                or re.search(r'руб|диагноз|\bцена\b|\bтелефон\b', model, re.IGNORECASE)):
            raise ValueError('Укажите видимую модель, а не бренд, формат бумаги, контакт или стоимость')
        result['model'] = model
    kind = value.get('content_kind', '')
    if kind:
        if kind not in ('product_photo','product_card','assembly_diagram','device_label','device_message','contact_note','document_image','other'):
            raise ValueError('Неизвестный тип изображения')
        result['content_kind'] = kind
    if kind == 'document_image' and set(value) - {'content_kind'}:
        raise ValueError('Документ или скриншот не подтверждает модель техники, контакт или диагноз')
    brand = value.get('brand', '')
    if not isinstance(brand, str):
        raise ValueError('Марка должна быть текстом с изображения')
    brand = brand.strip()
    if brand:
        if (kind not in ('product_photo', 'device_label')
                or not re.fullmatch(r"[A-Za-zА-Яа-яЁё0-9 &'’./-]{2,60}", brand)
                or not re.search(r'[A-Za-zА-Яа-яЁё]', brand)
                or re.search(r'руб|диагноз|цена|телефон|https?://|www\.', brand, re.I)
                or re.search(r'\d{4,}', brand)
                or re.search(r'\b[A-Za-zА-Яа-яЁё]+\d{2,}', brand)
                or brand.casefold() == model.casefold()):
            raise ValueError('Укажите только видимую марку на фото товара или шильдике, отдельно от модели')
        result['brand'] = brand
    if kind == 'contact_note' or set(value) & {'contact_role', 'contact_phone'}:
        import contact_phone
        phone = value.get('contact_phone', '')
        role = value.get('contact_role', '')
        if (kind != 'contact_note' or role not in ('customer', 'supplier', 'unknown')
                or not isinstance(phone, str) or not contact_phone.normalize(phone)
                or set(value) & {'brand', 'model', 'device_kind', 'visible_symptom', 'connector_type', 'error_system', 'error_code'}):
            raise ValueError('Для контакта укажите один видимый номер и его принадлежность')
        result.update(contact_role=role, contact_phone=phone.strip())
    if kind=='device_message' or value.get('error_code') or value.get('error_system'):
        code=value.get('error_code','');system=value.get('error_system','')
        if (kind!='device_message' or system not in ('xbox_live','windows','printer') or not isinstance(code,str)
                or not re.fullmatch(r'[A-Z0-9][A-Z0-9_.:-]{2,39}',code.strip().upper())
                or code.strip().isdigit() and len(code.strip())>10):
            raise ValueError('Укажите видимую систему и код ошибки; это не диагноз, телефон или инструкция')
        result.update(error_system=system,error_code=code.strip().upper())
    device = value.get('device_kind', '')
    if device:
        if device not in ('pc', 'pc_component', 'monitor', 'tv', 'ethernet_cable', 'oven', 'bed', 'wardrobe', 'dresser') or kind not in ('product_photo', 'device_label'):
            raise ValueError('Укажите основную технику на фотографии или шильдике')
        result['device_kind'] = device
    symptom = value.get('visible_symptom', '')
    if symptom:
        furniture = symptom in FURNITURE_SIGNS and device == FURNITURE_SIGNS[symptom][0]
        screen = symptom in ('screen_bands', 'tv_screen_bands') and device in ('tv', 'monitor') and (symptom != 'tv_screen_bands' or device == 'tv')
        screen = screen or symptom == 'screen_cracks' and device == 'tv'
        if kind != 'product_photo' or not (furniture or screen):
            raise ValueError('Видимый признак относится к указанному экрану или предмету, а не к диагнозу')
        result['visible_symptom'] = symptom
    connector = value.get('connector_type', '')
    if connector:
        if connector != 'RJ45' or device != 'ethernet_cable' or kind != 'product_photo':
            raise ValueError('Тип RJ45 указывают только на фотографии сетевого кабеля')
        result['connector_type'] = connector
    return result


def attach_observation(message, observations, *, source='reviewed_image'):
    """Trusted internal projection; raw extension fields never reach this call."""
    if source not in ('reviewed_image', 'offline_reviewed_image'):
        raise ValueError('Неизвестный источник просмотра')
    observation = normalize_observations(observations)
    if observation:
        message['media_observation'] = dict(observation, source=source,
                                             message_id=message['id'], signature=message.get('media_signature',''))


def reviewed_tv_screen_cracks(message):
    """A bound human observation of glass/screen appearance, never a diagnosis."""
    observation = message.get('media_observation') or {}
    return bool(message.get('direction') == 'in'
                and message.get('sender_type', 'client') in ('client', 'customer', 'user', 'contact', 'lead', '')
                and message.get('media_reviewed') and not message.get('unread_media')
                and message.get('media_signature')
                and observation.get('source') in ('reviewed_image', 'offline_reviewed_image')
                and observation.get('message_id') == message.get('id')
                and observation.get('signature') == message['media_signature']
                and observation.get('content_kind') == 'product_photo'
                and observation.get('device_kind') == 'tv'
                and observation.get('visible_symptom') == 'screen_cracks')


def current_tv_screen_crack_images(messages):
    """An explicit new enquiry/TV does not inherit the prior image's damage."""
    import re
    result = []
    for message in messages:
        body = str(message.get('body') or '')
        client = (message.get('direction') == 'in'
                  and message.get('sender_type', 'client') in ('client', 'customer', 'user', 'contact', 'lead', ''))
        if client and not re.search(r'[«»“”"]|\b(?:сказал|написал|если)\b', body, re.I):
            if re.match(r'\s*(?:(?:новая\s+заявка|новый\s+заказ|по\s+другому\s+вопросу)\s*[:.!—-]|'
                        r'(?:теперь\s+)?(?:другой|второй)\s+телевизор\s*[:.!—-])', body, re.I):
                result = []
        if reviewed_tv_screen_cracks(message):
            result.append(message)
    return result


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS personal_media_reviews (
        scope TEXT, chat TEXT, message_id TEXT, signature TEXT, policy TEXT,
        operator TEXT, reviewed REAL, observations TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY(scope,chat,message_id,signature,policy))""")
    if 'observations' not in {row[1] for row in db.execute('PRAGMA table_info(personal_media_reviews)')}:
        db.execute("ALTER TABLE personal_media_reviews ADD COLUMN observations TEXT NOT NULL DEFAULT '{}'")


def apply(store, scope, chat, messages):
    if not any(m.get("unread_media") and m.get("reviewable_image") for m in messages):
        return
    with store.connect() as db:
        schema(db)
        reviewed = {
            (r["message_id"], r["signature"]): r['observations']
            for r in db.execute(
                "SELECT message_id,signature,observations FROM personal_media_reviews WHERE scope=? AND chat=? AND policy=?",
                (scope, chat, assistant_policy.VERSION),
            )
        }
    for m in messages:
        if m.get("direction") == "in" and m.get("reviewable_image") and (
            m["id"], m.get("media_signature")
        ) in reviewed:
            m.update(unread_media=False, media_reviewed=True)
            try:
                attach_observation(m, json.loads(reviewed[(m['id'], m['media_signature'])]))
            except (ValueError, TypeError):
                # Corrupt or future observations cannot become facts.
                m.update(unread_media=True, media_reviewed=False)


def pending(messages):
    return [
        {"message_id": m["id"], "signature": m["media_signature"], "created_at": m["created_at"]}
        for m in messages
        if m.get("direction") == "in" and m["id"] and m.get("unread_media") and m.get("reviewable_image")
    ]


def confirm(store, owner, scope, session, chat, messages, known, revision, body):
    denied = {"ok": False, "auto_enabled": False, "code": "media_review",
              "error": "Изображение, история или подтверждение просмотра изменились"}
    version = str(body.get("client_version") or "")
    if (
        not session.get("active") or session.get("execution_mode") != "review"
        or known.get("assignee_id") != session["operator_id"]
        or known.get("channel", "").lower().startswith("max")
        or body.get("confirmed") is not True or body.get("policy_ack") != assistant_policy.VERSION
        or body.get("revision") != revision
        or not re.fullmatch(r"\d+\.\d+\.\d+", version)
        or tuple(map(int, version.split("."))) < (2, 7, 3)
    ):
        return denied
    target = next((m for m in pending(messages)
                   if m["message_id"] == body.get("message_id")
                   and m["signature"] == body.get("media_signature")), None)
    if not target:
        return denied
    try:
        observation = normalize_observations(body.get('observations'))
        raw = next(m for m in messages if m['id'] == target['message_id'])
        if observation and tuple(map(int, version.split('.'))) < (2,7,9):
            raise ValueError('Для фактов с изображения обновите расширение')
        if observation.get('brand') and tuple(map(int, version.split('.'))) < (2,8,12):
            raise ValueError('Для марки с изображения обновите расширение до 2.8.12')
        if observation.get('content_kind') == 'document_image' and tuple(map(int, version.split('.'))) < (2,8,13):
            raise ValueError('Для документа на изображении обновите расширение до 2.8.13')
        if observation.get('content_kind')=='device_message' and tuple(map(int,version.split('.'))) < (2,7,23):
            raise ValueError('Для кода с экрана обновите расширение до 2.7.23')
        if set(observation) & {'device_kind','visible_symptom','connector_type'} and tuple(map(int,version.split('.'))) < (2,7,14):
            raise ValueError('Для признаков техники с изображения обновите расширение до 2.7.14')
        if (observation.get('device_kind') in ('oven','bed','wardrobe','dresser')
                and tuple(map(int,version.split('.'))) < (2,7,16)):
            raise ValueError('Для признаков мебели и духовки обновите расширение до 2.7.16')
        if (observation.get('content_kind') == 'contact_note' or observation.get('device_kind') == 'pc_component') and tuple(map(int,version.split('.'))) < (2,8,4):
            raise ValueError('Для контакта на фото или отдельной платы обновите расширение до 2.8.4')
        if observation and raw.get('image_count') != 1:
            raise ValueError('Факты должны относиться к одному конкретному изображению')
    except (ValueError, TypeError) as error:
        return dict(denied, code='media_observation', error=str(error))
    now = time.time()
    with store.connect() as db:
        schema(db)
        db.execute("BEGIN IMMEDIATE")
        live = db.execute("SELECT * FROM personal_sessions WHERE scope=?", (digest(owner),)).fetchone()
        nonce = str(body.get("activation_nonce") or "")
        if (not live or live["sid"] != session["browser_session"]
            or live["operator"] != session["operator_id"] or live["expires"] <= now
            or live["execution_mode"] != "review" or live["mode_epoch"] != session["mode_epoch"]
            or len(nonce) < 20 or not secrets.compare_digest(nonce, live["activation_nonce"])):
            return denied
        next_nonce = secrets.token_urlsafe(24)
        db.execute("INSERT OR IGNORE INTO personal_media_reviews (scope,chat,message_id,signature,policy,operator,reviewed,observations) VALUES (?,?,?,?,?,?,?,?)",
                   (scope, chat, target["message_id"], target["signature"], assistant_policy.VERSION, session["operator_id"], now,json.dumps(observation,ensure_ascii=False)))
        db.execute("UPDATE personal_sessions SET activation_nonce=? WHERE scope=?", (next_nonce, digest(owner)))
    return {"ok": True, "auto_enabled": False, "media_reviewed": True,
            "message_id": target["message_id"], "signature": target["signature"],
            "observations": observation,
            "activation_nonce": next_nonce, "revision": revision}
