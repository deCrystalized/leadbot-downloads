"""Export only aggregate evidence and reviewed rules; private dialogue data stays local."""
import csv
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parents[1] / 'outputs'
read = lambda name: json.loads((ROOT / name).read_text())
catalog = read('leadbot/brain/reviewed_catalog.json')
registry = read('leadbot/brain/policy_registry.json')
audit = read('test-artifacts/round2/complete-dialogue-audit.json')
style_audit = read('test-artifacts/round2/corpus-audit.json')
holdout = read('test-artifacts/round2/full-holdout-replay.json')
dataset = read('test-artifacts/dataset-summary.json')
style = read('leadbot/brain/style_examples.json')['examples']
remaining = [r for r in registry['matrix_review'] if r['requires_semantic_review']]
old_disputed = sum(r.get('original_requires_semantic_review', False) for r in registry['matrix_review'])
old_unresolved = sum(r.get('original_requires_semantic_review', False) for r in remaining)
production_lines = (ROOT / 'test-artifacts/round2/final-production-verification.log').read_text().splitlines()
production = [json.loads(line) for line in production_lines if line.startswith('{')]
assert production[0]['hashes_verified'] == 13 and production[0]['auto_enabled'] is False
assert production[1]['v'] == '2.1.3' and production[1]['policy_version'] == registry['version']
assert production_lines[-4:] == ['active', 'active', 'active', 'inactive']
deployment = [json.loads(line) for line in (ROOT / 'test-artifacts/round2/final-deploy.log').read_text().splitlines() if line.startswith('{')][0]
live = read('test-artifacts/round2/live-and-production-results.json')
live_cases = [r for r in live if r.get('type') == 'case']
assert len(live_cases) == 14 and all(r['passed'] for r in live_cases)
archive = OUT / 'LeadChat-2.4.1.zip'
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for p in (ROOT / 'ext').rglob('*'):
        if p.is_file():
            assert z.read('LeadChat-2.4.1/' + str(p.relative_to(ROOT / 'ext'))) == p.read_bytes()
    package = {'file': archive.name, 'version': '2.4.1', 'entries': len(z.namelist()), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'permissions_expanded': False, 'installed_in_user_browser': False}
