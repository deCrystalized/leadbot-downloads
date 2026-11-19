"""Package only public extension sources and sanitized verification artifacts."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parents[1] / "outputs"
DATA = ROOT / "test-artifacts/auto-release"
read = lambda p: json.loads((ROOT / p).read_text())
manifest = read("ext/manifest.json")
assert manifest["version"] == "2.7.0"
for entry in manifest["content_scripts"]:
    for filename in entry.get("js", []) + entry.get("css", []):
        assert (ROOT / "ext" / filename).is_file()
archive = OUT / "LeadChat-2.7.0.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted((ROOT / "ext").rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            assert p.suffix not in {".env", ".pem", ".sqlite", ".jsonl", ".db"}
            z.write(p, "LeadChat-2.7.0/" + str(p.relative_to(ROOT / "ext")))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert len(z.namelist()) == 42
    assert json.loads(z.read("LeadChat-2.7.0/manifest.json"))["version"] == "2.7.0"
sha = hashlib.sha256(archive.read_bytes()).hexdigest()
authors = read("test-artifacts/alltime-authors/analysis/summary.json")
full = read("test-artifacts/round2/full-holdout-replay.json")
extra = read("test-artifacts/alltime-authors/analysis/holdout-replay.json")
proof = read("test-artifacts/auto-release/full-ui-proof.json")
crm = next(e for e in proof["events"] if "crm_verification" in e)
assert proof["writes"] == ["claim", "reply", "create", "link", "rename", "notify"]
assert not crm["crm_verification"]["diffs"] and crm["crm_verification"]["checked"] == 18
deploy = read("test-artifacts/auto-release/stage/test-artifacts/deploy-manifest.json")
deploy_result = next(json.loads(line) for line in (DATA / "final-deploy.txt").read_text().splitlines() if line.startswith('{'))
backup = deploy_result["backup"]
verification = {"extension_version": "2.7.0", "brain_version": "2.4.0", "policy_version": "2026-10-16.9", "archive_sha256": sha,
                "package_files": 42, "python_tests_passed": 177, "node_tests_passed": 79, "python_core_line_coverage_percent": 93,
                "history_analysis": authors, "frozen_holdout": full, "extra_author_holdout": extra,
                "isolated_full_chain": {"operations": proof["writes"], "crm_fields_checked": 18, "differences": 0, "crm_creations": 1,
                                        "pre_send_review": read("test-artifacts/auto-release/pre-send-review.json"),
                                        "local_auto_cycles_ms": [e["cycle"]["duration_ms"] for e in proof["events"] if e.get("cycle", {}).get("mode") == "auto"][:2]},
                "deployment": {"host": "72.56.68.159", "runtime_files": deploy["entries"], "backup": backup, "services_verified_active": True},
                "activation_ui_check": read("test-artifacts/auto-release/activation-ui-check.json"),
                "activation_incident": read("test-artifacts/auto-release/activation-incident.json"),
                "final_production_audit": read("test-artifacts/auto-release/final-audit.json"),
                "live_customer_sends": 0, "live_crm_writes": 0, "live_auto_enabled": False,
                "limitations": ["No 100-percent accuracy or human-equivalence claim.", "Live send and real CRM creation have not been exercised in this release.", "Every live test reply must be inspected and approved individually before transport.", "Six unresolved matrix rows and unknown branch conditions remain operator-only.", "Unavailable or deleted history was not recovered.", "Mac must remain awake, online, Chrome and the helper tab must remain running."]}
mac_path = DATA / "mac-verification.json"
if mac_path.exists():
    verification["mac"] = json.loads(mac_path.read_text())
(OUT / "LeadBot-verification-2.7.0.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n")
(OUT / "LeadChat-2.7.0-install.md").write_text(f"""# LeadChat 2.7.0

На этом Mac расширение уже установлено в профиль Chrome «Никола». Папка: `{OUT / 'LeadChat-Mac'}`. Идентификатор и сохранённый личный токен сохранены. Не переносите папку после установки.

В LeadChat нажмите ✦. Помощник открывается отдельной вкладкой; кнопка в её заголовке выносит её в отдельное окно. Подключите личную сессию, проверьте закреплённый аккаунт «Мамонтов Георгий» и запустите репетицию. Репетиция показывает точные ответы и планы без записей.

