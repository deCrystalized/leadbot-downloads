"""Package the reviewed personal client and sanitized verification only."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parents[1] / "outputs"
OUT.mkdir(exist_ok=True)
read = lambda name: json.loads((ROOT / "test-artifacts" / name).read_text())
manifest = json.loads((ROOT / "ext/manifest.json").read_text())
assert manifest["version"] == "2.6.0"
archive = OUT / "LeadChat-2.6.0.zip"
for entry in manifest["content_scripts"]:
    for name in entry.get("js", []) + entry.get("css", []):
        assert (ROOT / "ext" / name).is_file(), name
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted((ROOT / "ext").rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            assert p.suffix not in {".env", ".sqlite", ".db", ".jsonl", ".pem"}
            z.write(p, "LeadChat-2.6.0/" + str(p.relative_to(ROOT / "ext")))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert json.loads(z.read("LeadChat-2.6.0/manifest.json"))["version"] == "2.6.0"
    entries = len(z.namelist())

authors = read("extra-authors/summary.json")
new_holdout = read("extra-authors/holdout-replay.json")
full_holdout = read("round2/full-holdout-replay.json")
real = read("personal/real-reviewed-final-private.json")
ui = read("workflow-ui-verification.json")
deploy = read("workflow-release/test-artifacts/deploy-manifest.json")
checks = {"python_tests": 166, "node_tests": 60, "failed": 0, "python_core_statement_coverage_percent": round(100 * (1488-121) / 1488, 2), "python_core_modules": 11,
          "new_browser_core_line_coverage_percent": 95.41, "new_browser_core_branch_coverage_percent": 83.96,
          "legacy_offline_suites": 4, "ruff": "passed", "mypy_new_modules": "passed", "javascript_syntax": "passed", "build": "passed", "diff_check": "passed", "embedded_secret_pattern_scan": "passed"}
report = {"date": "2026-10-16", "client_timezone": "Asia/Shanghai", "extension_version": "2.6.0", "brain_version": "2.3.0", "policy_version": "2026-10-15.8",
          "auto_enabled": False, "automatic_customer_writes_enabled": False, "checks": checks, "new_authors": authors, "new_authors_holdout": new_holdout,
          "frozen_full_history_holdout": full_holdout, "frozen_reviewed_real_sample": {"cases": len(real["cases"]), "sources": real["sources"], "guard_failures": 0, "model_calls": 0},
          "browser_verification": ui,
          "deployment": {"host": "72.56.68.159", "verified_source_hashes": len(deploy["entries"]), "files": [{"target": e["target"], "sha256": e["sha256"]} for e in deploy["entries"]],
                         "backup_before_release": "/root/leadbot-release-backups/20261015-210822", "backup_before_final_audit_patch": "/root/leadbot-release-backups/20261015-211749",
                         "leadbot": "active", "brain": "active", "gateway": "active", "compiled_authenticated_entry": "passed", "compiled_workflow_guard_http": 403, "public_without_token_http": 401,
                         "service_without_token_http": 401, "other_owner_http": 403, "personal_authorize_http": 403, "pre_submit_guard_http": 403,
                         "audit_detail_owner_scope_and_after_stop": "passed", "personal_test_session": "started_and_stopped", "crm_writes": 0, "customer_sends": 0, "leadchat_server_modified": False},
          "package": {"file": archive.name, "entries": entries, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "permissions_expanded": False, "installed_in_working_chrome_this_turn": False},
          "limitations": ["Auto mode is immutable OFF; no UI switch or browser flag can enable it.", "Customer writes were verified only with isolated LC/CRM/Telegram transports, not on live customers.", "Mandatory pre-booking call requires explicit operator confirmation for the exact current revision; no automated telephony.", "Conflicting rules and unknown branch status remain operator-only.", "History beyond 300 messages, unavailable media or incomplete pagination stops qualification.", "Available historical data is not complete lifetime/deleted history; no model weight fine-tuning or conversion-quality claim.", "Narrow viewport CSS exists but only desktop 1280 px was visually verified in this turn."]}
(OUT / "LeadBot-verification-2.6.0.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

(OUT / "LeadChat-2.6.0-install.md").write_text("""# Обновление личного помощника до 2.6.0

