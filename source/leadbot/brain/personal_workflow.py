"""Server authority for explicitly activated, browser-owned personal execution."""
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import assistant_policy
import assistant_catalog
import assistant_prices
import contact_cities
import contact_facts
import personal_assistant
import qualification_state
import dialogue_lifecycle
import own_visit
import experience_runtime
from assistant_store import digest

VERSION = "2"


def enabled(session):
    return personal_assistant.auto_available() and session.get("active") is True and session.get("auto_enabled") is True and session.get("execution_mode") == "auto"


def _live_session_matches(live, session, now, *, reviewed):
    if (not live or live['sid'] != session['browser_session']
            or live['operator'] != session['operator_id']
            or live['principal'] not in ('', session.get('principal_id'))
            or live['expires'] <= now or live['mode_epoch'] != session['mode_epoch']
            or live['execution_mode'] != ('review' if reviewed else 'auto')
            or not personal_assistant.auto_available()):
        return False
    return reviewed or (live['policy_ack'] == assistant_policy.VERSION
        and (os.environ.get('LEADBOT_REQUIRE_ORDERED_CONTROL') != '1' or live['connection_epoch'] > 0))


def grant_schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS workflow_grants (scope TEXT, chat TEXT, slot TEXT, sid TEXT, revision TEXT, expires REAL, epoch INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope,chat,slot))")
    if "epoch" not in {r[1] for r in db.execute("PRAGMA table_info(workflow_grants)")}:
        db.execute("ALTER TABLE workflow_grants ADD COLUMN epoch INTEGER NOT NULL DEFAULT 0")
    if "reviewed" not in {r[1] for r in db.execute("PRAGMA table_info(workflow_grants)")}:
        db.execute("ALTER TABLE workflow_grants ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0")
    db.execute("CREATE TABLE IF NOT EXISTS workflow_crm_requirements (scope TEXT, chat TEXT, fields TEXT, policy TEXT, message_revision TEXT, PRIMARY KEY(scope,chat))")


def prior_native_action(db, chat, slot):
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_workflow_grants'").fetchone()
    return bool(exists and db.execute('SELECT 1 FROM native_workflow_grants WHERE chat=? AND slot=?',
                                     (chat,slot)).fetchone())


def required_crm_fields(messages, known):
    facts = contact_facts.collect(messages, known)
    labels = {"street": "улица", "building": "дом", "office": "квартира", "settlement": "населённый пункт", "entrance": "подъезд", "floor": "этаж"}
    fields = [label for key, label in labels.items() if facts["address"].get(key)]
    partner = str(known.get("partner") or "").lstrip("0")
    if partner in ("7", "340", "624", "723", "748") or known.get("white"):
        fields.append("отзыв")
    if partner == "619" or facts.get("call_before_visit"):
        fields.append("звонок перед выездом")
    if isinstance(facts.get('intercom_present'), bool):
        fields.append('домофон')
    return fields


CRM_CORE_FIELDS = ["город", "вид работ", "вид услуг", "тип", "партнёр", "дата", "время", "комментарий партнёра", "комментарий", "служебный комментарий", "имя / аккаунт объявления", "телефон", "имя клиента"]


def receipt_verified(required, verification, crm_id, messages):
    if not required or not isinstance(verification, dict):
        return False
    fields = verification.get("fields")
    if not isinstance(fields, list) or not all(isinstance(value, str) for value in fields):
        return False
    return (
        verification.get("crm_request_id") == crm_id
        and set(json.loads(required["fields"])).issubset(set(fields))
        and verification.get("diffs") == [] and verification.get("warnings") == []
        and verification.get("policy_version") == required["policy"] == assistant_policy.VERSION
        and verification.get("message_revision") == required["message_revision"] == digest(messages)
    )