Кнопка «Включить авто · Мамонтов Георгий» сначала показывает аккаунт и последствия. Рабочий режим включается только второй кнопкой «Подтверждаю: включить рабочий авто». Сейчас боевой авто выключен. До завершения контролируемых проверок оставьте его выключенным. Во время боевых тестов каждый ответ сначала разбирается по полной переписке и регламенту, затем отдельно допускается к отправке.

«Остановить» прекращает личную сессию. Закрытие или перезагрузка вкладки, смена аккаунта, потеря связи и изменение версии регламента останавливают выполнение. Переключение на другую вкладку само по себе не является остановкой. После подключения заново режим всегда «проверка».

Лимита количества активных диалогов нет, в том числе для 100 и более чатов. Сервер учитывает незавершённые работы и завершение заявок; старые назначения аккаунта показываются отдельно. Четыре исполнителя обрабатывают разные диалоги параллельно, внутри одного диалога действия сериализованы. Создание в CRM идёт отдельной очередью до выдачи краткосрочного разрешения. Неопределённый результат отправки или создания требует ручной проверки, повтор автоматически запрещён.

Ты можешь работать на другом ПК с другим аккаунтом. Новый аккаунт создаёшь самостоятельно. Помощник остаётся закреплён за текущим оператором; для переноса на иной аккаунт нужна отдельная настройка привязки.

Для рабочего ПК распакуйте [архив]({archive}) в прежнюю папку установленного расширения, замените файлы, затем нажмите перезагрузку его карточки в `chrome://extensions` и обновите LeadChat. Путь прежней папки важно сохранить, чтобы сохранить токен. SHA-256 архива: `{sha}`.
""")
(OUT / "LeadBot-2.7.0-report.md").write_text(f"""# Личный помощник LeadChat — 16.10.2026

Мозг 2.4.0 / регламент 2026-10-16.9 развёрнуты на lead-bot-nl; расширение 2.7.0 установлено на Mac. Логика правил и разрешений выполняется на сервере, действия — из личной браузерной сессии. Боевой автоматический режим выключен. Сервер LeadChat не изменялся.

## Что изменилось

- Явный запуск репетиции и автоматики только владельцем. Одноразовый код включения, версия регламента и версия расширения проверяются сервером. Повторное подключение не восстанавливает авто.
- Отдельная вкладка / окно, фиксированный заголовок и закреплённый оператор. Основной LeadChat не переключается. Диалог, открытый вручную в обычной вкладке этого профиля, помощник пропускает. Другой ПК с другим аккаунтом работает независимо.
- Реальные статусы LeadChat `new`, `in_progress`, `waiting_client` учтены. Неизвестный или закрытый статус блокирует действия. Ошибка ожидания несуществующего статуса `open` обнаружена на Mac до любых рабочих отправок.
- По твоему последнему указанию лимит активных чатов снят. Проверен учёт 101 незавершённого диалога. Сервер учитывает начало и завершение работ; неизвестный исход сохраняет блокировку повтора. Четыре исполнителя ведут разные чаты параллельно, действие в одном диалоге остаётся последовательным.
- Обычную первичную заявку можно создать по полностью подтверждённой переписке без звонка оператора — согласно твоему уточнению. Обязательная отметка звонка мастера перед выездом сохранена; модерации, согласования, спорная территория, история CRM и противоречивые контакты остаются оператору.
- Чтение историй идёт тремя параллельными запросами, обработка диалогов — четырьмя исполнителями. Создание в CRM сериализовано до выдачи разрешения, чтобы время ожидания формы не съедало разрешение. Реальные события будят цикл; резервная проверка — примерно раз в пять секунд. Запросы к модели для обычных проверенных формулировок не нужны. Событие нового сообщения приоритетно поднимает именно этот диалог. Время цикла записывается в журнал. Очередь читается страницами по 12 без прежних отсечек 100 своих / 600 входящих; проверен полный обход 1 310 диалогов.
- Сверяются прочитанные сообщения, контакты, обязательные вопросы, цена, источник, имя / аккаунт объявления, данные CRM и результат действий. Исправлена сверка имени объявления внутри одной строки комментария.

## Регламент и история