Мозг на lead-bot-nl уже обновлён. Адрес мозга и существующий личный токен сохраняются. Автоматическое взятие, отправка и создание заявок выключены.

1. Распакуйте `LeadChat-2.6.0.zip`.
2. **Замените содержимое прежней папки установленного распакованного расширения** файлами из папки `LeadChat-2.6.0`. Сохраните прежний путь: это сохраняет идентификатор расширения, личный токен и настройки.
3. В `chrome://extensions` нажмите кнопку перезагрузки на существующей карточке LeadChat. Перезагрузите страницу LeadChat.
4. Нажмите **✦ «Личный помощник»**. Откроется отдельная вкладка; основной LeadChat останется на месте. Значок **↗** выносит помощника в отдельное окно — его можно перенести на другой монитор.
5. Войдите в свой основной аккаунт Мамонтов Георгий. Подключите личную сессию, выберите лимит 1–5 (по умолчанию 3), нажмите **«Проверить очередь»**.
6. В подходящем диалоге нажмите **«Открыть диалог» → «Проверить всю цепочку»**. Выбор происходит внутри помощника. Проверка покажет следующий шаг и недостающие данные, без назначения диалога и отправки.
7. **«Подготовить ответ»** даёт проверенный текст. Сейчас отправляет оператор. В **«Подробном журнале»** нажмите «Обновить журнал», раскройте событие и «Показать прочитанные сообщения».

Согласования и неизвестные условия находятся в «Почему пропущены». Лимит считает все уже назначенные вам диалоги; сложные не снимаются с вас автоматически. Вторая вкладка не может одновременно подключить личную сессию.

«Остановить», закрытие окна, скрытие вкладки или смена аккаунта прекращают личную сессию. При работе на втором мониторе оставляйте отдельное окно помощника видимым. Журнал остаётся доступен после остановки. При подключении личного помощника старый автоприём расширения выключается.

Если расширение ещё не установлено, загрузите папку с `manifest.json` через «Загрузить распакованное расширение» в режиме разработчика Chrome и укажите существующий личный токен мозга в настройках. Не создавайте второй экземпляр рядом с уже установленным.
""")

table = "\n".join(f"| {name} | {s['outbound_messages']:,} | {s['dialogs']:,} | {s['blocks']:,} | {s['first_utc'][:10]} — {s['last_utc'][:10]} |".replace(",", " ") for name, s in authors["authors"].items())
(OUT / "LeadBot-2.6.0-report.md").write_text(f"""# Личный помощник LeadChat — 2.6.0

Проверка и обновление от 16.10.2026, часовой пояс пользователя Asia/Shanghai. Мозг 2.3.0 на lead-bot-nl, регламент 2026-10-15.8. **Автоматический режим выключен. Рабочим клиентам ничего не отправлено, рабочих заявок не создано.**

## Что ещё ограничивает автоматическую работу

Цепочка реализована и проверена на изолированных внешних транспортах. Полного прогона с записями реальным клиентам, рабочей CRM и Telegram не проводилось. Обязательный звонок пока подтверждает оператор для точной текущей версии данных; автоматической телефонии нет. Это готовность к личной проверке, а не подтверждение готовности к работе без присмотра.

Шесть спорных строк матрицы и неизвестные статусы филиалов остаются оператору: картриджи 113/243, спутниковое ТВ 042/124/229, Элиста 264. Для партнёра 723 используется общий прайс КП; подтверждённая поломка матрицы ТВ не попадает в самостоятельный приём. Неизвестное условие, согласование, жалоба, существующая заявка или нерасшифрованное вложение останавливают цепочку.

## Дополнительные сотрудники

Обработаны все доступные полные разговоры с участием Казахбаева Зухратдина и Вострикова Глеба: **2 036 уникальных диалогов, 63 384 сообщения в этих диалогах, 4 789 блоков ответов сотрудников**. Разговоры у сотрудников частично пересекаются, поэтому строки таблицы нельзя складывать как число уникальных клиентов.