def check_started(store, owner, session, chat, revision, expected, planned):
    denied = {"ok": False, "auto_enabled": False, "execution_allowed": False, "error": "Личный аккаунт, данные или разрешение изменились"}
    if not personal_assistant.auto_available() or not session.get("active") or revision != expected or not planned["eligible"] or planned["step"] != "prepare_crm":
        return denied
    with store.connect() as db:
        grant_schema(db)
        try:
            row = db.execute("SELECT * FROM workflow_grants WHERE scope=? AND chat=? AND slot='create_once'", (digest(owner), chat)).fetchone()
            live = db.execute('SELECT * FROM personal_sessions WHERE scope=?', (digest(owner),)).fetchone()
        except sqlite3.OperationalError:
            return denied
    if not row or row["sid"] != session["browser_session"] or row["revision"] != revision or row["expires"] <= time.time() or row["epoch"] != session["mode_epoch"]:
        return denied
    reviewed = row["reviewed"] == 1 and session.get("execution_mode") == "review"
    if (not enabled(session) and not reviewed
            or not _live_session_matches(live, session, time.time(), reviewed=reviewed)):
        return denied
    return {"ok": True, "auto_enabled": enabled(session), "reviewed": reviewed, "execution_allowed": True, "revision": revision, "operator_id": session["operator_id"]}


def validate_operation(store, owner, actor, ctx, known, revision, planned, operation, *, reviewed=False, call_status=None,
                       crm_only=False):
    """Business checks shared by browser and genuine native authorities."""
    denied = {"ok": False, "auto_enabled": False, "execution_allowed": False, "code": "auto_disabled", "error": "Автоматический режим выключен владельцем"}
    if str(known.get("channel") or "").lower().startswith("max"):
        return dict(denied, code="channel_excluded", error="MAX исключён владельцем")
    draft = None
    if not isinstance(operation, dict) or operation.get("revision") != revision:
        return dict(denied, code="stale", error="Действие относится к старым данным")
    if 'preflight_only' in operation and type(operation['preflight_only']) is not bool:
        return dict(denied, code="operation", error="Не подтверждён режим проверки действия")
    preflight_only = operation.get('preflight_only') is True
    kind = operation.get("kind")
    follows = {"link_crm": "link", "rename_client": "rename", "notify_created": "notify"}
    if kind not in ("claim", "reply", "create_crm", *follows):
        return dict(denied, code="operation", error="Неизвестное действие")
    expected = {"claim": "claim", "reply": "reply", "create_crm": "prepare_crm"}
    if kind not in follows and (not planned["eligible"] or planned["step"] != expected[kind] or operation.get("operation_id") != planned["operation_id"]):
        return dict(denied, code="stale", error="Действие не соответствует текущему плану")
    if kind != "claim" and known["assignee_id"] != actor["operator_id"]:
        return dict(denied, code="assignment", error="Диалог не назначен владельцу")
    chat = ctx["convId"]
    if kind == "reply":
        draft = store.draft("assistant:" + digest(owner), str(operation.get("draft_id") or ""), revision, chat)
        if not draft or reviewed and (not operation.get("reply") or operation["reply"] != draft.get("reply")):
            return dict(denied, code="draft", error="Ответ не прошёл проверку свежести или отличается от просмотренного")
        if not experience_runtime.current(draft, store.path, assistant_policy.VERSION):
            return dict(denied, code='experience_changed', error='Проверенный опыт обновился: нужен новый ответ')
        if draft.get('operator_binding') and draft['operator_binding'] != [actor.get('principal_id'), actor['operator_id']]:
            return dict(denied, code='draft_operator', error='Ответ подготовлен для другого автора или администратора')
        if not assistant_policy.visit_offer_is_current(draft, ctx['_parsed_messages'], known):
            return dict(denied, code='time_offer_expired', error='Предложение времени больше не укладывается в часы приёма')
        if (not isinstance(draft.get('reply'), str) or not draft['reply'].strip()
                or draft.get('needs_operator') or draft.get('validation')):
            return dict(denied, code='draft_not_sendable', error='Нет проверенного ответа для отправки: сначала устраните причину остановки')
        if draft.get('requires_operator_review') and not reviewed:
            return dict(denied, code='neural_review_required', error='Этот ответ требует отдельной проверки и одноразового разрешения')
        first_reply = assistant_policy.first_reply_required(ctx["_parsed_messages"])
        if assistant_policy.greeting_violations(
            draft.get("reply"),
            {"greeting_required": first_reply, "greeting_allowed": first_reply},
        ):
            return dict(denied, code="greeting", error="Первый ответ должен начинаться с приветствия; повторное приветствие запрещено")
    if kind == "create_crm":
        messages = ctx["_parsed_messages"]
        call = call_status() if call_status is not None else False
        gate = check_crm(messages, known, dict(ctx, workflowRevision=revision), operation.get("proposal"), call,
                         crm_only=crm_only)
        if not gate.get("ready") or gate.get("snapshot_hash") != operation.get("snapshot_hash"):
            return dict(denied, code="crm_gate", error="Заявка не прошла проверку регламента")
    return dict(ok=True, kind=kind, preflight_only=preflight_only, draft=draft)