Повторно получены [общий регламент](https://docs.google.com/document/d/1VJuB4kz8eqtXs0JjGgSeFt0pwD_Wqq6J84j8B1sAQtw/edit) и [регламент КП](https://docs.google.com/document/d/1hAOnFGyISfYVGjtZCw0Aq_IfEmZmZYAZ1P5NZUrVG5Y/edit). Старые идентификаторы пунктов сохранены, 31 удалённый абзац исключён из действующих оснований, пять новых добавлены. Изменение версии регламента сбрасывает активное разрешение авто. Неподтверждённые пункты не превращены в разрешение.

Полная доступная выборка Вострикова Глеба и Казахбаева Зухратдина: **12 333 диалога, 221 864 сообщения, 29 675 блоков ответов**. Глеб: 6 072 диалога / 22 848 исходящих сообщений, 10.09–15.10.2026 UTC. Зухратдин: 6 897 диалогов / 24 496 исходящих, 09.09–14.10.2026 UTC. Есть общие диалоги. Более ранняя или удалённая история не восстановлена.

Все блоки прошли разбор структуры вопросов, длины, цен и обещаний. Из 86 извлечённых кандидатов формулировок после индивидуальной проверки добавлены восемь новых нейтральных вопросов; всего 89 проверенных вариантов. Цены, обещания и приём работ из старых переписок не заменяют регламент. Это банк формулировок и контрольных примеров, не дообучение весов модели и не доказательство равной человеку конверсии.

## Проверки

**177 Python-тестов и 79 Node-тест прошли**, покрытие пяти основных серверных модулей — 93% строк. Проверены одноразовое включение, смена версии правил, смена оператора, остановка, свежесть ответа, учёт более 100 чатов, параллельная обработка и очередь CRM, неоднозначный результат, дубли, обязательные CRM-поля, подпись объявления и возврат к проверке после переподключения. Ruff, Mypy для трёх новых серверных модулей, синтаксис и сборка прошли. Разрешения расширения не расширены.

На 2 617 замороженных срезах с полной предшествующей историей: 763 вопроса, 1 846 передач оператору, пять ожиданий, три отказа. На 469 будущих срезах новых авторов с клиентами контрольной выборки: 107 вопросов и 362 передачи. На 51 вручную выбранном реальном срезе — 17 проверенных формулировок и 34 решения по правилам. Проверяемых нарушений контракта не найдено; модель в этих прогонах не вызывалась. Эти числа не являются процентом коммерческой точности или оценкой всех свободных новых лидов.

На изолированном браузерном стенде сначала прочитан и проверен точный ответ, затем пройдена цепочка **взять → ответить → создать → сверить 18 полей → привязать → переименовать → отписаться**. Одна синтетическая заявка, ноль расхождений. Настоящие правила, исполнитель и код CRM; внешние данные и транспорты — вымышленные. В рабочие LeadChat, CRM и Telegram ничего не отправлено. Время на локальном стенде не прогнозирует задержку боевой сети.

На lead-bot-nl проверены хеши 13 файлов, активность LeadBot, мозга и шлюза, настоящий скомпилированный вход с изолированным тестовым токеном, блокировки чужого владельца и записи без явного включения. Резервная копия последней правки: `{backup}`.

## Исправление, найденное при проверке интерфейса

При управлении Chrome нажатие попало во включение авто вместо репетиции. Серверная сессия была остановлена; по журналу режим действовал 97,7 секунды, разрешённых операций и начатых транспортных запросов было ноль. Ничего не отправлено и не создано. После этого добавлено отдельное подтверждение с аккаунтом, проверкой версии правил, одноразового кода и сроком 60 секунд. На стенде проверены первое нажатие без включения, отмена, явное второе подтверждение и выключение. Кнопка выключения доступна даже во время чтения очереди.

## Что остаётся для боевого допуска

После последней перезагрузки Chrome перестал возвращать пригодное изображение и содержимое страницы через управление. Установка 42 файлов и перезагрузка расширения проверены; свежий финальный снимок реального цикла не выдаётся за выполненную проверку. Последняя серверная сверка: ноль активных сессий, авто выключен, ноль разрешённых операций и начатых транспортных запросов за последний час.

100% знание и отсутствие ошибок гарантировать нельзя. Шесть спорных строк матрицы и неизвестные условия филиалов остаются оператору. Нужно по одному проверить реальные ответы и реальные сохранённые заявки; перед каждым тестовым ответом сначала разобрать переписку и точный текст, затем разрешить именно эту отправку. Общий автоцикл для боевых тестов оставлен выключенным. Mac должен быть включён, не спать, иметь сеть и открытую вкладку помощника.

[Расширение]({archive}) · [Как пользоваться]({OUT / 'LeadChat-2.7.0-install.md'}) · [Результаты и хеши]({OUT / 'LeadBot-verification-2.7.0.json'})

![Отдельный помощник на изолированном стенде]({OUT / 'LeadBot-2.7.0-helper.png'})
""")
layers = ["System prompt", "Session history", "Long-term memory", "Distillation", "Active recall", "Tool selection", "Tool execution", "Tool interpretation", "Answer shaping", "Platform rendering", "Hidden repair loops", "Persistence"]
audit = {"schema_version": "ecc.agent-architecture-audit.report.v1", "date": "2026-10-16",
         "executive_verdict": {"overall_health": "ready_for_controlled_live_pilot_auto_off", "primary_failure_mode": "Unattended live quality and live creation transport have not been established.", "most_urgent_fix": "Inspect and authorize each live test reply separately; verify real CRM fields before unattended operation."},
         "scope": {"target_name": "LeadChat personal extension 2.7.0, brain 2.4.0", "model_stack": ["Server policy and reviewed wording; ordinary flow uses no model", "Optional single-attempt model path guarded independently"], "layers_to_audit": layers},
         "findings": [
             {"severity": "high", "status": "fixed", "title": "Actual platform statuses differed from synthetic fixtures", "mechanism": "An open-only check skipped every real in_progress dialog.", "source_layer": "Tool interpretation", "root_cause": "Fixtures used an invented platform status.", "evidence_refs": ["app/services/conversation_status.py read-only reference", "tests/test_workflow.py", "Mac native rehearsal"], "confidence": 1, "recommended_fix": "Implemented exact real active status set; unknown states fail closed; full chain rerun."},
             {"severity": "high", "status": "fixed", "title": "Historic assignments must not permanently exhaust helper capacity", "mechanism": "All account assignments counted toward a 1-5 job cap even after CRM completion.", "source_layer": "Persistence", "root_cause": "Operator backlog is different from helper-owned unfinished work.", "evidence_refs": ["leadbot/brain/personal_assistant.py", "leadbot/brain/personal_workflow.py", "tests/test_workflow.py"], "confidence": 1, "recommended_fix": "Removed the owner-rejected cap; durable work tracking remains. Tested 101 unfinished jobs, four workers and full 1310-item pagination."},
             {"severity": "high", "status": "open", "title": "Live write quality is not yet measured", "mechanism": "Isolated transport proof cannot demonstrate production customer behavior or all live CRM conditions.", "source_layer": "Tool execution", "root_cause": "No live customer sends or CRM writes have been performed.", "evidence_refs": ["test-artifacts/auto-release/full-ui-proof.json", "test-artifacts/auto-release/mac-verification.json"], "confidence": 1, "recommended_fix": "Owner-required supervised per-reply live pilot; keep unattended auto OFF."}],
         "layer_checks": dict(zip(layers, ["Server selects rule, question and allowed action.", "Full bounded history; fresh snapshot before writes.", "Audit never becomes policy or model instructions.", "89 individually approved neutral wording variants; source/client/time disjointness.", "Known contact/qualification facts prevent redundant questions.", "Normal jobs only; owner and exact policy activation required.", "Four browser workers with per-dialog locks, a separate CRM creation queue and one-time epoch-fenced permits.", "IDs and exact CRM read-back required; unknown outcomes stop.", "Exact validated draft preserved; no silent paraphrase or invented prices.", "Native Mac installation plus separate tab; isolated full actual CRM-code chain.", "No repair-agent loop; ordinary questions require zero model calls.", "Owner-scoped SQLite audit, unlimited tracked conversations, durable outbox and journals."])),
         "ordered_fix_plan": [{"order": 1, "status": "completed", "goal": "Explicit owner activation and browser runner", "why_now": "Required for personal autonomy", "expected_effect": "No server sender or accidental startup"}, {"order": 2, "status": "completed", "goal": "Current primary sources and full author cohort", "why_now": "Prevent obsolete rules and partial-history claims", "expected_effect": "Versioned constraints and isolated wording bank"}, {"order": 3, "status": "completed", "goal": "Real-status and capacity corrections discovered on Mac", "why_now": "Synthetic success was insufficient", "expected_effect": "Real statuses admitted, no conversation cap, bounded parallel requests and complete queue paging"}, {"order": 4, "status": "pending", "goal": "Supervised live reply and CRM pilot", "why_now": "Required before unattended claims", "expected_effect": "Evidence from actual transports after individual review"}]}
(OUT / "LeadBot-architecture-2.7.0.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"archive": archive.name, "files": 42, "sha256": sha, "auto_enabled": False}))