| Сотрудник | Исходящие сообщения | Диалоги с исходящими | Блоки ответов | Период исходящих |
|---|---:|---:|---:|---|
{table}

Разбор выполнен по всему доступному корпусу программно; кандидатные формулировки просмотрены отдельно. Это не утверждение, что каждый разговор прочитан вручную, и не оценка качества сотрудников по исходам заказов. Переписка не показывает все звонки и внешние согласования.

Из 60 кандидатных формулировок допущены **14 коротких вопросов**: имя клиента, телефон, марка и модель, описание поломки, высота потолка. Например: «Вас как зовут?», «Подскажите номер телефона для связи», «Здравствуйте! а что у вас с ним случилось?». Распознавание ответа на «Вас как зовут?» также исправлено: следующее «Иван» считается именем и не переспрашивается.

Фразы с обещанием выезда, догадкой о диагнозе, неполным перечнем вариантов, ошибками или несколькими несвязанными вопросами не добавлены. Цены и правила приёма из поведения сотрудников не выводятся. Всего в рабочем наборе **81 проверенная формулировка**, обычные вопросы не требуют вызова модели. Веса модели не дообучались; исходные диалоги не загружались во внешний сервис обучения.

Источники новых формулировок датированы до 01.10.2026, группы клиентов замороженной отложенной выборки исключены. Пересечение источников обучения с этими клиентами — ноль. На 427 отдельных поздних ходах новых сотрудников: 105 вопросов, 322 передачи оператору, ноль нарушений проверяемых ограничений и вызовов модели. Это проверка ограничений, а не доказательство человеческого уровня общения или конверсии.

## Как устроена личная работа

✦ открывает собственную вкладку помощника. Значок ↗ выносит её в отдельное окно для другого монитора. Выбор диалога внутри помощника не переключает основной LeadChat. Слева — ваш аккаунт, лимит, подходящие диалоги и причины пропуска; справа — текущий разговор, план, ответ, данные и журнал.

Приём ограничен вашими назначенными и новыми свободными диалогами. Свободные со спорными правилами и согласованиями не берутся. Лимит по умолчанию три, диапазон 1–5; он учитывает все ваши назначенные разговоры. Фильтр подтверждает профильность и условия приёма, а не прибыльность будущего заказа.

Сервер принимает только ваш личный токен и основной аккаунт Мамонтов Георгий. Одновременно работает одна личная вкладка. Срок подтверждения сессии — 45 секунд. Закрытие, скрытие, остановка или смена аккаунта блокируют дальнейшие действия. Логика правил и разрешений находится на сервере; клиентские действия выполняет расширение в вашей браузерной сессии. Серверный работник для самостоятельного общения не включался.

Цепочка: отбор → взятие на ваш аккаунт → свежий проверенный ответ → ожидание клиента → сбор телефона, адреса, модели/работы, ЛПР, имени, даты и времени → проверка CRM и территории → подтверждение звонка → создание → сверка сохранённой карточки → привязка номера к разговору → имя с номером → обязательная служебная отписка для Avito/MAX.

Перед каждой записью заново проверяются аккаунт, сессия, текущая переписка и разрешение. Перед отправкой формы CRM проверка повторяется через исходную вкладку, также перед дозаписью комментариев и карточки клиента. Сохраняются исходная цена, техника и проблема, источник, имя мастера или название аккаунта объявления, представленное имя и ссылка на диалог. Точное время сверяется с сообщением клиента и часовым поясом города.

Запись сначала получает долговечную отметку намерения. Если сеть оборвалась, результат считается неизвестным; слепой повтор запрещён, включая перезапуск вкладки. Известный номер созданной заявки сохраняется даже при расхождении полей. Сбой привязки или отписки не создаёт вторую заявку.

## Что видно в журнале

На сервере сохраняются версии прочитанных сообщений, в том числе служебные и недоставленные с отметкой об исключении из решения; понятые контакты и ответы; неизвестные вложения; следующий вопрос; основания решения; точный черновик; подтверждение звонка; разрешённые и запрещённые попытки; начало запроса, подтверждённый номер или неизвестный результат.

