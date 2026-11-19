"""Personal browser session and conservative admission. No LeadChat/CRM transport."""
import os
import re
import secrets
import time

import assistant_catalog
import assistant_policy
import contact_facts
import qualification_state
import operator_identity
from assistant_store import digest

TTL = 45
DEFAULT_LIMIT = 0  # Owner requested no conversation limit; zero means unlimited.
ACTIVE_STATUSES = {"new", "in_progress", "waiting_client"}


def jobs_schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS personal_jobs(scope TEXT,chat TEXT,active INTEGER NOT NULL,updated REAL,PRIMARY KEY(scope,chat))")


def workload(store, owner, chat="", ctx=None, operator=None):
    """Count this helper's unfinished jobs, not an operator's historic backlog."""
    with store.connect() as db:
        jobs_schema(db)
        if chat and ctx and (ctx.get("crmRequestId") or ctx.get("conversationStatus") == "closed" or str(ctx.get("assigneeId") or "") not in ("", operator or os.environ.get("LEADBOT_PERSONAL_OPERATOR_ID"))):
            db.execute("UPDATE personal_jobs SET active=0,updated=? WHERE scope=? AND chat=?", (time.time(), digest(owner), chat))
        return db.execute("SELECT count(*) FROM personal_jobs WHERE scope=? AND active=1", (digest(owner),)).fetchone()[0]


def auto_available():
    """Deployment kill switch exposes a control, never activates a session."""
    return os.environ.get("LEADBOT_PERSONAL_AUTO_AVAILABLE") == "1"


def owner_allowed(owner):
    configured = os.environ.get("LEADBOT_PERSONAL_OWNER_ID", "")
    return not configured or owner == configured