def authorize(store, owner, session, ctx, known, revision, planned, operation, review=None):
    """A live owner session must explicitly acknowledge the current policy.

    Prepare-only checks do not grant execution. The final grant is consumed
    before transport, persists across restarts, and is never reissued on timeout.
    Customer/CRM calls stay in the browser.
    """
    denied = {"ok": False, "auto_enabled": False, "execution_allowed": False, "code": "auto_disabled",
              "error": "Автоматический режим выключен владельцем"}
    reviewed = isinstance(review, dict)
    if str(known.get("channel") or "").lower().startswith("max"):
        return dict(denied, code="channel_excluded", error="MAX исключён владельцем")
    if reviewed:
        version = str(review.get("client_version") or "")
        if not personal_assistant.auto_available() or session.get("active") is not True or session.get("execution_mode") != "review" or review.get("confirmed") is not True or review.get("policy_ack") != assistant_policy.VERSION or not re.fullmatch(r"\d+\.\d+\.\d+", version) or tuple(map(int, version.split("."))) < (2, 7, 1):
            return dict(denied, code="review_confirmation", error="Подтвердите один проверенный шаг в актуальном расширении")
    elif not enabled(session):
        return denied
    checked = validate_operation(store, owner, session, ctx, known, revision, planned, operation,
        reviewed=reviewed, call_status=lambda: record_call(store, owner, session, ctx["convId"], revision, False))
    if not checked["ok"]:
        return checked
    kind, preflight_only, draft = checked["kind"], checked["preflight_only"], checked["draft"]
    follows = {"link_crm": "link", "rename_client": "rename", "notify_created": "notify"}
    expected = {"claim": "claim", "reply": "reply", "create_crm": "prepare_crm"}
    chat = ctx["convId"]
    scope = digest(owner)
    opid = str(operation.get("operation_id") or "")
    slot = "create_once" if kind == "create_crm" else kind + ":" + opid
    now = time.time()
    expires = now + min(10, max(0, session.get("lease_seconds", 0)))
    if expires <= now:
        return dict(denied, code="lease", error="Личная сессия истекла")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        grant_schema(db)
        # Planning, source/CRM checks and the write lock can outlive Stop or
        # a mode/reconnect change. A prior lease snapshot cannot mint a new
        # action grant after that change, even when its policy checks passed.
        live = db.execute("SELECT * FROM personal_sessions WHERE scope=?", (scope,)).fetchone()
        now = time.time()
        if not _live_session_matches(live, session, now, reviewed=reviewed):
            return dict(denied, code='workflow_session_changed',
                        error='Личная сессия или режим изменились; действие не запускалось')
        expires = min(now + 10, live['expires'])
        if kind in follows:
            crm_id = str(operation.get("crm_request_id") or "")
            issued = db.execute("SELECT * FROM workflow_grants WHERE scope=? AND chat=? AND slot='create_once'", (scope, chat)).fetchone()
            # Owner: acknowledge one service Telegram post before native close.
            # This is only the current, fully verified creation, never a way to
            # notify for an arbitrary existing order or another browser/epoch.
            before_link = (kind == 'notify_created' and operation.get('before_link') is True
                           and not known['crm_request_id'] and issued is not None
                           and not reviewed and issued['reviewed'] == 0
                           and issued['sid'] == session['browser_session']
                           and issued['epoch'] == session['mode_epoch'])
            if not issued or not re.fullmatch(r"\d{1,12}", crm_id) or opid != follows[kind] + ":" + crm_id or ctx.get("channelAssigned") is not True or ctx.get("conversationStatus") not in personal_assistant.ACTIVE_STATUSES or ctx.get("botActive") is not False or ctx.get("hasTransfer") is not False or (kind != "link_crm" and known["crm_request_id"] != crm_id and not before_link):
                return dict(denied, code="receipt", error="Нет основания для привязки заявки")
            required = db.execute("SELECT * FROM workflow_crm_requirements WHERE scope=? AND chat=?", (scope, chat)).fetchone()
            verification = operation.get("verification")
            if not receipt_verified(required, verification, crm_id, ctx["_parsed_messages"]):
                return dict(denied, code="crm_verification", error="Нет полной сверки созданной заявки с перепиской, включая адрес. Нужен оператор")
        exists = db.execute("SELECT 1 FROM workflow_grants WHERE scope=? AND chat=? AND slot=?", (scope, chat, slot)).fetchone()
        if exists or prior_native_action(db, chat, slot):
            return dict(denied, code="already_started", error="Действие уже могло выполниться. Нужна проверка результата")
        next_nonce = ""
        if reviewed:
            nonce = str(review.get("activation_nonce") or "")
            if not live or live["sid"] != session["browser_session"] or live["operator"] != session["operator_id"] or live["expires"] <= now or live["mode_epoch"] != session["mode_epoch"] or live["execution_mode"] != "review" or len(nonce) < 20 or not secrets.compare_digest(nonce, live["activation_nonce"]):
                return dict(denied, code="review_confirmation", error="Подтверждение устарело или уже использовано")
        if preflight_only:
            return {"ok": True, "auto_enabled": not reviewed, "reviewed": reviewed,
                    "preflight_only": True, "execution_allowed": False, "kind": kind,
                    "operator_id": session["operator_id"], "revision": revision,
                    "mode_epoch": session["mode_epoch"], "expires_at": int(expires * 1000)}
        if reviewed:
            next_nonce = secrets.token_urlsafe(24)
            db.execute("UPDATE personal_sessions SET activation_nonce=? WHERE scope=?", (next_nonce, scope))
        personal_assistant.jobs_schema(db)
        if kind in expected:
            job = db.execute("SELECT active FROM personal_jobs WHERE scope=? AND chat=?", (scope, chat)).fetchone()
            count = db.execute("SELECT count(*) FROM personal_jobs WHERE scope=? AND active=1", (scope,)).fetchone()[0]
            if session["max_dialogs"] > 0 and (not job or not job["active"]) and count >= session["max_dialogs"]:
                return dict(denied, code="capacity", error="Достигнут лимит незавершённых диалогов помощника")
            db.execute("INSERT INTO personal_jobs VALUES(?,?,1,?) ON CONFLICT(scope,chat) DO UPDATE SET active=1,updated=excluded.updated", (scope, chat, now))
        db.execute("INSERT INTO workflow_grants(scope,chat,slot,sid,revision,expires,epoch,reviewed) VALUES (?,?,?,?,?,?,?,?)", (scope, chat, slot, session["browser_session"], revision, expires, session["mode_epoch"], int(reviewed)))
        if kind == 'reply':
            own_visit.anchor(db, 'assistant:' + scope, chat, session['operator_id'], known.get('account_id', ''),
                             opid, draft, ctx['_parsed_messages'], now, expires)
        if kind == "create_crm":
            db.execute("INSERT OR REPLACE INTO workflow_crm_requirements VALUES (?,?,?,?,?)", (scope, chat, json.dumps(CRM_CORE_FIELDS + required_crm_fields(ctx["_parsed_messages"], known)), assistant_policy.VERSION, digest(ctx["_parsed_messages"])))
    return {"ok": True, "auto_enabled": not reviewed, "reviewed": reviewed, "activation_nonce": next_nonce, "execution_allowed": True, "kind": kind,
            "operator_id": session["operator_id"], "revision": revision, "mode_epoch": session["mode_epoch"], "permit": secrets.token_urlsafe(32), "expires_at": int(expires * 1000)}