Одинаковый снимок учитывается счётчиком повторных проверок. Изменение даже исключённой служебной заметки сохраняется отдельным полным снимком. Журнал переживает перезапуск сервиса и очистку кэша черновиков, доступен только владельцу, выдаётся страницами. Внутренние токены, разрешения на действие и служебные ключи в него не пишутся; сам журнал не подмешивается в правила или обучение. При недоступности сервера события действий ставятся в локальную долговечную очередь.

## Проверки

- **166 Python-тестов, 60 Node-тестов**, четыре прежних набора проверок с отключённой сетью. Покрытие 11 основных Python-модулей — 92%; новых браузерных модулей — 95,41% строк.
- Ruff, Mypy для новых серверных модулей, синтаксис JavaScript/Python, сборка и diff прошли. Разрешения расширения не расширены; пакет проверен на известные шаблоны вшитых секретов.
- На 2 617 замороженных ходах с полной предшествующей историей: 763 вопроса, 1 846 передач оператору, пять ожиданий, три отказа. На 51 ранее выбранном реальном срезе: 17 проверенных вопросов и 34 решения по правилам. Нарушений проверяемого контракта нет; модель не вызывалась. Полные истории включают старые договорённости и неизвестные условия, поэтому доля передач не оценивает качество новых лидов.
- Через настоящий Node-вход и Python-брокер на стенде пройдена цепочка взятия, ответа, звонка, создания, привязки, переименования и отписки. Внешние клиентские транспорты были изолированы; разрешение включалось исключительно в отдельном тестовом процессе.
- Настоящий код CRM в браузере сверил 18 полей без расхождений. Намеренная потеря комментария и отзыва обнаружена. Остановка до формы дала ноль POST; остановка после создания заблокировала дозапись, сохранила номер и показала расхождение. Всего две синтетические записи в изолированную CRM, ноль рабочих записей.
- Интерфейс проверен на вымышленных данных при ширине 1280 px без горизонтального переполнения. Основная вкладка осталась неизменной. Узкая раскладка реализована в CSS, но её визуальная проверка в этой сессии не подтверждена.

На рабочем lead-bot-nl сверены SHA-256 всех 12 файлов; LeadBot, мозг и шлюз активны. Скомпилированный вход проверен с синтетическим личным токеном в изолированном хранилище и реальным внутренним LeadBot. Чужой владелец и автоматические записи получают 403, публичный запрос без токена — 401. Журнал и его подробные снимки проверены после остановки сессии. Резервная копия до релиза: `/root/leadbot-release-backups/20261015-210822`; до последнего исправления снимков: `/root/leadbot-release-backups/20261015-211749`. Сервер LeadChat 188.225.34.82 не изменялся.

## Обновление

Chrome в этой сессии не обновлялся. Нужно заменить файлы в прежней папке установленного распакованного расширения и нажать перезагрузку его карточки. Путь папки важно сохранить, чтобы сохранить идентификатор и токен. Кнопки включения автоматического режима в интерфейсе нет.

- [Архив расширения](./LeadChat-2.6.0.zip)
- [Инструкция обновления](./LeadChat-2.6.0-install.md)
- [Результаты и проверенные хеши](./LeadBot-verification-2.6.0.json)
- [Разбор архитектуры](./LeadBot-architecture-2.6.0.json)