def session(store, owner, action, body, now=None):
    explicit_now = now is not None
    now = time.time() if now is None else now
    if action == 'personal_identity_challenge':
        return operator_identity.challenge(store, owner, body, now)
    operator = os.environ.get("LEADBOT_PERSONAL_OPERATOR_ID", "")
    sid = str(body.get("browser_session") or "")
    who = str(body.get("operator_id") or "")
    identity = operator_identity.verify(store, owner, body, now) if body.get('identity_proof') else None
    if body.get('identity_proof') and identity is None:
        return {'ok': False, 'code': 'operator_identity', 'auto_enabled': False,
                'error': 'Подтвердите текущего администратора и автора ответа заново'}
    if identity:
        operator = identity['operator_id']
    principal = identity['principal_id'] if identity else operator
    admin_required = os.environ.get('LEADBOT_REQUIRE_ADMIN_AUTO') == '1'
    base = {"ok": True, "auto_enabled": False, "auto_available": auto_available(), "execution_mode": "review", "mode": "personal_review", "browser_session": sid,
            "owner_name": "Мамонтов Георгий", "operator_id": operator,
            "queue_scope": "mine_and_free", "strict_admission": True, "managed_dialogs": workload(store, owner)}
    base.update(principal_id=principal, delegated=bool(identity))
    if admin_required and not identity:
        base['auto_available'] = False
    if identity:
        base['owner_name'] = identity['operator_name']
    if not os.environ.get("LEADBOT_PERSONAL_OWNER_ID") or not operator:
        return dict(base, ok=False, code="personal_unconfigured", error="Личный доступ ещё не настроен")
    if not re.fullmatch(r"[a-zA-Z0-9:_-]{8,120}", sid) or who != operator:
        return dict(base, ok=False, code="personal_identity", error="Откройте LeadChat под своим аккаунтом")
    scope = digest(owner)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS personal_sessions (
            scope TEXT PRIMARY KEY, sid TEXT NOT NULL, operator TEXT NOT NULL,
            expires REAL NOT NULL, max_dialogs INTEGER NOT NULL)""")
        columns = {r[1] for r in db.execute("PRAGMA table_info(personal_sessions)")}
        for name, definition in {"principal": "TEXT NOT NULL DEFAULT ''", "execution_mode": "TEXT NOT NULL DEFAULT 'review'", "policy_ack": "TEXT NOT NULL DEFAULT ''", "activation_nonce": "TEXT NOT NULL DEFAULT ''", "mode_epoch": "INTEGER NOT NULL DEFAULT 0", "connection_epoch": "INTEGER NOT NULL DEFAULT 0", "control_seq": "INTEGER NOT NULL DEFAULT 0"}.items():
            if name not in columns:
                db.execute("ALTER TABLE personal_sessions ADD COLUMN " + name + " " + definition)
        if not explicit_now:
            now = time.time()
        if identity and not operator_identity.current_challenge(db, owner, identity, now):
            return dict(base, ok=False, active=False, code='operator_identity',
                        error='Подтверждение автора изменилось до обработки команды')
        row = db.execute("SELECT * FROM personal_sessions WHERE scope=?", (scope,)).fetchone()
        if row and row["max_dialogs"] != 0:
            db.execute("UPDATE personal_sessions SET max_dialogs=0 WHERE scope=?", (scope,))
            row = db.execute("SELECT * FROM personal_sessions WHERE scope=?", (scope,)).fetchone()
        live = bool(row and row["expires"] > now)
        same_principal = bool(row and row['principal'] in ('', principal))
        mine = bool(live and row["sid"] == sid and row["operator"] == who and same_principal)
        if row and row['principal'] and not identity:
            mine = False  # No legacy fallback into an attested admin session.
        ordered_required = os.environ.get('LEADBOT_REQUIRE_ORDERED_CONTROL') == '1'
        if mine and row["execution_mode"] == "auto" and (not auto_available() or row["policy_ack"] != assistant_policy.VERSION or admin_required and not identity or ordered_required and not row['connection_epoch']):
            base['mode_reset_reason'] = ('Регламент изменился' if row['policy_ack'] != assistant_policy.VERSION
                else 'Подключите расширение с проверкой порядка команд' if ordered_required and not row['connection_epoch']
                else 'Авто отключён на сервере')
            db.execute("UPDATE personal_sessions SET execution_mode='review',activation_nonce=?,mode_epoch=mode_epoch+1 WHERE scope=?", (secrets.token_urlsafe(24), scope))
            row = db.execute("SELECT * FROM personal_sessions WHERE scope=?", (scope,)).fetchone()
        if mine:
            base.update(execution_mode=row["execution_mode"], auto_enabled=row["execution_mode"] == "auto", mode_epoch=row["mode_epoch"],
                        policy_version=assistant_policy.VERSION, activation_nonce=row["activation_nonce"],
                        connection_epoch=row['connection_epoch'], control_seq=row['control_seq'],
                        control_protocol='ordered_v1' if row['connection_epoch'] else 'legacy')
            if ordered_required and not row['connection_epoch']:
                base['auto_available'] = False
        if action == "personal_status":
            return dict(base, active=mine, another_tab=live and not mine,
                        lease_seconds=max(0, int(row["expires"]-now)) if mine else 0,
                        max_dialogs=row["max_dialogs"] if live else DEFAULT_LIMIT)
        if action == "personal_start":
            if live and not mine:
                return dict(base, ok=False, code="personal_busy", error="Помощник уже открыт в другой вкладке")
            protocol = body.get('control_protocol')
            if protocol not in (None, 'ordered_v1') or (mine and row['connection_epoch'] and protocol != 'ordered_v1'):
                return dict(base, ok=False, code='personal_control_protocol',
                            error='Подключите актуальное расширение с проверкой порядка команд')
            value = DEFAULT_LIMIT
            nonce = secrets.token_urlsafe(24);epoch = row["mode_epoch"]+1 if row else 1
            connection = epoch if protocol == 'ordered_v1' else 0
            db.execute("INSERT OR REPLACE INTO personal_sessions(scope,sid,operator,expires,max_dialogs,execution_mode,policy_ack,activation_nonce,mode_epoch,principal,connection_epoch,control_seq) VALUES (?,?,?,?,?,'review','',?,?,?,?,0)",
                       (scope, sid, who, now+TTL, value, nonce, epoch, principal if identity else '', connection))
            return dict(base, active=True, auto_enabled=False,
                        auto_available=auto_available() and (not admin_required or bool(identity)) and (not ordered_required or bool(connection)),
                        execution_mode="review", activation_nonce=nonce, mode_epoch=epoch,
                        connection_epoch=connection, control_seq=0, control_protocol=protocol or 'legacy',
                        policy_version=assistant_policy.VERSION, lease_seconds=TTL, max_dialogs=value)
        if not mine:
            return dict(base, ok=False, active=False, code="personal_expired", error="Личная сессия остановлена. Подключите её заново")
        ordered = row['connection_epoch'] > 0
        if ordered and action in ('personal_stop', 'personal_mode', 'personal_heartbeat'):
            connection = body.get('connection_epoch')
            sequence = body.get('control_seq')
            if (type(connection) is not int or connection != row['connection_epoch']
                    or action != 'personal_heartbeat' and (type(sequence) is not int
                        or not row['control_seq'] < sequence <= 9007199254740991)):
                return dict(base, ok=False, active=True, code='personal_control_obsolete',
                            control_not_applied=True, error='Команда относится к старому подключению или режиму')
        def record_control():
            if ordered:
                db.execute('UPDATE personal_sessions SET control_seq=? WHERE scope=?', (body['control_seq'], scope))
                base['control_seq'] = body['control_seq']
        if action == "personal_stop":
            expected_epoch = body.get('expected_mode_epoch')
            if expected_epoch is not None:
                if type(expected_epoch) is not int or expected_epoch < 1:
                    return dict(base, ok=False, active=True, code='personal_stop_epoch',
                                error='Не подтверждена версия остановленной сессии')
                if expected_epoch != row['mode_epoch']:
                    return dict(base, active=True, stop_not_applied=True,
                                code='personal_stop_obsolete')
            record_control()
            # Retain a generation tombstone: a quick reconnect must not reuse
            # the epoch of a still-in-flight permit from the previous session.
            db.execute("UPDATE personal_sessions SET expires=0,execution_mode='review',activation_nonce='',mode_epoch=mode_epoch+1 WHERE scope=?", (scope,))
            return dict(base, active=False, auto_enabled=False, execution_mode="review", activation_nonce="", mode_epoch=row['mode_epoch']+1, max_dialogs=row["max_dialogs"])
        if action == "personal_mode":
            mode = body.get("execution_mode")
            if mode not in ("review", "auto"):
                return dict(base, ok=False, code="personal_mode", error="Неизвестный режим")
            record_control()
            if mode == "auto":
                if os.environ.get('LEADBOT_REQUIRE_ORDERED_CONTROL') == '1' and not ordered:
                    return dict(base, ok=False, code='personal_control_protocol',
                                error='Для рабочего авто нужно расширение с проверкой порядка команд')
                if admin_required and not identity:
                    return dict(base, ok=False, code='admin_required', error='Рабочее авто включается из аккаунта администратора')
                version = str(body.get("client_version") or "")
                current_client = bool(re.fullmatch(r"\d+\.\d+\.\d+", version) and tuple(map(int, version.split("."))) >= (2, 7, 0))
                nonce = str(body.get("activation_nonce") or "")
                if not auto_available() or body.get("confirmed") is not True or body.get("policy_ack") != assistant_policy.VERSION or not current_client or len(nonce) < 20 or not secrets.compare_digest(nonce, row["activation_nonce"]):
                    return dict(base, ok=False, code="auto_activation", error="Подключите актуальное расширение и явно включите авто для своего аккаунта")
            nonce = secrets.token_urlsafe(24);epoch = row["mode_epoch"]+1
            db.execute("UPDATE personal_sessions SET execution_mode=?,policy_ack=?,activation_nonce=?,mode_epoch=? WHERE scope=?",
                       (mode, assistant_policy.VERSION if mode == "auto" else "", nonce, epoch, scope))
            return dict(base, active=True, auto_enabled=mode == "auto", execution_mode=mode, activation_nonce=nonce, mode_epoch=epoch,
                        policy_version=assistant_policy.VERSION, lease_seconds=max(0, int(row["expires"]-now)), max_dialogs=row["max_dialogs"])
        if action == "personal_heartbeat":
            db.execute("UPDATE personal_sessions SET expires=? WHERE scope=?", (now+TTL, scope))
        return dict(base, active=True, lease_seconds=TTL if action == "personal_heartbeat" else max(0, int(row["expires"]-now)), max_dialogs=row["max_dialogs"])


# These missing facts can turn an apparently ordinary job into branch approval.
CONDITIONS = qualification_state.ACCEPTANCE_CONDITIONS
# Sport installation is accepted without approval (DOC-L0355). Wall material
# remains a required intake question (DOC-L0356), not a reason to skip the chat.


def screen(messages, known, ctx, operator, limit, mine_count, allow_ready=False, *, allow_visual=False):
    facts = contact_facts.collect(messages, known)
    decision = assistant_policy.assess(messages, known, facts)
    service = decision.get("service") or assistant_catalog.choose(
        "\n".join(m["body"] for m in messages if m["direction"] == "in"), known)
    assignment = str(ctx.get("assigneeId") or "")
    scope = "mine" if assignment == operator else "free" if not assignment else "other"
    result = {"ok": True, "auto_enabled": False, "eligible": False, "scope": scope,
              "action": decision["action"], "policy_version": assistant_policy.VERSION,
              "rule_ids": list(dict.fromkeys(decision['rule_ids'])),
              "candidate_service_rule_ids": service['rules'],
              "decision_guards": decision.get('decision_guards', []),
              "next_question": decision.get("next_question", {}).get("question", ""),
              "planned_actions": [], "reason": "", "service_status": service["status"]}
    if decision.get('crm_preparation'):
        result['crm_preparation'] = decision['crm_preparation']

    def reject(reason, kind="skip"):
        return dict(result, reason=reason, admission=kind)

    if str(known.get("channel") or "").lower().startswith("max"):
        return reject("MAX исключён владельцем: помощник здесь не работает")
    if scope == "other":
        return reject("Диалог назначен другому сотруднику")
    if ctx.get("assignmentKnown") is not True:
        return reject("Не подтверждён ответственный по диалогу")
    if ctx.get("conversationStatus") not in ACTIVE_STATUSES:
        return reject("Диалог закрыт или его состояние неизвестно")
    if ctx.get("botActive") is not False or ctx.get("hasTransfer") is not False:
        return reject("Диалог ведёт встроенный бот, есть передача либо статус не подтверждён")
    if ctx.get("channelAssigned") is not True:
        return reject("Доступ к этому каналу не подтверждён")
    if known.get("crm_request_id") or ctx.get("hasCrmJob"):
        return reject("По диалогу уже есть заявка или идёт её создание")
    adult = facts.get('adult_presence') or {}
    if adult.get('required') and adult.get('status') != 'confirmed':
        if (scope == 'mine' and service['status'] == 'supported'
                and decision['action'] in ('question', 'price')
                and any(g['id']=='VERIFY_ADULT_PRESENCE' for g in decision.get('decision_guards', []))):
            return dict(result, eligible=True, admission='qualify', qualification_only=True,
                        reason='Уточнить условие присутствия взрослого в своём диалоге',
                        planned_actions=['Проверить ответ по условию взрослого'])
        return reject('Не подтверждено присутствие взрослого при визите: свободный диалог не берём', 'needs_facts')
    if decision.get('silence_followup'):
        if scope != 'mine' or service['status'] != 'supported':
            return reject('Уточнение после ожидания возможно только в своём профильном диалоге', 'wait')
        return dict(result, eligible=True, admission='eligible',
                    reason='Один уточняющий вопрос после5минут ожидания на КП',
                    planned_actions=['Проверить и отправить уточняющий вопрос'])
    if scope == 'free' and decision.get('crm_flags', {}).get('future_only'):
        return reject('Клиент спрашивает об услуге на будущее: сейчас новый диалог не берём', 'wait')
    if scope == "free" and limit > 0 and mine_count >= limit:
        return reject("Достигнут личный лимит диалогов", "capacity")
    ready = decision["reason"] == "Данные собраны: оператор проверяет условия и подтверждает заявку"
    visual = (allow_visual and decision['action']=='handoff'
              and any(g.get('id')=='UNREAD_MEDIA' for g in decision.get('decision_guards',[]))
              and any(m.get('unread_media') for m in messages)
              and all(m.get('reviewable_image') for m in messages if m.get('unread_media')))
    if visual:
        result['requires_visual_research']=True
        # A read-only routing probe must reach the normal territorial/service
        # guards that sit after UNREAD_MEDIA. It neither saves a review nor
        # supplies an observation/fact, and cannot authorize an operation.
        from research_vision import routing_probe
        probe=routing_probe(messages,known)
        if probe['action'] in ('handoff','refuse','wait'):
            return reject(probe['reason'])
        visual_geo=probe.get('geography') or {}
    if decision["action"] in ("handoff", "refuse") and not (allow_ready and ready) and not visual:
        return reject(decision["reason"])
    if decision["action"] == "wait":
        return reject(decision["reason"], "wait")
    if service["status"] != "supported":
        return reject("Нет однозначной профильной работы без согласования")
    geo = visual_geo if visual else (decision.get("geography") or {})
    if geo.get("status") != "known" or geo.get("far_trip"):
        return reject("Территория требует уточнения, согласования или дальнего выезда")
    if facts["phone_needs_confirmation"] or facts["address_needs_confirmation"]:
        return reject("Контакты или адрес противоречивы")
    if visual:
        return dict(result,eligible=True,admission='visual_research',action='wait',
                    reason='Прочитать исходное изображение до нового решения о приёме',can_send_or_create=False)
    state = qualification_state.inspect(messages)
    keys = qualification_state.acceptance_conditions(service, state)
    missing_conditions = [key for key in keys if state[key]['status'] != 'answered']
    if missing_conditions:
        result['missing_acceptance_conditions'] = missing_conditions
        question = decision.get('next_question') or {}
        if (scope == 'mine' and question.get('kind') in missing_conditions
                and not question.get('requires_operator')
                and all(state[key]['status'] in ('missing', 'uncertain')
                        and state[key]['asked'] < 2 for key in missing_conditions)):
            return dict(result, eligible=True, admission='qualify', qualification_only=True,
                        reason='Уточнить условие приёма в своём диалоге',
                        planned_actions=['Уточнить условие приёма'])
        return reject("Не подтверждены условия, от которых зависит приём без согласования", "needs_facts")
    if decision["action"] == "wait":
        return reject("Ожидаем ответ клиента; новый диалог сейчас не берём", "wait")
    result.update(eligible=True, admission="eligible", reason="Профильная работа без выявленных согласований",
                  planned_actions=(["Взять диалог на себя"] if scope == "free" else []) +
                  (["Подготовить следующий ответ"] if decision.get("next_question") else ["Проверить ответ и данные заявки"]))
    return result
