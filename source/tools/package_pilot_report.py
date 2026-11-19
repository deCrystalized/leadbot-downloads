"""Package the installed client and aggregate pilot evidence; never export raw chats."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parents[1] / "outputs"
DATA = ROOT / "test-artifacts/auto-release"
read = lambda p: json.loads((ROOT / p).read_text())
version = read("ext/manifest.json")["version"]
assert version == "2.7.1"
python_result = (DATA / "pilot-python-tests.txt").read_text()
node_result = (DATA / "pilot-node-tests.txt").read_text()
assert "\nOK\n" in python_result and "FAILED" not in python_result
assert "ℹ fail 0" in node_result
python_count = int(re.search(r"Ran (\d+) tests", python_result)[1])
node_count = int(re.search(r"ℹ pass (\d+)", node_result)[1])
deployment = next(json.loads(l) for l in (DATA / "pilot-final-deploy.txt").read_text().splitlines() if l.startswith("{"))
smoke = [json.loads(l) for l in (DATA / "pilot-production-final.txt").read_text().splitlines() if l.startswith("{")]
assert smoke[0]["hashes_verified"] == 15 and smoke[0]["services_active"]
assert smoke[1]["policy_version"] == "2026-10-16.13"
files = sorted(p for p in (ROOT / "ext").rglob("*") if p.is_file())
assert len(files) == 42
for p in files:
    assert p.suffix not in {".env", ".pem", ".sqlite", ".jsonl", ".db"}
    assert p.read_bytes() == (OUT / "LeadChat-Mac" / p.relative_to(ROOT / "ext")).read_bytes()
archive = OUT / f"LeadChat-{version}.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, f"LeadChat-{version}/" + str(p.relative_to(ROOT / "ext")))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None and len(z.namelist()) == 42
sha = hashlib.sha256(archive.read_bytes()).hexdigest()
holdout = read("test-artifacts/round2/full-holdout-replay.json")
extra = read("test-artifacts/alltime-authors/analysis/holdout-replay.json")
assert not holdout["approved_question_guard_failures"] and not extra["approved_question_guard_failures"]
verification = {
    "extension_version": version, "brain_version": "2.4.1", "policy_version": "2026-10-16.13",
    "archive_sha256": sha, "package_files": 42,
    "python_tests_passed": python_count, "node_tests_passed": node_count,
    "five_core_python_modules_line_coverage_percent": 93,
    "production_smoke": smoke, "backup": deployment["backup"],
    "deployment_manifest": read("test-artifacts/auto-release/stage/test-artifacts/deploy-manifest.json"),
    "frozen_holdout": holdout, "extra_author_holdout": extra,
    "final_audit": read("test-artifacts/auto-release/pilot-final-audit.json"),
    "supervised_live_customer_sends": 0, "supervised_live_claims": 0, "supervised_live_crm_creations": 0,
    "unattended_auto_enabled": False,
    "limitations": [
        "No guarantee of 100 percent accuracy or human equivalence.",
        "A real new request creation and customer send have not yet been exercised.",
        "Each live action requires separate inspection and approval during the pilot.",
        "Identical requests across several ads require operator duplicate review.",
        "Six unresolved matrix rows remain operator-only.",
        "Historical and missing exports do not cover unavailable or deleted data.",
        "The Mac, Chrome and the helper tab must remain awake, online and running."
    ]
}
(OUT / f"LeadBot-verification-{version}.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n")
(OUT / f"LeadChat-{version}-install.md").write_text(f"""# LeadChat {version}

На этом Mac установлена версия {version}, Chrome, профиль «Никола». Сохранён прежний личный токен. Папку `{OUT / 'LeadChat-Mac'}` не перемещайте.

Открой ✦ → личная сессия → «Запустить репетицию». Репетиция непрерывно читает очередь и показывает планы, ничего не берёт и не отправляет. Надпись «Цикл остановлен» означает, что очередь не проверяется. Новые свободные диалоги проверяются в каждом цикле, старые назначения обходятся страницами; лимита числа чатов нет.

Выбери диалог и нажми «Проверить всю цепочку». Перед действием видны клиент, аккаунт объявления, город, точный ответ либо поля заявки. Кнопка «Проверено по регламенту» разрешает только этот шаг: взятие, один ответ, одно создание или следующий шаг оформления. После взятия ответ не уходит сам. После изменения переписки разрешение нужно получить заново. Неопределённый результат требует ручной сверки, автоматический повтор запрещён.

Постоянный авто пока не включай. MAX исключён сервером во всех вариантах канала. Обычная первичная заявка по полностью подтверждённой переписке не требует звонка оператора. Согласования, модерации, спорные адреса и неизвестные условия остаются тебе.

На рабочем ПК распакуй [архив]({archive}) в прежнюю папку установленного расширения с заменой файлов, перезагрузи его карточку в `chrome://extensions`, затем обнови LeadChat. Сохранение пути сохраняет прежний идентификатор и токен. SHA-256: `{sha}`.
""")
(OUT / f"LeadBot-{version}-report.md").write_text(f"""# Проверка личного помощника — 16.10.2026

Расширение {version} установлено и перезагружено на Mac. Мозг 2.4.1 / правила 2026-10-16.13 развёрнуты на lead-bot-nl. Проверены хеши 15 файлов, скомпилированный вход и три активных сервиса. Сервер LeadChat не изменялся. Резервная копия: `{deployment['backup']}`.