def plan(messages, known, ctx, session, mine_count, revision, *, allow_visual=False):
    result = plan_for_actor(messages, known, ctx, session["operator_id"], mine_count, revision,
                            max_dialogs=session["max_dialogs"], allow_visual=allow_visual)
    result.update(auto_session_enabled=enabled(session), mode_epoch=session["mode_epoch"])
    return result


def plan_for_actor(messages, known, ctx, operator, mine_count, revision, *, max_dialogs=0, allow_visual=False):
    admission = personal_assistant.screen(messages, known, ctx, operator,
                                         max_dialogs, mine_count, allow_ready=True,allow_visual=allow_visual)
    result = dict(admission, workflow_version=VERSION, revision=revision, message_revision=digest(messages),
                  operator_id=operator, step="handoff", auto_enabled=False,
                  execution_allowed=False, operation_id="", preview_only=True)
    result["crm_required_fields"] = required_crm_fields(messages, known)
    facts = contact_facts.collect(messages, known)
    decision = assistant_policy.assess(messages, known, facts)
    result['lifecycle'] = dialogue_lifecycle.classify(messages, known, decision,
        dialogue_lifecycle.extension_context(ctx, operator))
    if not admission["eligible"]:
        result["step"] = "wait" if admission["action"] == "wait" else "handoff"
        return result
    if admission.get('requires_visual_research'):
        step = 'inspect_media'
    elif admission["scope"] == "free":
        step = "claim"
    elif decision["reason"] == "Данные собраны: оператор проверяет условия и подтверждает заявку":
        step = "prepare_crm"
    else:
        step = "reply"
    result.update(step=step, operation_id=digest([known.get("account_id"), ctx["convId"],
                  revision, operator, step])[:40])
    result["planned_actions"] = ["Отбор без согласований", "Взять на мой аккаунт", "Ответить по регламенту",
                                 "Сверить данные, территорию и историю CRM", "Создать и сверить заявку"]
    return result