![Отдельная вкладка на изолированном стенде](./LeadBot-2.6.0-personal-tab.png)
![Прочитанное и понятое в журнале](./LeadBot-2.6.0-audit.png)
""")

layers = ["System prompt", "Session history", "Long-term memory", "Distillation", "Active recall", "Tool selection", "Tool execution", "Tool interpretation", "Answer shaping", "Platform rendering", "Hidden repair loops", "Persistence"]
report_path = OUT / "LeadBot-2.6.0-report.md"
report_path.write_text(report_path.read_text().replace("](./", f"]({OUT}/"))
audit = {"schema_version": "ecc.agent-architecture-audit.report.v1", "date": "2026-10-16", "executive_verdict": {"overall_health": "ready_for_personal_review_auto_blocked", "primary_failure_mode": "Live customer transport and unattended quality are not established; auto remains immutable OFF.", "most_urgent_fix": "Keep OFF until a separately authorized operator pilot validates the live chain and remaining rule conflicts."},
         "scope": {"target_name": "Personal LeadChat extension 2.6.0 with server brain 2.3.0", "model_stack": ["reviewed server-selected wording; zero model calls in normal personal review", "optional single-attempt model path separately guarded and not selectable by client"], "layers_to_audit": layers},
         "findings": [
             {"severity": "high", "status": "open_but_auto_blocked", "title": "Live write chain and unattended quality remain unverified", "mechanism": "Tests use real coordinator, policy and CRM code but isolated customer transports.", "source_layer": "Tool execution", "root_cause": "User explicitly prohibited activation; no live customer writes performed.", "evidence_refs": ["tests/test_workflow_bridge.test.js", "tools/workflow_ui_server.py"], "confidence": 1, "recommended_fix": "Preserve immutable OFF; later validate only under separately authorized operator pilot."},
             {"severity": "high", "status": "fixed", "title": "Ambiguous writes require durable stop and reconciliation", "mechanism": "A lost result must not become a second CRM create or customer send.", "source_layer": "Persistence", "root_cause": "New action transports need durable write-ahead receipts independent of message revision.", "evidence_refs": ["ext/workflow.js", "leadbot/brain/personal_workflow.py", "tests/test_workflow.test.js"], "confidence": 1, "recommended_fix": "Implemented permanent create slot, operation journal, one-time grants, exact message reconciliation and known-ID retention."},
             {"severity": "medium", "status": "fixed", "title": "Incomplete history and ignored-message changes must remain observable", "mechanism": "Silent first-page analysis or snapshot dedup by filtered decision revision loses source context.", "source_layer": "Session history", "root_cause": "Decision revision alone does not represent excluded raw message versions.", "evidence_refs": ["ext/workflow.js", "leadbot/brain/workflow_audit.py", "tests/test_audit.py"], "confidence": 1, "recommended_fix": "Full cursor pagination with bounds; complete read snapshots keyed by exact message-version references."}],
         "layer_checks": dict(zip(layers, ["One server-selected question; rule/price selection outside model.", "Complete bounded history, identity and revision fencing.", "Audit and raw conversations never recalled as policy or prompts.", "Only 14 explicitly reviewed new questions admitted; primary regulation controls decisions.", "Question state avoids repeated facts; no redundant summary model calls.", "Plan and server permits code-gate all write types.", "Write-ahead intent, receipt reconciliation and strict pre-submit guard.", "No success without IDs and read-back fields; unknown stops.", "Actual validated text retained; no hidden paraphrase.", "Actual HTTP bridge, DOM CRM verification and browser UI tested.", "No repair agent; default reviewed questions use no model; optional model single attempt.", "Owner-scoped SQLite audit and grants; durable browser outbox; expiry and stale revisions stop writes."])),
         "ordered_fix_plan": [{"order": 1, "status": "completed", "goal": "Implement personal browser-owned coordinator with server authority", "why_now": "Required for owner-only operation", "expected_effect": "No server background sender or colleague execution"}, {"order": 2, "status": "completed", "goal": "Durable write and read audit, strict reconciliation and CRM verification", "why_now": "Prevent duplicates and invisible outcomes", "expected_effect": "Unknown outcomes stop and remain inspectable"}, {"order": 3, "status": "completed", "goal": "Review new-author wording and replay frozen real history", "why_now": "Natural wording must preserve regulation", "expected_effect": "81 reviewed question variants with disjoint holdout sources"}, {"order": 4, "status": "completed", "goal": "Deploy verified source and package extension with auto OFF", "why_now": "Make result concrete and reviewable", "expected_effect": "Owner can inspect queue, plan and log before future activation"}]}
(OUT / "LeadBot-architecture-2.6.0.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"archive": archive.name, "entries": entries, "sha256": report["package"]["sha256"], "auto_enabled": False, "new_author_dialogues": 2036, "new_reviewed_questions": 14}))