## Почему помощник не взял входящие

В базе найдены четыре диалога, взятые Мамонтовым почти одновременно 16.10 в 00:10:40 UTC. Они ждали от 3 минут 45 секунд до 6 минут 30 секунд. В журнале помощника до этого взятия нет чтения этих диалогов. На Mac проверочная сессия была остановлена; самостоятельное взятие не было запущено. Все шесть из сообщения пользователя однозначно сопоставить с этим событием нельзя: остальные два не подтверждены одной временной группой.

Исправлены дополнительные причины пропусков и ошибка выбора ответа:

- Свободные входящие стояли после старых назначенных. Теперь каждый цикл перечитывает шесть свободных строк и две первые назначенные; события сообщения получают приоритет. Не менее четырёх мест остаётся для полного обхода остальной очереди. Проверены шесть новых входящих на разных положениях курсора и полный обход 1 310 синтетических диалогов.
- Две разрешённые работы МНЧ автоматически считались смешанным согласованием. Реальный пример — шланг фильтра и кнопка унитаза. Пункты DOC-L0278–0280 и DOC-L0289–0290 разрешают эти работы; DOC-L0463 относится к сочетанию разрешённых и согласуемых работ. Теперь несколько явно разрешённых работ МНЧ проходят отбор, обязательные уточнения сохраняются. Конкретная цена одной услуги не выдаётся за весь список; сложный расчёт остаётся оператору.
- Во время повторной репетиции замечен свободный диалог Марины: ранее сотрудник назвал 3500р, клиент попросил подтвердить итог за всё. До взятия и отправки обнаружена прежняя договорённость. Добавлена передача такого уточнения оператору; повторный типовой ответ не разрешён.

Три одинаковых запроса клиента пришли на разные объявления. Такие случаи проверяются вместе вручную: автоматическое общение на всех копиях без проверки дублей не доказано и не разрешено в этом пилоте.

## Остальные исправления

- MAX, max_bot и max_user запрещены серверной политикой, отбором и выдачей разрешений, включая оформление уже созданной заявки.
- Отдельное одноразовое разрешение выполняет только один проверенный шаг без включения авто. Сервер сверяет владельца, вкладку, свежесть переписки, версию правил, точный текст ответа или поля заявки и одноразовый код.
- Исправлена общая блокировка всех диалогов: разные чаты имеют отдельные блокировки. Создание CRM остаётся последовательным.
- LeadChat возвращает сообщение в состоянии pending до фактической доставки. Расширение теперь ждёт подтверждения именно отправленного сообщения до восьми секунд. Ошибка или неизвестный исход не вызывает повторный POST.
- Ожидание после ответа оператора показывается как ожидание клиента, а не как неизвестная услуга или территория.
- Перед отправкой видны аккаунт объявления и город, имя аккаунта есть на кнопке отправки. Перед созданием показаны поля заявки. Подробности причин пропуска сохраняются открытыми при обновлениях.

## Проверки и границы результата

Прошли **{python_count} Python-тестов и {node_count} Node-тестов**, покрытие пяти основных модулей — 93%. Проверены актуальная серверная политика, одноразовое разрешение без авто, отказ при повторном коде, MAX, очередь, параллельная работа и ожидание доставки. Изолированная цепочка с настоящим Node/HTTP кодом проверена по одному шагу; внешние отправки и CRM в ней синтетические. Ранее на браузерном стенде сверены 18 полей синтетической заявки без расхождений.

Повторный прогон текущих правил: 2 617 замороженных срезов реальной истории и 469 будущих срезов двух дополнительных авторов. На последней выборке: {extra['counts'].get('question', 0)} вопросов, {extra['counts'].get('handoff', 0)} передач оператору. Проверяемых нарушений контракта нет; модель не вызывалась. Это проверка правил и ограничений, а не процент правильности всех ответов и не оценка конверсии. Проверенная выборка 51 реального диалога также пройдена. Полная доступная история Глеба и Зухратдина ранее разобрана: 12 333 диалога / 221 864 сообщения; эти данные не означают дообучение весов модели.

В рабочем LeadChat выполнено чтение очереди и историй. Проверена существующая отменённая заявка №2693534: повторное создание блокируется. Это не проверка новой созданной заявки. В данном пилоте реальных взятий, клиентских отправок и новых CRM-заявок **ноль**. Постоянный авто выключен. Репетиция может читать очередь и готовить планы; каждый реальный ответ сначала требует отдельной проверки и разрешения.

100% точность гарантировать нельзя. Шесть спорных строк матрицы и неизвестные условия остаются оператору. Для завершения боевого допуска ещё нужны подходящий реальный диалог, проверенная отправка и создание с последующим чтением фактической карточки CRM.

[Архив]({archive}) · [Как пользоваться]({OUT / f'LeadChat-{version}-install.md'}) · [Проверки и хеши]({OUT / f'LeadBot-verification-{version}.json'})

![Помощник на Mac, авто выключен]({OUT / 'LeadBot-2.7.1-helper.png'})
""")
print(json.dumps({"archive": archive.name, "files": len(files), "sha256": sha, "python": python_count, "node": node_count, "auto_enabled": False}))