def record_call(store, owner, session, chat, revision, confirmed, now=None):
    now = time.time() if now is None else now
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS workflow_calls (scope TEXT, chat TEXT, revision TEXT, operator TEXT, expires REAL, PRIMARY KEY(scope,chat))")
        if confirmed is True:
            db.execute("INSERT OR REPLACE INTO workflow_calls VALUES (?,?,?,?,?)",
                       (digest(owner), chat, revision, session["operator_id"], now + 600))
        row = db.execute("SELECT * FROM workflow_calls WHERE scope=? AND chat=?", (digest(owner), chat)).fetchone()
    return bool(row and row["revision"] == revision and row["operator"] == session["operator_id"] and row["expires"] > now)


def check_crm(messages, known, ctx, proposal, call_confirmed=False, *, crm_only=False):
    """Validate the actual prepared snapshot against dialogue and live CRM/map reads.

    Ordinary primary requests may use fully confirmed chat data under the owner
    amendment. Moderation, approval and mandatory master-call flags still gate
    admission. The legacy call receipt remains for review compatibility only.
    """
    if not isinstance(proposal, dict):
        return {"ok": False, "code": "proposal", "error": "Нет снимка заявки", "auto_enabled": False}
    if any(not isinstance(proposal.get(key), dict) for key in ("lead", "prep", "territory", "sel")) or not isinstance(proposal["lead"].get("addr"), dict):
        return {"ok": False, "code": "proposal", "error": "Неверный формат снимка заявки", "auto_enabled": False}
    facts = contact_facts.collect(messages, known)
    decision = assistant_policy.assess(messages, known, facts)
    reasons = []
    if decision["reason"] != "Данные собраны: оператор проверяет условия и подтверждает заявку":
        reasons.append(decision["reason"] or "Сбор данных ещё не завершён")
    lead = proposal.get("lead") or {}
    prep = proposal.get("prep") or {}
    terr = proposal.get("territory") or {}
    sel = proposal.get("sel") or {}
    if proposal.get("revision") != ctx.get("workflowRevision"):
        reasons.append("Диалог изменился после подготовки заявки")
    digits = lambda value: re.sub(r"\D", "", str(value or ""))[-10:]
    if not facts["contact_phone_to_use"] or digits(lead.get("phone")) != digits(facts["contact_phone_to_use"]):
        reasons.append("Номер заявки не подтверждён перепиской")
    address = facts["address"]
    if address.get('settlement'):
        checked = terr.get('checkedAddress') or {}
        norm = lambda value: re.sub(r'\s+', ' ', str(value or '').casefold().replace('ё', 'е')).strip()
        same_address = isinstance(checked, dict) and all(norm(checked.get(k)) == norm(address.get(k)) for k in ('street', 'building'))
        same_place = isinstance(checked, dict) and norm(address['settlement']) in (norm(checked.get('settlement')), norm(terr.get('verifiedSettlement')))
        if terr.get('address_verified') is not True or not same_address or not same_place:
            reasons.append('Населённый пункт или микрорайон не проверен вместе с улицей и домом')
    if terr.get('mismatch') or terr.get('qualified_location_unverified'):
        reasons.append('Адрес или город не совпадает с проверкой карты: нужен оператор до выбора филиала')
    if not address.get("building") or not (address.get("street") or address.get("settlement")):
        reasons.append("Нет полного подтверждённого адреса")
    for key, value in address.items():
        # The UI checkbox carries presence; the exact entry code has a
        # separate mandatory comment carrier checked below.
        if key not in ("city", "intercom") and value and str((lead.get("addr") or {}).get(key, "")).strip().casefold() != str(value).strip().casefold():
            reasons.append("Адрес заявки отличается от подтверждённого: " + key)
    if facts["phone_needs_confirmation"] or facts["address_needs_confirmation"]:
        reasons.append("Контакты требуют подтверждения")
    if isinstance(facts.get('intercom_present'), bool) and lead['addr'].get('has_intercom') is not facts['intercom_present']:
        reasons.append('Наличие домофона в заявке отличается от слов клиента. Обновите расширение или проверьте отметку')
    # Current qualified client evidence is also the form's name source.
    # A profile label is a fallback, not permission to overwrite that name.
    name_fact = qualification_state.inspect(messages)["client_name"]
    name_row = next((m for m in messages if m.get('id') == name_fact.get('message_id')), {})
    qualified_name = qualification_state.client_name_value(name_fact, name_row)
    name_source = qualified_name or qualification_state.client_name_profile_value(name_fact, known.get('client_name'))
    if not re.fullmatch(r"[А-Яа-яЁёA-Za-z -]{2,60}", str(lead.get("name") or "")):
        reasons.append("Не подтверждено имя клиента")
    elif not re.search(r'(?<![а-яёa-z-])' + re.escape(str(lead['name']).strip()) + r'(?![а-яёa-z-])', str(name_source), re.I):
        reasons.append("Имя заявки отличается от подтверждённого имени клиента")
    if decision["crm_flags"]["review"] and lead.get("review") is not True:
        reasons.append("Не установлен обязательный отзыв")
    if decision["crm_flags"]["callbefore"] and lead.get("call_before_visit") is not True:
        reasons.append("Не установлена отметка звонка перед выездом")
    if lead.get("call_check") or lead.get("far_ride") or lead.get("is_zakrep"):
        reasons.append("Прозвон, дальний выезд и закреп требуют оператора")
    if not str(lead.get("problem") or "").strip() or not str(lead.get("problem") or "").strip().casefold() in str(lead.get("comment") or "").casefold():
        reasons.append("В комментарии нет проверенной сути работы")
    for line in contact_facts.crm_comment_lines(facts):
        if line not in str(lead.get("comment") or ""):
            reasons.append("В комментарии не сохранены подтверждённые ориентиры или код домофона")
    consent = assistant_prices.consent(messages)
    if consent["amount"] and not re.search(r"(?<!\d)" + str(consent["amount"]) + r"(?!\d)", re.sub(r"\s", "", str(lead.get("comment") or ""))):
        reasons.append("В комментарии нет озвученной стоимости")
    if proposal.get("dir") != known["direction"] or proposal.get("allowLive"):
        reasons.append("Нельзя менять базу или обходить дубли автоматически")
    if not prep.get("ok") or not prep.get("cityId") or prep.get("cityId") != sel.get("cityId"):
        reasons.append("Не подтверждён город CRM")
    service = decision.get("service") or assistant_catalog.choose(contact_facts.intent_text("\n".join(m["body"] for m in messages if m.get("direction") == "in"), facts), known)
    route = assistant_policy.crm_branch_route(known, service)
    if route:
        reasons.extend(branch_route_check(route, prep, sel))
    elif str(prep.get("cityText") or "").split("(")[0].strip().casefold() != str((decision.get("geography") or {}).get("lead") or known["city"]).strip().casefold():
        reasons.append("Город CRM отличается от подтверждённого филиала")
    if known.get("direction") == "mnc" and known.get("city") == "Красноярск" and not route:
        selected_work = next((r.get("text", "") for r in prep.get("appl", []) if r.get("id") == prep.get("applId")), "")
        if selected_work.strip().casefold() == "сантехника" or str(prep.get("cityId")) == "709":
            reasons.append("Вид работ или специальный филиал не подтверждён смыслом переписки")
    if not prep.get("applRule") or not prep.get("subRule") or prep.get("applId") != sel.get("applId") or prep.get("subId") != sel.get("subId"):
        reasons.append("Вид работ или услуг выбран неоднозначно")
    if prep.get("live") or prep.get("moderation") or prep.get("found") or prep.get("unchecked"):
        reasons.append("Есть история заявки или не проверены все базы CRM")
    if prep.get("partnerFound") is not True or str(lead.get("partner")) != str(known["partner"]).lstrip('0'):
        reasons.append("Не подтверждён партнёр CRM")
    if not terr.get("ok") or terr.get("approval") or terr.get("far") or terr.get("noMap") or terr.get("timeout"):
        reasons.append("Территория не подтверждена без согласования")
        if route:
            reasons.append(route["approval_instruction"])
    if proposal.get("flags") or proposal.get("readiness") != "ready":
        reasons.append("Проверка готовности оставила замечания")
    followup=proposal.get('followup') or {}
    if type(crm_only)is not bool:
        reasons.append('Не подтверждён серверный режим завершения заявки')
    elif crm_only:
        if (followup.get('mode')!='crm_only' or followup.get('required')is not False
                or followup.get('telegram_ready')is not False):
            reasons.append('Снимок заявки не соответствует серверному режиму без Telegram')
    elif known["channel"] in ("avito", "max") and followup.get("telegram_ready") is not True:
        reasons.append("Не готова обязательная отписка в «Созданные с Авито»")
    identity = known["advertiser_name"] or known["account_name"]
    if not identity or lead.get("ad_identity") != identity or ("Объявление: «" + identity + "».") not in str(lead.get("comment") or ""):
        reasons.append("В комментарии нет подтверждённого имени или аккаунта объявления")
    if known.get("introduced_name") and known["introduced_name"] not in str(lead.get("comment") or ""):
        reasons.append("В комментарии нет имени, которым представились")
    codes = re.findall(r'(?<![\w])[А-ЯЁA-Z]\d+(?:\.\d+)?(?![\w.])', known['origin'], re.I)
    numbered = re.fullmatch(r'\s*№\s*([1-9]\d{0,3})\s*', known['origin'])
    if not codes and str(known.get('partner') or '').lstrip('0') == '748' and numbered:
        codes = ['№' + numbered[1]]
    if len(codes) != 1 or str(lead.get('partner_note') or '').strip() != codes[0]:
        reasons.append("Не подтверждён источник заявки")
    if not str(ctx["convId"]) in str(lead.get("service_comment") or ""):
        reasons.append("Нет ссылки на этот диалог")
    if not re.fullmatch(r"20\d\d-\d\d-\d\d", str(lead.get("visit_date") or "")) or not re.fullmatch(r"\d\d:\d\d", str(lead.get("visit_time") or "")):
        reasons.append("Не подтверждены дата и время визита")
    else:
        reasons.extend(visit_check(messages, known, lead, terr))
    # Owner clarification 2026-10-16: an ordinary primary chat request needs no
    # operator phone call. Moderations/approvals are excluded above; mandatory
    # master-call-before-visit flags remain enforced independently.
    return {"ok": True, "auto_enabled": False, "execution_allowed": False,
            "ready": not reasons, "step": "create_crm" if not reasons else "handoff", "reasons": list(dict.fromkeys(reasons)),
            "snapshot_hash": digest(proposal), "policy_version": assistant_policy.VERSION, "crm_route": route}