report = {
    'date': '2026-10-15', 'brain_version': '2.1.3', 'policy_version': registry['version'],
    'auto_enabled': False, 'automatic_crm_create': False,
    'corpus': {k: audit[k] for k in ('available_conversations', 'unique_messages', 'named_human_outbound_messages', 'historical_bot_outbound_messages')},
    'style_audit': {k: style_audit[k] for k in ('blocks_examined', 'human_dialogues', 'first_utc', 'last_utc', 'reply_chars')},
    'rules': {'primary_fragments': len(registry['sources']), 'legacy_rows_reviewed': len(catalog['matrix_review']), 'typed_service_groups': len(catalog['rules']), 'previous_disputed_rows': old_disputed, 'previous_disputed_rows_resolved': old_disputed-old_unresolved, 'rows_awaiting_external_confirmation': len(remaining), 'remaining': remaining},
    'style_learning': {'individually_reviewed_questions': len(style), 'client_overlap_with_frozen_evaluation': 0, 'source_before_utc': '2026-10-01T00:00:00+00:00', 'full_dialogue_finetuning': False, 'uploaded_training_examples': 0, 'candidate_partitions': dataset['partitions']},
    'verification': {'python_tests_passed': 107, 'node_integration_tests_passed': 15, 'failed': 0, 'core_python_modules': 8, 'core_statement_coverage_percent': 89, 'ruff': 'passed', 'mypy_basic_checks': 'passed', 'python_compile': 'passed', 'brain_build': 'passed', 'synthetic_live_cases': {'passed': 14, 'model_responses_including_cache': 6, 'deterministic_or_handoff': 8, 'model': 'GigaChat-2-Pro', 'policy_at_live_model_test': '2026-10-15.2'}, 'final_matrix_boundary_cases_on_production': 5, 'frozen_holdout': holdout, 'production': production},
    'contact_replay_previous_stage': read('test-artifacts/contact-replay-summary.json'),
    'deployment': {'host': '72.56.68.159', 'leadbot': 'active', 'lc_brain': 'active', 'gateway': 'active', 'staging_service': 'stopped', 'latest_backup': deployment['backup'], 'backup_before_this_iteration': '/root/leadbot-release-backups/20261015-055600', 'verified_changed_file_hashes': 13, 'leadchat_server_modified': False, 'crm_records_modified': False, 'customer_messages_sent': 0},
    'package': package,
    'limitations': ['Only available exported history was inspected; deleted or missing data is unavailable.', '2617 offline cases check contracts and fail-closed behavior, not model quality or conversion.', '14 live synthetic cases are a small integration check; final stricter matrix/presence changes were checked offline and with deterministic production tests.', 'Cartridge, satellite-TV and Elista conflicts require an operator; KP operational status in Ulyanovsk, Stavropol and Nevinnomyssk is also gated.', 'Telegram exports lack 84 photos and 37 files.', 'No guarantee of human-equivalent communication or full autonomous regulation coverage; automatic mode remains disabled.', 'Client package must be updated in the working browser.'],
}
(OUT / 'LeadBot-verification-2.4.1.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
pending_ids = {r['id'] for r in remaining}
with (OUT / 'LeadBot-rules-review-2026-10-15.csv').open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Позиция', 'Вид работ/правило', 'Решение', 'Нужна внешняя проверка', 'Первоисточники', 'Пояснение'])
    for row in catalog['matrix_review']:
        writer.writerow([row['id'], row['title'], row['status'], row['id'] in pending_ids, '; '.join(row['primary_refs']), row['resolution']])

text = f"""# LeadBot: доработка правил и переписок — 15.10.2026

На lead-bot-nl установлены мозг 2.1.3 и правила {registry['version']}. Подготовлено расширение 2.4.1. **Автоматическое общение и создание заявок выключены на сервере.** Рабочий сервер LeadChat и карточки CRM не изменялись; сообщения клиентам не отправлялись. Этот отчёт заменяет результаты этапа 2.4.0 в части правил и оценки.

## Что разобрано

Обработана вся доступная выгрузка: 14 478 диалогов и 257 239 уникальных сообщений с хронологией, типами отправителя и состоянием доставки. В ней 49 150 исходящих сообщений Мамонтова Георгия и Скорохода Ильи, объединённых в 36 322 блока ответов в 14 053 диалогах. Доступные ответы этих двух сотрудников датируются 26 августа — 15 октября 2026 по UTC. «Вся выгрузка» означает автоматический разбор каждого доступного сообщения; это не заявление о ручном прочтении каждого текста или восстановлении удалённой истории.

Повторно прочитаны актуальные общий регламент и документ КП: содержательных изменений относительно предыдущей загруженной версии нет. Все 273 пункта старой матрицы сопоставлены с первоисточниками и разобраны по смыслу. Из 89 ранее отмеченных спорных пунктов 84 получили решение. Пять старых и один дополнительно выявленный пункт требуют внешнего подтверждения. В серверном реестре 3 122 фрагмента источников; 91 группа услуг имеет явные условия выбора и уточнений. Статус «принимается» не отменяет обязательные вопросы, согласование и проверку оператором.

## Какие изменения внесены

- **Партнёр 723:** по вашему уточнению действует общий прайс КП. На этапе фиксированной цены Windows, Office и чистка — 2 000 ₽; правило выезда/диагностики этим уточнением не меняется. Цена выбирается сервером по конкретной услуге и этапу, а не по похожим словам в старом чате. После озвучки проверяется согласие; отказ клиента не обходится обещанием скидки или оформления.
- **Матрица ТВ:** подтверждённая поломка/фактические полосы ведут к отказу либо согласованию. Предположение «возможно, матрица» и гипотетические полосы ведут к уточнению типа ТВ, модели и повреждения. Ремонт не обещается. Мониторы и ноутбуки проверяются по своим правилам.
- **Условия приёма:** отдельно проверяются лицензия для специальных программ, проведённый интернет для роутера, подготовка воды/электрики, тип кофемашины и плиты, закладная под натяжным потолком, готовность пола, материалы, место и объём работ. Частное правило, например дверца духовки, имеет приоритет перед общим разрешением на детали. Смешанные работы и передачи между КП/БТ/МНЧ сохраняются для оператора.
- **Факты из диалога:** заданный вопрос не считается полученным ответом. «Да» после вопроса с выбором или нескольких вопросов не угадывает нужный вариант. Более поздний явный ответ заменяет ранний. Присутствие клиента отдельно не подтверждает право принимать решение и оплачивать работу. После двух безрезультатных попыток уточнения подключается оператор.
- **Доставка и вложения:** неотправленный ответ не считается заданным вопросом; отправляющийся ответ требует ожидания. Системные уведомления не становятся фактами клиента. Голосовое учитывается только с расшифровкой; фотографии и неизвестные вложения требуют просмотра оператором.
- **Обязательные сведения:** фраза для партнёра 620 добавляется сервером. Сохраняются правило Jivo об источнике, имени мастера/аккаунта и имени представления, а также прежние поля комментария. Бот не придумывает новое имя без решения оператора.
- **Территория:** Дудинка оформляется через Норильск с отдельным населённым пунктом и дальним выездом; Зеленодольск — через Казань; Златоуст требует согласования с Челябинском. Прежние проверенные правила Кургана, Феодосии, Коврова и зон Мытищ сохранены.
- **Сбои и устаревание:** после обновления правил прежние черновики нельзя использовать. Повторный запрос не запускает дополнительный вызов модели. При сбое провайдера или неверном формате доступен проверенный сервером следующий вопрос; корректно оформленный, но нарушающий правила ответ модели передаётся оператору. Исходные карточки правил не меняются от повторных запросов.

## Манера общения и проверка качества

В доступных человеческих блоках медианная длина ответа — 41 символ. Для помощника вручную допущены 67 коротких формулировок вопросов: без цен, обещаний, персональных контактов и выводов об успешности заявки. Их исходные диалоги относятся к периоду до 1 октября и не пересекаются по известным клиентам с отложенной выборкой. Модель получает подходящие примеры и один следующий вопрос, выбранный сервером.

Полноценное дообучение весов модели на переписках не проводилось; исходный корпус никуда не загружался для обучения. Исторические ответы сотрудников и старого бота служат материалом анализа, а не доказательством правильности: звонки, согласования и действия вне LeadChat могут быть недоступны.

Прошли **107 Python-тестов и 15 интеграционных Node-тестов**, Ruff, базовая проверка Mypy, компиляция Python, синтаксис JS и сборка мозга. Покрытие восьми основных Python-модулей — 89% операторов. Тесты проверяют авторизацию, изоляцию владельца, факты, условия, цены, актуальность черновика, повторы, сбои модели и блокировку отправки.

На финальной версии повторены 2 617 отложенных ходов с предшествующей историей: {holdout['counts']['draft']} запрос формулировки следующего вопроса, {holdout['counts']['question']} ответов/уточнений по правилам, {holdout['counts']['handoff']} передачи оператору, {holdout['counts']['wait']} ожиданий и {holdout['counts']['refuse']} отказа. Проверенные серверные вопросы прошли ограничения без ошибок; модель в этом прогоне не вызывалась. **Это проверка контракта и ограничений, а не измерение качества модели, конверсии или сходства с человеком.**

В изолированном серверном прогоне прошли 14 вымышленных сценариев: шесть ответов GigaChat-2-Pro, включая кэшированные, и восемь решений по правилам/передач оператору. Этот прогон выполнен на правилах 2026-10-15.2; последующие ужесточения матрицы и подтверждения условий проверены тестами, а пять случаев матрицы — дополнительно через рабочий сервер без вызова модели. Настоящие клиентские сообщения при этих проверках не отправлялись.

Прежний прогон телефонного парсера распознал все 70 ранее выявленных пропусков среди доступных клиентских сообщений. Исторические карточки не исправлялись автоматически. Ранее сверенные структура CRM, комментарии и адресные поля сохранены; новая запись в CRM не выполнялась.

## Что осталось оператору

| Тема | Почему нужен оператор |
|---|---|
| Картриджи — MATRIX-113, 243 | Документ допускает согласование, отдельное объявление запрещает |
| Спутниковое ТВ — MATRIX-042, 124, 229 | Общий документ и отдельное объявление расходятся |
| Элиста КП — MATRIX-264 | Закрытие в канале расходится с доступностью города в CRM; ваше последнее уточнение не определило статус |
| Ульяновск, Ставрополь, Невинномысск КП | Закрытие в канале расходится с локальным справочником; действующий приём требует подтверждения |

В Telegram-экспортах отсутствуют 84 фотографии и 37 файлов. Удалённые диалоги и недоступные записи звонков восстановить из этих данных нельзя. Условия, требующие филиала, звонка или фактического подтверждения выезда, сохраняют участие оператора.

## Установка и состояние сервера

Сверены SHA-256 всех 13 изменённых за этот этап серверных файлов. LeadBot, мозг и шлюз активны; временный тестовый сервис остановлен. Скомпилированный вход мозга проверен с личным токеном и реальным внутренним подключением к LeadBot. Запрос без токена возвращает 401, попытка отправки через новый API — 403. Служебный ключ остаётся на сервере.

Последняя резервная копия: `{deployment['backup']}`. Копия перед всей текущей итерацией: `/root/leadbot-release-backups/20261015-055600`.

Пакет расширения 2.4.1 содержит 36 файлов, совпадает с исходниками и не расширяет разрешения Chrome. В рабочем браузере он ещё не установлен; архив нужно обновить вручную. SHA-256: `{package['sha256']}`.

Бот работает через панель расширения: подготовить черновик → проверить → скопировать. Перенос контактов меняет только локальную форму заявки. Автоматический режим остаётся выключенным; сходство с сотрудниками и безошибочное выполнение всего регламента ещё не доказаны достаточной размеченной проверкой.

- [Расширение 2.4.1]({OUT / 'LeadChat-2.4.1.zip'})
- [Инструкция обновления]({OUT / 'LeadChat-2.4.1-install.md'})
- [Все 273 разобранных пункта]({OUT / 'LeadBot-rules-review-2026-10-15.csv'})
- [Подробные результаты JSON]({OUT / 'LeadBot-verification-2.4.1.json'})
- [Общий регламент](https://docs.google.com/document/d/1VJuB4kz8eqtXs0JjGgSeFt0pwD_Wqq6J84j8B1sAQtw/edit)
- [Документ КП](https://docs.google.com/document/d/1hAOnFGyISfYVGjtZCw0Aq_IfEmZmZYAZ1P5NZUrVG5Y/edit)
"""
(OUT / 'LeadBot-review-2026-10-15.md').write_text(text)
(OUT / 'LeadChat-2.4.1-install.md').write_text("""# Обновление LeadChat до 2.4.1

Сервер уже обновлён. Адрес мозга и личный токен прежние. Автоматическое общение и автоматическое создание заявок выключены.

1. Распакуйте архив `LeadChat-2.4.1.zip`.
2. Если LeadChat установлен распакованным расширением, замените содержимое его текущей папки файлами из `LeadChat-2.4.1`. Сохраните прежний путь папки, чтобы сохранить идентификатор и настройки расширения.
3. В `chrome://extensions` нажмите «Обновить» на карточке LeadChat, затем перезагрузите страницу LeadChat.
4. Откройте в панели заявки **✦ «Помощник по регламенту» → «Подготовить ответ»**.
5. Проверьте черновик. Кнопка «Скопировать ответ» повторно проверяет его актуальность. Ответ отправляет оператор. «Использовать контакты в заявке» переносит данные только в локальную форму; создание заявки требует обычного подтверждения.

Если расширение ещё не установлено: включите режим разработчика в `chrome://extensions`, нажмите «Загрузить распакованное расширение» и выберите папку с `manifest.json`. Укажите существующий личный токен мозга в настройках расширения. Серверный ключ и пароль CRM для этого не нужны.

После нового сообщения, смены диалога или обновления правил подготовьте новый черновик. «Пауза» блокирует использование старого ответа. При неясном условии помощник передаёт решение оператору.
""")
print(json.dumps({'report': 'LeadBot-review-2026-10-15.md', 'brain': report['brain_version'], 'rules': len(catalog['matrix_review']), 'old_disputes_resolved': old_disputed-old_unresolved, 'remaining_rows': len(remaining), 'style_questions': len(style), 'auto_enabled': False}))