def branch_route_check(route, prep, sel):
    """Validate the live directory and selected work, never a label prefix."""
    reasons = []
    normalize = lambda value: re.sub(r"[()\s]+", " ", str(value or "")).strip().casefold()
    if str(prep.get("cityId")) != route["city_id"] or str(sel.get("cityId")) != route["city_id"] or normalize(prep.get("cityText")) != normalize(route["city_text"]):
        reasons.append("Сантехника Красноярска должна создаваться на филиал «Красноярск сантехника» (709)")
    if not any(str(r.get("id")) == route["city_id"] and normalize(r.get("text")) == normalize(route["city_text"]) for r in prep.get("cities", [])):
        reasons.append("Новый филиал сантехники не подтверждён актуальным справочником CRM")
    if not any(str(r.get("id")) == str(prep.get("applId")) and normalize(r.get("text")) == "сантехника" for r in prep.get("appl", [])):
        reasons.append("Не подтверждён вид работ «Сантехника» в новом филиале")
    if route["mixed_work"]:
        reasons.append("Смешанные работы нужно разделить по филиалам с оператором")
    return reasons


def visit_check(messages, known, lead, territory):
    city = contact_cities.city_by_name(known["city"])
    if not city:
        return ["Не подтверждён часовой пояс клиента"]
    try:
        zone = ZoneInfo(city.tz)
        now = datetime.now(zone)
        if known.get('_accepted_own_visit'):
            return own_visit.check_time(known['_accepted_own_visit'], known, lead, territory, now)
        visit = datetime.fromisoformat(lead["visit_date"] + "T" + lead["visit_time"]).replace(tzinfo=zone)
        earliest = str(territory.get("earliest") or "10:00")
        if visit < now + timedelta(hours=1) or not earliest <= lead["visit_time"] <= "21:30":
            return ["Время визита нарушает срок подготовки или часы приёма"]
        fact = qualification_state.inspect(messages)["visit_time"]
        source: dict = next((m for m in messages if m["id"] == fact.get("message_id")), {})
        text = source.get("body", "").lower()
        if re.search(r"\bне\s+(?:сегодня|завтра|послезавтра|[вк]\s*\d)", text) or len(set(re.findall(r"\bсегодня\b|\bзавтра\b|\bпослезавтра\b", text))) > 1 or len(re.findall(r"\b\d{1,2}:\d{2}\b", text)) > 1:
            return ["Дата или время содержат отрицание, выбор или окно; нужен оператор"]
        match = re.search(r"(?:\bв|\bк)\s*(\d{1,2})(?::(\d{2})|\s*час)", text)
        if not match or f"{int(match[1]):02d}:{int(match[2] or 0):02d}" != lead["visit_time"]:
            return ["Время заявки не совпадает с точным временем клиента; окно требует проверки"]
        timestamp = source.get("created_at")
        base = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(zone).date() if timestamp else now.date()  # noqa: FURB162 - Python 3.10 compatibility
        if "послезавтра" in text:
            wanted = base + timedelta(days=2)
        elif "завтра" in text:
            wanted = base + timedelta(days=1)
        elif "сегодня" in text:
            wanted = base
        else:
            date = re.search(r"\b(\d{1,2})[.](\d{1,2})\b", text)
            if not date:
                return ["Не подтверждён день визита"]
            wanted = base.replace(month=int(date[2]), day=int(date[1]))
        if wanted.isoformat() != lead["visit_date"]:
            return ["Дата заявки не совпадает с датой клиента"]
        if wanted >= now.date() + timedelta(days=2) and not lead.get("call_before_visit"):
            return ["Для визита через два дня нужна отметка звонка перед выездом"]
        return []
    except (ValueError, TypeError, KeyError):
        return ["Дата и время требуют проверки оператора"]
